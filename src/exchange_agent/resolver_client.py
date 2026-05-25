"""
Production ANS Resolver Client for the MBTA Exchange Agent.

Imported by stategraph_orchestrator.py when ANS_ENABLED=true.
Resolves agent IDs → live endpoints via the Recursive Resolver service.

Configuration (from environment — zero hardcoded values):
  ANS_RESOLVER_URL      — URL of the Recursive Resolver (default: http://localhost:8200)
  ANS_RESOLVER_TIMEOUT  — HTTP timeout in seconds (default: 5.0)
  ANS_TLD               — URN top-level domain (default: agents.dataworksai.com)
  ANS_APP               — application namespace (default: mbta-transit-ci)

The orchestrator calls:
  urn = get_urn_for_agent("mbta-alerts")
  resolved = await resolver_client.resolve(urn)
  # resolved.endpoint_url, resolved.cached, resolved.latency_ms
"""

import logging
import os
import time as _time
from dataclasses import dataclass
from typing import Dict, Optional

import httpx

logger = logging.getLogger(__name__)

# ── Read configuration from environment — no hardcoded values ─────────────────
_ANS_TLD = os.getenv("ANS_TLD", "agents.dataworksai.com")
_ANS_APP = os.getenv("ANS_APP", "mbta-transit-ci")

# URN map — built entirely from env vars at import time.
# To add a new agent: add entry here and set ANS_LABEL=<label> in its supervisor config.
MBTA_URNS: Dict[str, str] = {
    "mbta-alerts":        f"urn:{_ANS_TLD}:{_ANS_APP}:alerts",
    "mbta-planner":       f"urn:{_ANS_TLD}:{_ANS_APP}:planner",
    "mbta-stopfinder":    f"urn:{_ANS_TLD}:{_ANS_APP}:stopfinder",
    "mbta-fares":         f"urn:{_ANS_TLD}:{_ANS_APP}:fares",
    # Aliases used by some orchestrator nodes
    "mbta-route-planner": f"urn:{_ANS_TLD}:{_ANS_APP}:planner",
    "mbta-stops":         f"urn:{_ANS_TLD}:{_ANS_APP}:stopfinder",
}


def get_urn_for_agent(agent_id: str) -> Optional[str]:
    """
    Return the ANS URN for a given agent_id, or None if unknown.

    Example:
      get_urn_for_agent("mbta-alerts")
      → "urn:agents.dataworksai.com:mbta-transit-ci:alerts"
    """
    return MBTA_URNS.get(agent_id)


@dataclass
class ResolvedAgent:
    """Result returned by ResolverClient.resolve()."""
    endpoint_url: str           # e.g. "http://96.126.111.107:8001"
    protocol: str               # e.g. "a2a" — DANS-negotiated protocol (lowercase)
    ttl: int                    # cache TTL in seconds
    cached: bool                # True if this was a cache hit at the resolver
    latency_ms: float           # round-trip time to the resolver (ms)
    metadata: dict              # raw metadata from DANS
    protocol_metadata: dict     # per-protocol hints: {"version": "0.2.1", "path": "/a2a/message", …}
    negotiated_by: str          # "intersection" | "agent_default" | "fallback"
    fallback_protocol: str      # next best protocol if primary fails (or "")
    warning: str                # present when negotiated_by == "fallback" (or "")


class ResolverClient:
    """
    HTTP client for the MBTA Recursive Resolver service.

    Never raises — returns None on failure so the orchestrator falls back to
    the static registry URL.
    """

    def __init__(self):
        self.resolver_url = os.getenv("ANS_RESOLVER_URL", "http://localhost:8200").rstrip("/")
        self.timeout = float(os.getenv("ANS_RESOLVER_TIMEOUT", "5.0"))
        logger.info(f"ResolverClient initialized: {self.resolver_url}")

    # Protocols this exchange agent can speak — passed to DANS so it can negotiate
    # the best match with the target agent's registered protocols.
    CALLER_PROTOCOLS = ["slim", "a2a", "http"]

    async def resolve(
        self,
        urn: str,
        requester_context: Optional[dict] = None,
        cache_enabled: bool = True,
    ) -> Optional[ResolvedAgent]:
        """
        Resolve a URN to a live agent endpoint.

        Passes CALLER_PROTOCOLS so DANS can negotiate the best protocol match.
        Returns ResolvedAgent on success, None on any failure.
        Never raises — failures are logged as warnings.
        """
        if not urn:
            return None

        # Merge caller-declared protocols into requester_context so DANS can negotiate
        ctx = dict(requester_context or {})
        if "protocols" not in ctx:
            ctx["protocols"] = self.CALLER_PROTOCOLS

        t0 = _time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(
                    f"{self.resolver_url}/resolve",
                    json={
                        "agent_name": urn,
                        "requester_context": ctx,
                        "cache_enabled": cache_enabled,
                    },
                )
        except httpx.TimeoutException:
            logger.warning(f"ANS resolver timed out for URN: {urn}")
            return None
        except Exception as exc:
            logger.warning(f"ANS resolver unreachable ({self.resolver_url}): {exc}")
            return None

        if resp.status_code != 200:
            logger.warning(f"ANS resolver returned {resp.status_code} for {urn}: {resp.text[:200]}")
            return None

        elapsed_ms = (_time.monotonic() - t0) * 1000

        try:
            data = resp.json()
        except Exception:
            logger.warning(f"ANS resolver returned invalid JSON for {urn}")
            return None

        endpoint = data.get("endpoint")
        if not endpoint:
            logger.warning(f"ANS resolver response missing 'endpoint' for {urn}")
            return None

        protocol = data.get("protocol", "http").lower()
        negotiated_by = data.get("negotiated_by", "unknown")
        fallback_protocol = data.get("fallback_protocol") or ""
        warning = data.get("warning") or ""

        logger.info(
            f"DANS protocol negotiation: {urn} → {protocol} "
            f"(negotiated_by={negotiated_by}"
            + (f", warning={warning}" if warning else "")
            + ")"
        )

        return ResolvedAgent(
            endpoint_url=endpoint,
            protocol=protocol,
            ttl=data.get("ttl", 300),
            cached=data.get("cached", False),
            latency_ms=round(elapsed_ms, 2),
            metadata=data.get("metadata", {}),
            protocol_metadata=data.get("protocol_metadata", {}),
            negotiated_by=negotiated_by,
            fallback_protocol=fallback_protocol,
            warning=warning,
        )

    async def health_check(self) -> bool:
        """
        Check if the Recursive Resolver service is reachable.
        Returns True if healthy, False otherwise.
        """
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                resp = await client.get(f"{self.resolver_url}/health")
            return resp.status_code == 200
        except Exception:
            return False
