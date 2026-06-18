"""
ANS Resolver Client — wraps the Recursive Resolver API for use by the Exchange orchestrator.

Key design principles:
  - NEVER raises into the orchestrator. All exceptions are caught, logged as WARNING,
    and None is returned so the caller falls back to the static registry URL.
  - Uses the new ResolutionRequest / ResolutionResponse spec (v2.0).
  - MBTA_URNS is the single source of truth for agent_id → URN mapping.

For the prototype this points to localhost:8200.
In production it will point to the Recursive Resolver Nanode IP.
"""
import httpx
import logging
import os
from dataclasses import dataclass, field
from typing import Dict, Optional

logger = logging.getLogger(__name__)

# ── Configuration ─────────────────────────────────────────────────────────────

ANS_RESOLVER_URL = os.getenv("ANS_RESOLVER_URL", "http://localhost:8200")
ANS_RESOLVER_TIMEOUT = float(os.getenv("ANS_RESOLVER_TIMEOUT", "5.0"))

# Prototype URNs (agents.local TLD).
# In production, replace "agents.local" with "agents.dataworksai.com".
MBTA_URNS: Dict[str, str] = {
    "mbta-alerts":        "urn:agents.local:mbta-transit-ci:alerts",
    "mbta-planner":       "urn:agents.local:mbta-transit-ci:planner",
    "mbta-stopfinder":    "urn:agents.local:mbta-transit-ci:stopfinder",
    "mbta-route-planner": "urn:agents.local:mbta-transit-ci:planner",
    "mbta-stops":         "urn:agents.local:mbta-transit-ci:stopfinder",
}

# Fallback static endpoints if resolution fails
FALLBACK_ENDPOINTS: Dict[str, str] = {
    "alerts":     "http://localhost:8001",
    "planner":    "http://localhost:8002",
    "stopfinder": "http://localhost:8003",
}


def get_urn_for_agent(agent_id: str) -> Optional[str]:
    """Return the URN for a given agent_id, or None if not mapped."""
    return MBTA_URNS.get(agent_id)


# ── Data class ────────────────────────────────────────────────────────────────

@dataclass
class ResolvedAgent:
    urn: str
    endpoint_url: str    # e.g. "http://localhost:8001"
    agent_id: str        # e.g. "mbta-alerts"
    ttl: int             # seconds the caller may cache this
    cached: bool         # True if the resolver returned a cached result
    latency_ms: float    # resolver's reported resolution_time_ms
    protocol: str = "A2A"
    metadata: Dict = field(default_factory=dict)


# ── Client ────────────────────────────────────────────────────────────────────

class ResolverClient:
    """
    Async client for the ANS Recursive Resolver (v2.0 spec).

    Instantiated once in StateGraphOrchestrator.__init__ and reused across calls.
    """

    def __init__(
        self,
        resolver_url: str = ANS_RESOLVER_URL,
        timeout: float = ANS_RESOLVER_TIMEOUT,
    ):
        self.resolver_url = resolver_url
        self.timeout = timeout
        logger.info(f"ANS ResolverClient → {self.resolver_url}")

    async def resolve(self, urn: str, force_refresh: bool = False) -> Optional[ResolvedAgent]:
        """
        Resolve a URN to an endpoint URL using the v2.0 POST API.

        Returns ResolvedAgent on success, None on any failure.
        Never raises — safe to call without try/except.
        """
        return await self._resolve_v2(urn)

    async def _resolve_v2(self, urn: str) -> Optional[ResolvedAgent]:
        """Call POST /resolve with new ResolutionRequest spec."""
        payload = {
            "agent_name": urn,
            "requester_context": {
                "location": {"city": "Boston", "state": "MA", "country": "US"},
                "device": "server",
                "network": "datacenter",
                "protocols": ["A2A", "SLIM"],
                "security_level": "standard",
            },
            "cache_enabled": True,
        }
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as c:
                r = await c.post(f"{self.resolver_url}/resolve", json=payload)

            if r.status_code == 200:
                d = r.json()
                # Extract agent_id from URN label (last component)
                agent_id = urn.rsplit(":", 1)[-1]  # "alerts"
                return ResolvedAgent(
                    urn=urn,
                    endpoint_url=d["endpoint"],
                    agent_id=agent_id,
                    ttl=d.get("ttl", 60),
                    cached=d.get("cached", False),
                    latency_ms=d.get("resolution_time_ms", 0.0),
                    protocol=d.get("protocol", "A2A"),
                    metadata=d.get("metadata", {}),
                )

            logger.warning(
                f"ANS resolver returned HTTP {r.status_code} for {urn}: {r.text[:120]}"
            )

        except httpx.TimeoutException:
            logger.warning(f"ANS resolver timed out for {urn} (>{self.timeout}s)")
        except Exception as e:
            logger.warning(f"ANS resolver error for {urn}: {e}")

        return None

    async def resolve_agent(
        self,
        agent_name: str,
        requester_context: Optional[Dict] = None,
    ) -> Optional[ResolvedAgent]:
        """
        High-level method matching the Exchange Server prompt spec.
        Accepts agent_name (URN) and optional requester_context dict.
        Falls back gracefully to None on failure.
        """
        payload = {
            "agent_name": agent_name,
            "requester_context": requester_context or {
                "location": {"city": "Boston", "state": "MA", "country": "US"},
                "device": "server",
                "network": "datacenter",
                "protocols": ["A2A", "SLIM"],
                "security_level": "standard",
            },
            "cache_enabled": True,
        }
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as c:
                r = await c.post(f"{self.resolver_url}/resolve", json=payload)

            if r.status_code == 200:
                d = r.json()
                agent_id = agent_name.rsplit(":", 1)[-1]
                return ResolvedAgent(
                    urn=agent_name,
                    endpoint_url=d["endpoint"],
                    agent_id=agent_id,
                    ttl=d.get("ttl", 60),
                    cached=d.get("cached", False),
                    latency_ms=d.get("resolution_time_ms", 0.0),
                    protocol=d.get("protocol", "A2A"),
                    metadata=d.get("metadata", {}),
                )

            logger.warning(f"Resolver HTTP {r.status_code} for {agent_name}: {r.text[:120]}")

        except httpx.TimeoutException:
            logger.warning(f"Resolver timed out for {agent_name}")
        except Exception as e:
            logger.warning(f"Resolver error for {agent_name}: {e}")

        return None

    async def health_check(self) -> bool:
        """Returns True if the resolver is reachable and healthy."""
        try:
            async with httpx.AsyncClient(timeout=3.0) as c:
                r = await c.get(f"{self.resolver_url}/health")
            return r.status_code == 200
        except Exception:
            return False
