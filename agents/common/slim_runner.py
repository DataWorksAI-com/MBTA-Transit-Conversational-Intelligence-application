"""
SLIM Transport Runner — agents/common/slim_runner.py
=====================================================
Generic SLIM server wrapper for any MBTA A2A agent.

Each agent calls run_slim_server() alongside its existing uvicorn A2A server.
This registers the agent with the SLIM controller so the exchange can reach it
via SLIM transport (instead of plain HTTP SSE).

Transport stack:
  Exchange  →  SLIM Controller (:46357)  →  Agent SLIM listener
                                              ↓
                                         DefaultRequestHandler
                                              ↓
                                         AgentExecutor.execute()

Environment variables (set per agent in supervisor):
  SLIM_ENDPOINT     = http://96.126.111.107:46357  (SLIM controller)
  SLIM_SHARED_SECRET= <32+ char secret, same on all agents + exchange>
  SLIM_ORG          = mbta
  SLIM_NS           = transit-ci
  SLIM_LABEL        = alerts | planner | stopfinder
"""

import asyncio
import logging
import os
from uuid import uuid4

logger = logging.getLogger(__name__)

SLIM_ENDPOINT      = os.getenv("SLIM_ENDPOINT",      "http://96.126.111.107:46357")
SLIM_SHARED_SECRET = os.getenv("SLIM_SHARED_SECRET", "")
SLIM_ORG           = os.getenv("SLIM_ORG",           "mbta")
SLIM_NS            = os.getenv("SLIM_NS",            "transit-ci")
SLIM_LABEL         = os.getenv("SLIM_LABEL",         "")   # alerts / planner / stopfinder

# ── Prompt Firewall (data-plane guard for the SLIM transport) ───────────────────
# The HTTP data path goes through the standalone firewall service (DANS /resolve
# returns a /firewall/proxy/<label> URL). SLIM is a *different* transport, so
# without this hook it would be a way to reach the agent while bypassing the
# firewall. We close that gap by calling the firewall's dry-run endpoint before
# the message reaches the agent executor.
#
#   FIREWALL_URL       base URL of the firewall service (e.g.
#                      http://97.107.132.213/firewall  or  http://localhost:8300)
#                      If unset, the SLIM firewall guard is disabled.
#   FIREWALL_FAIL_OPEN "true" (default) → if the firewall is unreachable, let the
#                      request through (availability over strictness). Set to
#                      "false" to fail closed (block when the firewall is down).
FIREWALL_URL       = os.getenv("FIREWALL_URL", "").rstrip("/")
FIREWALL_FAIL_OPEN = os.getenv("FIREWALL_FAIL_OPEN", "true").lower().strip() != "false"
_FIREWALL_TIMEOUT  = float(os.getenv("FIREWALL_TIMEOUT", "5"))


def _extract_text(message) -> str:
    """Pull the user text out of an a2a Message (mirrors the agent executors)."""
    try:
        for part in message.parts:
            if hasattr(part, "root") and hasattr(part.root, "text"):
                return part.root.text
            if hasattr(part, "text"):
                return part.text
    except Exception:
        pass
    return ""


class FirewallGuardExecutor:
    """
    Wraps an a2a AgentExecutor and runs every inbound SLIM message through the
    Prompt Firewall (POST {FIREWALL_URL}/firewall/test) before delegating to the
    real executor. If the firewall returns action == "block", the request is
    refused and the agent never sees it — so SLIM enforces the same policy as
    the HTTP /proxy path instead of bypassing it.
    """

    def __init__(self, inner, label: str, firewall_url: str):
        self._inner = inner
        self._label = label
        self._firewall_url = firewall_url

    async def _check(self, text: str) -> dict:
        """Return the firewall verdict dict, or {} if the check could not run."""
        import httpx
        url = f"{self._firewall_url}/firewall/test"
        try:
            async with httpx.AsyncClient(timeout=_FIREWALL_TIMEOUT) as client:
                resp = await client.post(url, json={
                    "label": self._label,
                    "body":  {"message": text},
                })
            if resp.status_code == 200:
                return resp.json()
            logger.warning(f"🔥 firewall check HTTP {resp.status_code} for {self._label}")
        except Exception as exc:
            logger.warning(f"🔥 firewall unreachable ({exc}) for {self._label}")
        return {}

    async def execute(self, context, event_queue):
        text = _extract_text(context.message)
        verdict = await self._check(text)

        if verdict:
            action = verdict.get("action", "pass")
            if action == "block":
                reason = verdict.get("reason") or verdict.get("rule_id") or "policy"
                logger.warning(f"🚫 SLIM firewall BLOCKED {self._label}: {reason}")
                from a2a.types import Message, TextPart
                await event_queue.enqueue_event(Message(
                    message_id=str(uuid4()),
                    parts=[TextPart(text=(
                        "🚫 This request was blocked by the Prompt Firewall "
                        f"(reason: {reason})."
                    ))],
                    role="agent",
                ))
                return
        elif not FIREWALL_FAIL_OPEN:
            # Firewall could not be reached and we are configured to fail closed.
            logger.warning(f"🚫 SLIM firewall FAIL-CLOSED block for {self._label}")
            from a2a.types import Message, TextPart
            await event_queue.enqueue_event(Message(
                message_id=str(uuid4()),
                parts=[TextPart(text=(
                    "🚫 Request rejected: the Prompt Firewall is unavailable "
                    "and this transport is configured to fail closed."
                ))],
                role="agent",
            ))
            return

        # Passed (or firewall down + fail-open) → hand off to the real executor.
        await self._inner.execute(context, event_queue)

    async def cancel(self, context, event_queue):
        return await self._inner.cancel(context, event_queue)


async def run_slim_server(agent_card, executor, task_store):
    """
    Register this agent with the SLIM controller and serve incoming A2A requests.

    Blocks until the process is killed — call from asyncio.run() in each
    agent's run_slim.py entry point.

    Args:
        agent_card:  a2a.types.AgentCard instance (same card the A2A server uses)
        executor:    AgentExecutor subclass instance (AlertsExecutor, etc.)
        task_store:  InMemoryTaskStore() instance
    """
    if not SLIM_LABEL:
        raise RuntimeError("SLIM_LABEL env var must be set (alerts / planner / stopfinder)")
    if not SLIM_SHARED_SECRET:
        raise RuntimeError(
            "SLIM_SHARED_SECRET env var must be set (≥32 chars, same value on all servers)"
        )
    if len(SLIM_SHARED_SECRET) < 32:
        raise RuntimeError(
            f"SLIM_SHARED_SECRET too short ({len(SLIM_SHARED_SECRET)} chars) — need ≥32"
        )

    identity = f"{SLIM_ORG}/{SLIM_NS}/{SLIM_LABEL}"
    logger.info(f"🔌 Starting SLIM transport: identity={identity} endpoint={SLIM_ENDPOINT}")

    # Guard the SLIM path with the Prompt Firewall so it can't be used to bypass
    # the policy the HTTP /proxy path enforces. No-op if FIREWALL_URL is unset.
    if FIREWALL_URL:
        logger.info(
            f"🔥 SLIM Prompt Firewall guard enabled → {FIREWALL_URL} "
            f"(fail_{'open' if FIREWALL_FAIL_OPEN else 'closed'})"
        )
        executor = FirewallGuardExecutor(executor, SLIM_LABEL, FIREWALL_URL)
    else:
        logger.warning(
            "⚠️  FIREWALL_URL not set — SLIM transport is NOT firewall-guarded"
        )

    try:
        from agntcy_app_sdk.factory import AgntcyFactory
        from agntcy_app_sdk.semantic.a2a.server.srpc import (
            A2ASlimRpcServerConfig,
            SlimRpcConnectionConfig,
        )
        from a2a.server.request_handlers import DefaultRequestHandler
    except ImportError as exc:
        raise ImportError(
            "agntcy-app-sdk not installed. Run:\n"
            "  pip install agntcy-app-sdk==0.5.5 slim-bindings==1.3.0"
        ) from exc

    config = A2ASlimRpcServerConfig(
        agent_card=agent_card,
        request_handler=DefaultRequestHandler(
            agent_executor=executor,
            task_store=task_store,
        ),
        connection=SlimRpcConnectionConfig(
            identity=identity,
            shared_secret=SLIM_SHARED_SECRET,
            endpoint=SLIM_ENDPOINT,
        ),
    )

    factory = AgntcyFactory()
    session = factory.create_session(config)

    logger.info(f"✅ SLIM registered: {identity} @ {SLIM_ENDPOINT}")
    logger.info(f"   Waiting for incoming A2A requests via SLIM...")

    # Blocks until process exits — keep_alive=True means reconnect on drop
    await session.start_all_sessions(keep_alive=True)
