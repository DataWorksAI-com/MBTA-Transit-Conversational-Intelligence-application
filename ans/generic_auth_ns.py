"""
Generic Authoritative Nameserver — handles ALL MBTA agents.

Runs on the agents server (96.126.111.107) on port 8300.
A single process replaces three separate per-agent auth NS files.

Configuration is entirely env-var driven — zero hardcoded IPs:
  AGENT_HOST  — IP or hostname of the agents server  (default: localhost)
  ANS_TLD     — URN top-level domain                 (default: agents.dataworksai.com)
  ANS_APP     — application namespace                (default: mbta-transit-ci)
  AUTH_NS_PORT— port this server listens on           (default: 8300)

POST /resolve  {"agent": "alerts", "requester_context": {...}}
GET  /health   — auth NS own health
GET  /agents   — list all registered agents + live health
"""

import asyncio
import os
import sys
import time as _time
from datetime import datetime, timezone

import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Any, Dict, Optional

# ── Resolve sibling imports from the ans/ package ─────────────────────────────
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from health_checker import check_agent_health
from server_selection import rank_servers, select_protocol, calculate_ttl

# ── Config from environment — NO hardcoded values ─────────────────────────────
HOST = os.getenv("AGENT_HOST", "localhost")
ANS_TLD = os.getenv("ANS_TLD", "agents.dataworksai.com")
ANS_APP = os.getenv("ANS_APP", "mbta-transit-ci")
AUTH_NS_PORT = int(os.getenv("AUTH_NS_PORT", "8300"))

_start_time = _time.time()

# ── SLIM port config — all from env vars, no hardcoded values ─────────────────
# The agents run as A2A SLIM wrappers (uvicorn ASGI) on these ports.
# Health check uses /.well-known/agent.json (A2A AgentCard endpoint, always 200
# when the agent is up) because the SLIM wrappers don't expose /health.
ALERTS_PORT     = int(os.getenv("ALERTS_SLIM_PORT",     "50051"))
PLANNER_PORT    = int(os.getenv("PLANNER_SLIM_PORT",    "50052"))
STOPFINDER_PORT = int(os.getenv("STOPFINDER_SLIM_PORT", "50053"))

# ── Agent registry — all built from env vars, no hardcoded values ─────────────
AGENTS: Dict[str, Dict] = {
    "alerts": {
        "server_id":        "alerts-primary",
        "http_endpoint":    f"http://{HOST}:{ALERTS_PORT}",
        "health_check_url": f"http://{HOST}:{ALERTS_PORT}/.well-known/agent.json",
        "protocols":        ["A2A", "SLIM"],
        "location":         {"latitude": 42.3601, "longitude": -71.0589},  # Boston
    },
    "planner": {
        "server_id":        "planner-primary",
        "http_endpoint":    f"http://{HOST}:{PLANNER_PORT}",
        "health_check_url": f"http://{HOST}:{PLANNER_PORT}/.well-known/agent.json",
        "protocols":        ["A2A", "SLIM"],
        "location":         {"latitude": 42.3601, "longitude": -71.0589},
    },
    "stopfinder": {
        "server_id":        "stopfinder-primary",
        "http_endpoint":    f"http://{HOST}:{STOPFINDER_PORT}",
        "health_check_url": f"http://{HOST}:{STOPFINDER_PORT}/.well-known/agent.json",
        "protocols":        ["A2A", "SLIM"],
        "location":         {"latitude": 42.3601, "longitude": -71.0589},
    },
}

# ── FastAPI app ───────────────────────────────────────────────────────────────
app = FastAPI(
    title="MBTA Generic Auth NS",
    description="Authoritative Nameserver for all MBTA agents — env-var driven",
    version="1.0.0",
)


# ── Request / Response models ─────────────────────────────────────────────────
class ResolveRequest(BaseModel):
    agent: str                              # e.g. "alerts"
    requester_context: Optional[Dict[str, Any]] = {}


class ResolveResponse(BaseModel):
    endpoint: str
    protocol: str
    ttl: int
    metadata: Dict[str, Any]


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.post("/resolve", response_model=ResolveResponse)
async def resolve(req: ResolveRequest):
    """
    Resolve an agent label to its live endpoint.

    Input:  {"agent": "alerts", "requester_context": {"protocols": ["A2A"]}}
    Output: {"endpoint": "http://96.126.111.107:8001", "protocol": "A2A",
             "ttl": 600, "metadata": {...}}
    """
    label = req.agent.lower().strip()
    agent_cfg = AGENTS.get(label)
    if not agent_cfg:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown agent: {label!r}. Known: {list(AGENTS.keys())}",
        )

    context = req.requester_context or {}

    # Build a servers list compatible with rank_servers()
    servers = [{**agent_cfg}]   # list of one; extend for multi-region deployments

    # Live health check
    health = await check_agent_health(agent_cfg["health_check_url"])

    if health["status"] == "unhealthy":
        raise HTTPException(
            status_code=503,
            detail=f"Agent {label!r} is currently unhealthy.",
        )

    health_map = {agent_cfg["server_id"]: health}
    ranked = rank_servers(servers, health_map, context)

    if not ranked:
        raise HTTPException(status_code=503, detail=f"No healthy servers for {label!r}")

    best_server, best_health = ranked[0]
    preferred_protocols = context.get("protocols", ["A2A"])
    protocol = select_protocol(best_server.get("protocols", ["A2A"]), preferred_protocols)
    ttl = calculate_ttl(best_health)

    urn = f"urn:{ANS_TLD}:{ANS_APP}:{label}"

    return ResolveResponse(
        endpoint=best_server["http_endpoint"],
        protocol=protocol,
        ttl=ttl,
        metadata={
            "agent": label,
            "urn": urn,
            "server_id": best_server["server_id"],
            "server_health": best_health["status"],
            "load_percent": best_health.get("load", 0.0),
            "response_time_ms": best_health.get("response_time_ms", 0.0),
            "resolved_at": datetime.now(timezone.utc).isoformat(),
        },
    )


@app.get("/health")
async def health():
    """Auth NS own health — also checks whether all agents are reachable."""
    checks = await asyncio.gather(
        *[check_agent_health(cfg["health_check_url"]) for cfg in AGENTS.values()],
        return_exceptions=True,
    )
    agent_statuses = {}
    for label, result in zip(AGENTS.keys(), checks):
        if isinstance(result, Exception):
            agent_statuses[label] = "error"
        else:
            agent_statuses[label] = result.get("status", "unknown")

    overall = "ok" if all(s != "unhealthy" for s in agent_statuses.values()) else "degraded"
    return {
        "ok": overall == "ok",
        "status": overall,
        "service": "mbta-generic-auth-ns",
        "version": "1.0.0",
        "agent_host": HOST,
        "tld": ANS_TLD,
        "app_namespace": ANS_APP,
        "agents_registered": list(AGENTS.keys()),
        "agent_health": agent_statuses,
        "uptime_seconds": round(_time.time() - _start_time, 1),
    }


@app.get("/agents")
async def list_agents():
    """List all configured agents with their live health status."""
    checks = await asyncio.gather(
        *[check_agent_health(cfg["health_check_url"]) for cfg in AGENTS.values()],
        return_exceptions=True,
    )
    result = {}
    for label, cfg, check in zip(AGENTS.keys(), AGENTS.values(), checks):
        health = check if not isinstance(check, Exception) else {"status": "error"}
        urn = f"urn:{ANS_TLD}:{ANS_APP}:{label}"
        result[label] = {
            "urn": urn,
            "endpoint": cfg["http_endpoint"],
            "protocols": cfg["protocols"],
            "health": health,
        }
    return result


# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print(f"Starting Generic Auth NS on :{AUTH_NS_PORT}")
    print(f"  AGENT_HOST = {HOST}")
    print(f"  ANS_TLD    = {ANS_TLD}")
    print(f"  ANS_APP    = {ANS_APP}")
    print(f"  Agents     = {list(AGENTS.keys())}")
    uvicorn.run(app, host="0.0.0.0", port=AUTH_NS_PORT, log_level="info")
