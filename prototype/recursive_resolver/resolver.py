"""
ANS Recursive Resolver — main FastAPI application (v2.0).

Orchestrates the full resolution chain:
  Parse URN → Find Namespace Server → POST to Registry (chains to Auth NS) → Cache → Return

Features:
  - POST /resolve with ResolutionRequest / ResolutionResponse spec
  - Async TTL cache keyed on agent_name + location + protocols
  - Cache stats and clear endpoints
  - Precise resolution_time_ms measurement

Port: 8200

Run:
  python -m uvicorn recursive_resolver.resolver:app --host 0.0.0.0 --port 8200
  OR (from prototype/ directory):
  python resolver.py
"""
import os
import time

import uvicorn
import yaml
from fastapi import FastAPI, HTTPException

from .models import ResolutionRequest, ResolutionResponse
from .urn_parser import parse_urn
from .cache import ResolutionCache
from .namespace_discovery import find_namespace_server, query_namespace_server, NAMESPACE_SERVERS

app = FastAPI(
    title="ans-recursive-resolver",
    version="2.0.0",
    description="Recursive resolver for the Agent Name Service (ANS). "
                "Resolves agent URNs to live, health-verified endpoint URLs.",
)

cache = ResolutionCache()
_config: dict = {}


@app.on_event("startup")
async def startup():
    global _config
    config_path = os.path.join(os.path.dirname(__file__), "config.yaml")
    with open(config_path) as f:
        _config = yaml.safe_load(f)

    # Patch namespace server map from config if provided
    for ns_id, ns_info in _config.get("namespaces", {}).items():
        NAMESPACE_SERVERS[ns_id] = ns_info

    print(f"✅ Recursive Resolver v2.0 started on port {_config.get('resolver', {}).get('port', 8200)}")
    print(f"   Configured namespaces: {list(NAMESPACE_SERVERS.keys())}")


# ── Health ────────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    stats = await cache.get_stats()
    return {
        "ok": True,
        "service": "ans-recursive-resolver",
        "version": "2.0.0",
        "port": 8200,
        "cache": stats,
        "namespaces": list(NAMESPACE_SERVERS.keys()),
    }


# ── Main resolution endpoint ──────────────────────────────────────────────────

@app.post("/resolve", response_model=ResolutionResponse)
async def resolve(req: ResolutionRequest) -> ResolutionResponse:
    """
    Resolve an agent URN to its live endpoint.

    Steps:
      1. Parse URN → extract namespace_id and agent_path
      2. If cache_enabled: check cache → return cached response (cached=True)
      3. Find namespace server URL from config
      4. POST agent_path + context to namespace server
         (Registry chains: TLD NS → App NS → Auth NS internally)
      5. Cache the result with its TTL
      6. Return ResolutionResponse with timing

    Error codes:
      400 — malformed URN
      404 — unknown namespace or agent
      503 — all agent servers unhealthy / namespace server unavailable
    """
    t0 = time.monotonic()

    # Step 1: parse URN
    try:
        parsed = parse_urn(req.agent_name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # namespace_id = "agents.local", agent_path = "mbta-transit-ci:alerts"
    namespace_id = parsed.tld
    agent_path = f"{parsed.app_namespace}:{parsed.label}"

    context = req.requester_context.dict()

    # Step 2: cache lookup
    if req.cache_enabled:
        cached_data = await cache.get(req.agent_name, req.requester_context)
        if cached_data:
            return ResolutionResponse(
                endpoint=cached_data["endpoint"],
                protocol=cached_data["protocol"],
                ttl=cached_data["ttl"],
                metadata=cached_data["metadata"],
                cached=True,
                resolution_time_ms=round((time.monotonic() - t0) * 1000, 2),
            )

    # Step 3: find namespace server
    ns_url = find_namespace_server(namespace_id)

    # Step 4: query namespace server (single POST, chains internally)
    result = await query_namespace_server(
        ns_url=ns_url,
        agent_path=agent_path,
        context=context,
        timeout=_config.get("timeouts", {}).get("ns_query_s", 10.0),
    )

    resolution_time_ms = round((time.monotonic() - t0) * 1000, 2)

    # Build response data
    response_data = {
        "agent_name": req.agent_name,
        "endpoint": result["endpoint"],
        "protocol": result.get("protocol", "A2A"),
        "ttl": result.get("ttl", 60),
        "metadata": result.get("metadata", {}),
    }

    # Step 5: cache result
    if req.cache_enabled:
        await cache.set(
            req.agent_name,
            req.requester_context,
            response_data,
            ttl=result.get("ttl", 60),
        )

    # Step 6: return
    return ResolutionResponse(
        endpoint=response_data["endpoint"],
        protocol=response_data["protocol"],
        ttl=response_data["ttl"],
        metadata=response_data["metadata"],
        cached=False,
        resolution_time_ms=resolution_time_ms,
    )


# ── Cache management ──────────────────────────────────────────────────────────

@app.get("/cache/stats")
async def cache_stats():
    """Return cache hit/miss/eviction statistics."""
    return await cache.get_stats()


@app.post("/cache/clear")
async def clear_cache():
    """Clear all cached resolutions."""
    await cache.clear()
    return {"cleared": True}


# ── Namespace info ────────────────────────────────────────────────────────────

@app.get("/namespaces")
async def list_namespaces():
    """List all configured namespace servers."""
    return {
        "namespaces": {
            ns_id: {"url": info.get("url"), "type": info.get("type")}
            for ns_id, info in NAMESPACE_SERVERS.items()
        }
    }


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8200, log_level="info")
