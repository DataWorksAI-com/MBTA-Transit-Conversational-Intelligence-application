"""
Namespace discovery for the upgraded Recursive Resolver.

Uses POST requests to forward resolution through the TLD NS → (App NS + Auth NS chain).
The registry's POST /resolve endpoint handles the full forwarding internally,
so the resolver only needs to make a single POST call to the registry.

Also retains the legacy NamespaceDiscovery class for backward compat with the old GET-based flow.
"""
from typing import Dict

import httpx
from fastapi import HTTPException


# ── New POST-based resolution ─────────────────────────────────────────────────

NAMESPACE_SERVERS: Dict[str, Dict] = {
    "agents.local": {
        "url": "http://localhost:6900",
        "type": "local_registry",
    }
}


def find_namespace_server(namespace_id: str) -> str:
    """
    Return the base URL for a namespace server.

    Input:  "agents.local"
    Output: "http://localhost:6900"
    Raises: HTTPException(404) if namespace not configured.
    """
    entry = NAMESPACE_SERVERS.get(namespace_id)
    if not entry:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown namespace: {namespace_id!r}. "
                   f"Known: {list(NAMESPACE_SERVERS.keys())}",
        )
    return entry["url"]


async def query_namespace_server(
    ns_url: str,
    agent_path: str,
    context: dict,
    timeout: float = 10.0,
) -> dict:
    """
    POST to the namespace server's /resolve endpoint.

    The registry's /resolve endpoint chains TLD NS → App NS → Auth NS internally
    and returns the final Auth NS resolution response.

    Input:
      ns_url      "http://localhost:6900"
      agent_path  "mbta-transit-ci:alerts"
      context     {"location": {...}, "protocols": [...]}

    Output:
      {"endpoint": "http://localhost:8001", "protocol": "A2A", "ttl": 300, "metadata": {...}}

    Raises:
      HTTPException(404) — agent not found
      HTTPException(503) — namespace server unavailable
    """
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(
                f"{ns_url}/resolve",
                json={"agent_path": agent_path, "requester_context": context},
            )
    except httpx.TimeoutException:
        raise HTTPException(
            status_code=503,
            detail=f"Namespace server timed out: {ns_url}",
        )
    except Exception as e:
        raise HTTPException(
            status_code=503,
            detail=f"Namespace server unavailable: {ns_url} — {e}",
        )

    if resp.status_code == 404:
        raise HTTPException(status_code=404, detail=f"Agent not found: {agent_path}")
    if resp.status_code == 503:
        raise HTTPException(status_code=503, detail="Agent servers are all unhealthy")
    if resp.status_code != 200:
        raise HTTPException(
            status_code=resp.status_code,
            detail=f"Namespace server error: {resp.text[:200]}",
        )

    return resp.json()


# ── Legacy class (used by old resolver.py, kept for backward compat) ──────────

class NamespaceDiscovery:
    """Legacy GET-based 3-tier namespace query chain."""

    def __init__(self, tld_ns_url: str, timeout: float = 5.0):
        self.tld_ns_url = tld_ns_url
        self.timeout = timeout

    async def query_tld(self, urn: str) -> dict:
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as c:
                r = await c.get(self.tld_ns_url, params={"urn": urn})
        except Exception as e:
            raise ValueError(f"tld_timeout: {e}") from e

        if r.status_code == 400:
            raise ValueError("malformed_urn")
        if r.status_code == 404:
            raise ValueError("tld_unknown")
        r.raise_for_status()
        return r.json()

    async def query_app_ns(self, app_ns_url: str, urn: str) -> dict:
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as c:
                r = await c.get(app_ns_url, params={"urn": urn})
        except Exception as e:
            raise ValueError(f"app_ns_timeout: {e}") from e

        if r.status_code == 404:
            raise ValueError("namespace_unknown")
        r.raise_for_status()
        return r.json()

    async def query_auth_ns(self, auth_ns_base: str, urn: str) -> dict:
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as c:
                r = await c.get(f"{auth_ns_base}/resolve", params={"urn": urn})
        except Exception as e:
            raise ValueError(f"auth_ns_timeout: {e}") from e

        if r.status_code == 503:
            raise ValueError("agent_unreachable")
        if r.status_code == 404:
            raise ValueError("namespace_unknown")
        r.raise_for_status()
        return r.json()
