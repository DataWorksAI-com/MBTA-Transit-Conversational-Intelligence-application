"""
Authoritative Nameserver for the Alerts agent.

Owns:  urn:agents.local:mbta-transit-ci:alerts
Port:  8300

Performs live health checks on all registered alert servers,
selects the best one based on health / geography / load,
and returns a resolution response with dynamic TTL.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime, timezone

import uvicorn
from fastapi import FastAPI, HTTPException

from authoritative_ns.models import AuthResolutionRequest, AuthResolutionResponse
from authoritative_ns.health_checker import check_all_servers_health
from authoritative_ns.server_selection import rank_servers, select_protocol, calculate_ttl

app = FastAPI(title="alerts-auth-ns", version="2.0.0")

# ── Deployment configuration ──────────────────────────────────────────────────

AGENT_DEPLOYMENT = {
    "agent_id": "alerts",
    "agent_name": "urn:agents.local:mbta-transit-ci:alerts",
    "servers": [
        {
            "server_id": "alerts-local",
            "location": {
                "datacenter": "local",
                "region": "us-east",
                "city": "Boston",
                "state": "MA",
                "country": "US",
                "latitude": 42.3601,
                "longitude": -71.0589,
            },
            "http_endpoint": "http://localhost:8001",
            "health_check_url": "http://localhost:8001/health",
            "protocols": ["A2A", "SLIM"],
            "capacity": {"max_concurrent": 100, "current_load": 20},
            "health": {"status": "unknown", "last_check": None},
        }
    ],
    "routing_policy": {"default": "least-loaded", "failover": True},
}


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {
        "ok": True,
        "service": "alerts-auth-ns",
        "port": 8300,
        "agent": AGENT_DEPLOYMENT["agent_name"],
    }


@app.get("/deployment")
def get_deployment():
    return AGENT_DEPLOYMENT


@app.get("/servers")
async def list_servers():
    servers = AGENT_DEPLOYMENT["servers"]
    health_map = await check_all_servers_health(servers)
    return {
        "agent_id": AGENT_DEPLOYMENT["agent_id"],
        "servers": [
            {**s, "health": health_map.get(s["server_id"], {"status": "unknown"})}
            for s in servers
        ],
    }


@app.post("/resolve", response_model=AuthResolutionResponse)
async def resolve(req: AuthResolutionRequest) -> AuthResolutionResponse:
    """
    Select best server for the alerts agent and return its endpoint.

    Process:
      1. Health-check all servers in parallel
      2. Rank by: health → protocol → geography → load
      3. Select best available server
      4. Calculate TTL based on health/load
      5. Return resolution response
    """
    servers = AGENT_DEPLOYMENT["servers"]
    context = req.requester_context.dict()

    # Step 1: parallel health checks
    health_map = await check_all_servers_health(servers)

    # Step 2: rank servers
    ranked = rank_servers(servers, health_map, context)

    if not ranked:
        raise HTTPException(
            status_code=503,
            detail="All alert servers are currently unhealthy",
        )

    # Step 3: pick best server
    best_server, best_health = ranked[0]

    # Step 4: select protocol
    preferred = context.get("protocols", ["A2A"])
    protocol = select_protocol(best_server["protocols"], preferred)

    # Step 5: calculate TTL
    ttl = calculate_ttl(best_health)

    return AuthResolutionResponse(
        endpoint=best_server["http_endpoint"],
        protocol=protocol,
        ttl=ttl,
        metadata={
            "server_id": best_server["server_id"],
            "server_location": best_server["location"].get("city", "unknown"),
            "server_load": best_health.get("load", 0),
            "server_health": best_health["status"],
            "health_verified_at": best_health.get("last_check", datetime.now(timezone.utc).isoformat()),
            "response_time_ms": best_health.get("response_time_ms", 0),
        },
    )


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8300, log_level="info")
