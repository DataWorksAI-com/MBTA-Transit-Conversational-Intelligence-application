# agents/common/registry_client.py

"""
DANS Registration Client — registers MBTA agents with the DANS nameservice.

Wraps agentns.target_lib with the same RegistryClient interface used by
all MBTA agents (alerts, planner, stopfinder, fares).  Agent code requires
no changes — just update environment variables.

Configuration (environment variables, read at startup):
  AGENTNS_URL   — DANS endpoint  (default: http://97.107.132.213/dans)
  ANS_LABEL     — Short label to register under. Must match MBTA_URNS key suffix.
                  e.g. "alerts", "planner", "stopfinder", "fares"
  ANS_TLD       — URN TLD        (default: agents.dataworksai.com)
  ANS_APP       — URN namespace  (default: mbta-transit-ci)
  AGENT_REGION  — DANS region tag (default: us-east)
  AGENT_CITY    — City for geo-routing (default: Newark)
"""

import asyncio
import atexit
import logging
import os
import time
from threading import Thread
from typing import List, Optional

import agentns
import agentns.target_lib as _target_lib

logger = logging.getLogger(__name__)


class RegistryClient:
    """
    DANS registration client — keeps this agent's endpoint live in DANS.

    Features:
    - Auto-registration on startup (idempotent — safe to call multiple times)
    - Periodic re-registration heartbeat (refreshes TTL in DANS)
    - Graceful deregistration on shutdown
    - Retry logic on registration failure (built into agentns.target_lib)
    """

    def __init__(self, registry_url: Optional[str] = None):
        # registry_url accepted for backward compat but ignored — we always use AGENTNS_URL
        ns_url = os.getenv("AGENTNS_URL", "http://97.107.132.213/dans")
        self._client = _target_lib.connect(ns_url=ns_url)
        self._leaf_name: Optional[str] = None
        self._a2a_url: Optional[str] = None
        self._should_run = False
        self._heartbeat_thread: Optional[Thread] = None
        # Keep registry_url attr for any code that inspects it
        self.registry_url = ns_url
        logger.info(f"DANS RegistryClient → {ns_url}")

    # ── register ──────────────────────────────────────────────────────────────

    def register(
        self,
        agent_id: str,
        agent_url: str,
        api_url: str,
        capabilities: Optional[List[str]] = None,
        tags: Optional[List[str]] = None,
    ) -> None:
        """
        Register this agent with DANS.

        Args:
            agent_id:     Unique agent identifier (e.g. "mbta-alerts-agent")
            agent_url:    Base URL where agent is accessible
            api_url:      API endpoint URL (kept for interface compat, not sent to DANS)
            capabilities: Ignored (DANS routes by name, not capability)
            tags:         Ignored (DANS routes by name, not tag)
        """
        self._a2a_url = agent_url
        label = os.getenv("ANS_LABEL", "")
        if not label:
            # Derive label from agent_id: "mbta-alerts-agent" → "alerts"
            label = agent_id.replace("mbta-", "").replace("-agent", "")
            logger.warning(
                f"ANS_LABEL not set — derived '{label}' from agent_id '{agent_id}'. "
                "Set ANS_LABEL in supervisor config to be explicit."
            )
        self._leaf_name = label

        region = os.getenv("AGENT_REGION", "us-east")
        city   = os.getenv("AGENT_CITY", "Newark")

        spec = _target_lib.DeploymentSpec(
            leaf_name  = label,
            a2a_url    = agent_url,
            health_url = f"{agent_url}/health",
            region     = region,
            location   = {"city": city},
            protocols  = ["A2A"],
        )

        logger.info(f"Registering '{label}' → {agent_url} in DANS ({self.registry_url})…")

        # Run async record() from synchronous context
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # Inside an async framework (FastAPI / uvicorn) — schedule as a task
                asyncio.ensure_future(self._record_async(spec))
            else:
                loop.run_until_complete(self._record_async(spec))
        except RuntimeError:
            # No event loop yet — create one just for registration
            asyncio.run(self._record_async(spec))

        # Register cleanup + start heartbeat re-registration
        atexit.register(self._deregister_sync)
        self._start_heartbeat(spec)

    async def _record_async(self, spec: _target_lib.DeploymentSpec) -> None:
        """Async wrapper: call target_lib.record() and log the result."""
        try:
            result = await self._client.record(spec)
            logger.info(f"✅ DANS registration OK: {result.get('agent_name', self._leaf_name)}")
        except Exception as exc:
            logger.error(f"❌ DANS registration failed: {exc}")
            logger.info("Agent will continue running — DANS may be temporarily unreachable.")

    # ── heartbeat (re-registration) ───────────────────────────────────────────

    def _start_heartbeat(
        self,
        spec: _target_lib.DeploymentSpec,
        interval: int = 240,
    ) -> None:
        """
        Re-register every `interval` seconds to refresh DANS TTL.

        DANS entries have a 5-minute TTL by default; re-registering every 4 min
        keeps this agent permanently visible.
        """
        self._should_run = True

        def _loop() -> None:
            while self._should_run:
                time.sleep(interval)
                if not self._should_run:
                    break
                logger.debug(f"♻️  DANS re-registration heartbeat: {self._leaf_name}")
                try:
                    loop = asyncio.new_event_loop()
                    loop.run_until_complete(self._record_async(spec))
                    loop.close()
                except Exception as exc:
                    logger.debug(f"Heartbeat re-registration failed: {exc}")

        self._heartbeat_thread = Thread(target=_loop, daemon=True, name="dans-heartbeat")
        self._heartbeat_thread.start()
        logger.info(f"💓 DANS heartbeat started ({interval}s interval)")

    def stop_heartbeat(self) -> None:
        """Stop the heartbeat thread."""
        self._should_run = False
        if self._heartbeat_thread:
            self._heartbeat_thread.join(timeout=5)
            logger.info("💓 DANS heartbeat stopped")

    # ── deregister ────────────────────────────────────────────────────────────

    def mark_offline(self) -> None:
        """Deregister from DANS (called on shutdown)."""
        if not self._leaf_name:
            return
        logger.info(f"📤 Deregistering '{self._leaf_name}' from DANS…")
        self.stop_heartbeat()
        self._deregister_sync()

    def _deregister_sync(self) -> None:
        """Synchronous deregistration — safe to call from atexit."""
        if not self._leaf_name:
            return
        try:
            loop = asyncio.new_event_loop()
            loop.run_until_complete(
                self._client.deregister(self._leaf_name, self._a2a_url or "")
            )
            loop.close()
            logger.info(f"✅ '{self._leaf_name}' deregistered from DANS")
        except Exception as exc:
            logger.warning(f"⚠️  DANS deregister failed: {exc}")


# ── Example / smoke-test ──────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    os.environ.setdefault("AGENTNS_URL", "http://97.107.132.213/dans")
    os.environ.setdefault("ANS_LABEL", "test-agent")

    client = RegistryClient()
    client.register(
        agent_id  = "mbta-test-agent",
        agent_url = "http://localhost:9000",
        api_url   = "http://localhost:9000/api",
    )

    print("Agent registered in DANS. Press Ctrl+C to deregister and exit.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        client.mark_offline()
        print("Done.")
