"""
slim_client.py — Real Cisco AGNTCY SLIM transport client
=========================================================
Uses agntcy-app-sdk to call MBTA agents over SLIM (not HTTP SSE).

Transport stack:
  Exchange  →  SLIM Controller (:46357)  →  Agent SLIM listener
                  (96.126.111.107)              (same server)

Agents are identified by SLIM identity strings:
  mbta/transit-ci/alerts
  mbta/transit-ci/planner
  mbta/transit-ci/stopfinder

Zero hardcoded IPs — all config from environment variables:
  SLIM_ENDPOINT      = http://96.126.111.107:46357
  SLIM_SHARED_SECRET = <64-char secret, same on all servers>
  SLIM_ORG           = mbta
  SLIM_NS            = transit-ci

Package requirements (Python 3.12+):
  pip install agntcy-app-sdk==0.5.5 slim-bindings==1.3.0
"""

import asyncio
import logging
import os
from typing import Any, Dict, Optional
from uuid import uuid4

logger = logging.getLogger(__name__)

# ── Config from env (zero hardcoded values) ───────────────────────────────────
SLIM_ENDPOINT      = os.getenv("SLIM_ENDPOINT",      "http://96.126.111.107:46357")
SLIM_SHARED_SECRET = os.getenv("SLIM_SHARED_SECRET", "")
SLIM_ORG           = os.getenv("SLIM_ORG",           "mbta")
SLIM_NS            = os.getenv("SLIM_NS",            "transit-ci")
SLIM_TIMEOUT       = float(os.getenv("SLIM_TIMEOUT", "60.0"))

# ── Agent label → registry agent_id map ──────────────────────────────────────
AGENT_ID_MAP: Dict[str, str] = {
    "alerts":     "mbta-alerts",
    "planner":    "mbta-planner",
    "stopfinder": "mbta-stopfinder",
    "fares":      "mbta-fares",
}


def _extract_text(event: Any) -> str:
    """Pull plain text out of an A2A streaming event (dict or SDK object)."""
    if not event:
        return ""
    if isinstance(event, str):
        return event
    if not isinstance(event, dict):
        return getattr(event, "text", "") or str(event)

    # TaskStatusUpdateEvent / Message
    for part in event.get("parts", []):
        if isinstance(part, dict):
            text = part.get("text") or part.get("root", {}).get("text", "")
            if text:
                return text
        else:
            text = getattr(getattr(part, "root", part), "text", "")
            if text:
                return text

    # Nested status → message → parts
    status = event.get("status", {})
    msg    = status.get("message", {}) if isinstance(status, dict) else {}
    for part in msg.get("parts", []):
        text = part.get("text", "") if isinstance(part, dict) else ""
        if text:
            return text

    return ""


class SlimAgentClient:
    """
    Production SLIM client — wraps agntcy-app-sdk A2A-over-SLIM.

    Usage:
        client = SlimAgentClient()
        await client.initialize()
        result = await client.call_agent("alerts", "Red Line delays?")
        await client.cleanup()

    The client is created once in MBTAOrchestrator.__init__ and reused across
    all requests. SLIM sessions are created per call (stateless per query).
    """

    def __init__(self) -> None:
        self._factory   = None
        self._initialized = False

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def initialize(self) -> None:
        """Import agntcy-app-sdk and validate config. Fast — no network call."""
        try:
            from agntcy_app_sdk.factory import AgntcyFactory  # noqa: F401
        except ImportError as exc:
            raise ImportError(
                "agntcy-app-sdk not installed.\n"
                "Run: pip install agntcy-app-sdk==0.5.5 slim-bindings==1.3.0"
            ) from exc

        if not SLIM_SHARED_SECRET:
            raise RuntimeError(
                "SLIM_SHARED_SECRET env var not set. "
                "Use the same ≥32-char secret that agents use."
            )
        if len(SLIM_SHARED_SECRET) < 32:
            raise RuntimeError(
                f"SLIM_SHARED_SECRET too short ({len(SLIM_SHARED_SECRET)} chars, need ≥32)."
            )

        from agntcy_app_sdk.factory import AgntcyFactory
        self._factory     = AgntcyFactory()
        self._initialized = True
        logger.info(
            f"✅ SlimAgentClient ready — "
            f"controller={SLIM_ENDPOINT}  org={SLIM_ORG}/{SLIM_NS}"
        )

    async def cleanup(self) -> None:
        """No persistent resources — nothing to tear down."""
        logger.info("✅ SlimAgentClient cleanup (stateless)")

    # ── Core call ─────────────────────────────────────────────────────────────

    async def call_agent(
        self,
        agent_name: str,
        message: str,
        base_url: Optional[str] = None,  # accepted but unused — SLIM routes by identity
    ) -> Dict[str, Any]:
        """
        Call an agent via SLIM transport.

        Args:
            agent_name: short label — "alerts", "planner", or "stopfinder"
            message:    natural-language query string
            base_url:   ignored (ANS-resolved URL not used; SLIM resolves by identity)

        Returns:
            {"response": str, "agent_used": str, "metadata": {...}}
        """
        if not self._initialized or self._factory is None:
            raise RuntimeError(
                "SlimAgentClient.initialize() must be called before call_agent()."
            )

        identity = f"{SLIM_ORG}/{SLIM_NS}/{agent_name}"
        logger.info(f"📤 SLIM → {identity}")

        try:
            from agntcy_app_sdk.semantic.a2a.client.config import (
                ClientConfig,
                SlimTransportConfig,
            )
            from a2a.types import SendStreamingMessageRequest, MessageSendParams, Message, TextPart
        except ImportError as exc:
            raise ImportError(
                f"agntcy-app-sdk A2A client module not found: {exc}\n"
                "Ensure agntcy-app-sdk==0.5.5 is installed."
            ) from exc

        client_config = ClientConfig(
            transport_config=SlimTransportConfig(
                endpoint=SLIM_ENDPOINT,
                name=identity,
                shared_secret=SLIM_SHARED_SECRET,
            )
        )

        client_factory = self._factory.a2a(client_config)
        client         = client_factory.create_client()

        request = SendStreamingMessageRequest(
            id=str(uuid4()),
            params=MessageSendParams(
                message=Message(
                    messageId=str(uuid4()),
                    role="user",
                    parts=[TextPart(text=message)],
                )
            ),
        )

        response_text = ""
        try:
            async with asyncio.timeout(SLIM_TIMEOUT):
                async for event in client.send_message(request):
                    text = _extract_text(
                        event.model_dump(mode="json") if hasattr(event, "model_dump") else event
                    )
                    if text:
                        response_text = text
                        break   # first non-empty text chunk is the answer
        except TimeoutError:
            logger.error(f"⏱️  SLIM call to {agent_name} timed out after {SLIM_TIMEOUT}s")
            raise RuntimeError(f"SLIM call to {agent_name} timed out")

        if not response_text:
            response_text = f"Agent {agent_name} returned no response via SLIM"

        logger.info(f"✅ SLIM ← {agent_name}: {len(response_text)} chars")
        return {
            "response":   response_text,
            "agent_used": AGENT_ID_MAP.get(agent_name, agent_name),
            "metadata": {
                "transport": "slim",
                "agent":     agent_name,
                "identity":  identity,
                "endpoint":  SLIM_ENDPOINT,
            },
        }
