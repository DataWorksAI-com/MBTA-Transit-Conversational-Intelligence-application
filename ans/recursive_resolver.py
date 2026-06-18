"""
Production Recursive Resolver — MBTA Agent Name Service

Runs on the Exchange server (50.116.53.133) on port 8200.
Receives a URN, looks up the namespace server, forwards to the registry's
POST /resolve endpoint, caches the result, and returns endpoint + metadata.

Configuration (all from environment — zero hardcoded values):
  REGISTRY_URL      — e.g. http://97.107.132.213:6900   (already in .env)
  ANS_TLD           — e.g. agents.dataworksai.com
  ANS_APP           — e.g. mbta-transit-ci
  RESOLVER_PORT     — port this server listens on (default: 8200)

POST /resolve        — resolve a URN to an agent endpoint
GET  /health         — resolver health + cache summary
GET  /namespaces     — list known namespace → registry mappings
GET  /cache/stats    — cache hit/miss/TTL statistics
POST /cache/clear    — flush entire cache
"""

import os
import sys
import time as _time
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import httpx
import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

# ── Resolve sibling imports ────────────────────────────────────────────────────
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cache import ResolutionCache
from urn_parser import parse_urn, ParsedURN

# ── Config from environment ────────────────────────────────────────────────────
REGISTRY_URL = os.getenv("REGISTRY_URL", "http://localhost:6900")
ANS_TLD = os.getenv("ANS_TLD", "agents.dataworksai.com")
ANS_APP = os.getenv("ANS_APP", "mbta-transit-ci")
RESOLVER_PORT = int(os.getenv("RESOLVER_PORT", "8200"))
RESOLVER_TIMEOUT = float(os.getenv("RESOLVER_TIMEOUT", "10.0"))

_start_time = _time.time()

# ── Namespace → Registry URL mapping ─────────────────────────────────────────
# Maps TLD (from URN) → registry base URL
# All values come from env vars; add more entries here if needed.
NAMESPACE_REGISTRY_MAP: Dict[str, str] = {
    ANS_TLD: REGISTRY_URL,
    "agents.local": os.getenv("LOCAL_REGISTRY_URL", REGISTRY_URL),  # dev override
}

# ── FastAPI app ────────────────────────────────────────────────────────────────
app = FastAPI(
    title="MBTA Recursive Resolver",
    description="Production ANS recursive resolver — resolves URNs to live agent endpoints",
    version="2.0.0",
)

cache = ResolutionCache()


# ── Request / Response models ─────────────────────────────────────────────────

class ResolutionRequest(BaseModel):
    agent_name: str                                 # URN e.g. urn:agents.dataworksai.com:mbta-transit-ci:alerts
    requester_context: Optional[Dict[str, Any]] = {}
    cache_enabled: bool = True


class ResolutionResponse(BaseModel):
    endpoint: str
    protocol: str
    ttl: int
    metadata: Dict[str, Any]
    cached: bool
    resolution_time_ms: float


# ── URN → registry lookup ─────────────────────────────────────────────────────

def _registry_url_for(tld: str) -> str:
    """Return the registry URL for a given TLD namespace."""
    url = NAMESPACE_REGISTRY_MAP.get(tld)
    if not url:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown TLD namespace: {tld!r}. Known: {list(NAMESPACE_REGISTRY_MAP.keys())}",
        )
    return url


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.post("/resolve", response_model=ResolutionResponse)
async def resolve(req: ResolutionRequest):
    """
    Resolve a URN to a live agent endpoint.

    Steps:
      1. Parse the URN → (tld, app_namespace, label)
      2. Check cache (skip if cache_enabled=False)
      3. POST {registry_url}/resolve with {agent_path, requester_context}
      4. Cache the result under the agent URN + context key
      5. Return endpoint, protocol, ttl, metadata, cached, resolution_time_ms
    """
    t0 = _time.monotonic()

    # Parse URN
    try:
        parsed: ParsedURN = parse_urn(req.agent_name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    # Cache check
    context = req.requester_context or {}
    if req.cache_enabled:
        cached_data = await cache.get(req.agent_name, context)
        if cached_data is not None:
            elapsed = (_time.monotonic() - t0) * 1000
            return ResolutionResponse(
                endpoint=cached_data["endpoint"],
                protocol=cached_data["protocol"],
                ttl=cached_data["ttl"],
                metadata=cached_data["metadata"],
                cached=True,
                resolution_time_ms=round(elapsed, 2),
            )

    # Forward to registry's TLD NS (POST /resolve)
    registry_url = _registry_url_for(parsed.tld)
    agent_path = f"{parsed.app_namespace}:{parsed.label}"

    try:
        async with httpx.AsyncClient(timeout=RESOLVER_TIMEOUT) as client:
            resp = await client.post(
                f"{registry_url}/resolve",
                json={"agent_path": agent_path, "requester_context": context},
            )
    except httpx.TimeoutException:
        raise HTTPException(status_code=503, detail=f"Registry timed out: {registry_url}")
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Registry unreachable: {registry_url} — {exc}")

    if resp.status_code == 404:
        raise HTTPException(status_code=404, detail=f"Agent not found: {req.agent_name}")
    if resp.status_code == 503:
        raise HTTPException(status_code=503, detail="Agent servers are all unhealthy")
    if resp.status_code != 200:
        raise HTTPException(
            status_code=resp.status_code,
            detail=f"Registry error: {resp.text[:200]}",
        )

    data = resp.json()
    elapsed = (_time.monotonic() - t0) * 1000

    result = {
        "endpoint": data["endpoint"],
        "protocol": data.get("protocol", "A2A"),
        "ttl":      data.get("ttl", 300),
        "metadata": data.get("metadata", {}),
    }

    # Cache the result
    if req.cache_enabled:
        await cache.set(req.agent_name, context, result, result["ttl"])

    return ResolutionResponse(
        endpoint=result["endpoint"],
        protocol=result["protocol"],
        ttl=result["ttl"],
        metadata=result["metadata"],
        cached=False,
        resolution_time_ms=round(elapsed, 2),
    )


@app.get("/health")
async def health():
    stats = await cache.get_stats()
    return {
        "ok": True,
        "service": "mbta-recursive-resolver",
        "version": "2.0.0",
        "registry_url": REGISTRY_URL,
        "tld": ANS_TLD,
        "app_namespace": ANS_APP,
        "uptime_seconds": round(_time.time() - _start_time, 1),
        "cache": stats,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/namespaces")
async def namespaces():
    """Return all known namespace → registry URL mappings."""
    return {
        "namespaces": {
            tld: {"registry_url": url}
            for tld, url in NAMESPACE_REGISTRY_MAP.items()
        }
    }


@app.get("/cache/stats")
async def cache_stats():
    return await cache.get_stats()


@app.post("/cache/clear")
async def cache_clear():
    await cache.clear()
    return {"cleared": True, "timestamp": datetime.now(timezone.utc).isoformat()}


# ── Entry point ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print(f"Starting MBTA Recursive Resolver on :{RESOLVER_PORT}")
    print(f"  REGISTRY_URL = {REGISTRY_URL}")
    print(f"  ANS_TLD      = {ANS_TLD}")
    print(f"  ANS_APP      = {ANS_APP}")
    uvicorn.run(app, host="0.0.0.0", port=RESOLVER_PORT, log_level="info")
