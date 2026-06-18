"""
Authoritative Nameserver for the StopFinder agent.

Owns:  urn:agents.local:mbta-transit-ci:stopfinder
Port:  8302
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

app = FastAPI(title="stopfinder-auth-ns", version="2.0.0")

AGENT_DEPLOYMENT = {
    "agent_id": "stopfinder",
    "agent_name": "urn:agents.local:mbta-transit-ci:stopfinder",
    "servers": [
        {
            "server_id": "stopfinder-local",
            "location": {
                "datacenter": "local",
                "region": "us-east",
                "city": "Boston",
                "state": "MA",
                "country": "US",
                "latitude": 42.3601,
                "longitude": -71.0589,
            },
            "http_endpoint": "http://localhost:8003",
            "health_check_url": "http://localhost:8003/health",
            "protocols": ["A2A", "SLIM"],
            "capacity": {"max_concurrent": 100, "current_load": 20},
            "health": {"status": "unknown", "last_check": None},
        }
    ],
    "routing_policy": {"default": "least-loaded", "failover": True},
}


@app.get("/health")
def health():
    return {
        "ok": True,
        "service": "stopfinder-auth-ns",
        "port": 8302,
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
    servers = AGENT_DEPLOYMENT["servers"]
    context = req.requester_context.dict()

    health_map = await check_all_servers_health(servers)
    ranked = rank_servers(servers, health_map, context)

    if not ranked:
        raise HTTPException(status_code=503, detail="All stopfinder servers are currently unhealthy")

    best_server, best_health = ranked[0]
    preferred = context.get("protocols", ["A2A"])
    protocol = select_protocol(best_server["protocols"], preferred)
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
    uvicorn.run(app, host="0.0.0.0", port=8302, log_level="info")
