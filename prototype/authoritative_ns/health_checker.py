"""
Health checker for Authoritative Nameservers.
Performs live HTTP health checks on agent endpoints and classifies their status.
"""
import asyncio
import time
from datetime import datetime, timezone
from typing import Dict, List

import httpx


async def check_agent_health(health_url: str) -> Dict:
    """
    Perform a real-time health check on a single agent.

    Classification:
      healthy   — response_time < 100ms AND load < 75%
      degraded  — response_time < 500ms AND load < 90%
      unhealthy — timeout | error | load >= 90%

    Returns:
      {status, load, response_time_ms, last_check}
    """
    t0 = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            r = await client.get(health_url)
        response_time_ms = (time.monotonic() - t0) * 1000

        if r.status_code != 200:
            return {
                "status": "unhealthy",
                "load": 100.0,
                "response_time_ms": round(response_time_ms, 2),
                "last_check": datetime.now(timezone.utc).isoformat(),
            }

        data = r.json()
        load = float(data.get("load_percent", 50.0))

        if response_time_ms < 100 and load < 75:
            status = "healthy"
        elif response_time_ms < 500 and load < 90:
            status = "degraded"
        else:
            status = "unhealthy"

        return {
            "status": status,
            "load": round(load, 1),
            "response_time_ms": round(response_time_ms, 2),
            "last_check": datetime.now(timezone.utc).isoformat(),
        }

    except (httpx.TimeoutException, httpx.ConnectError, Exception):
        response_time_ms = (time.monotonic() - t0) * 1000
        return {
            "status": "unhealthy",
            "load": 100.0,
            "response_time_ms": round(response_time_ms, 2),
            "last_check": datetime.now(timezone.utc).isoformat(),
        }


async def check_all_servers_health(servers: List[Dict]) -> Dict[str, Dict]:
    """
    Check health of all servers in parallel using asyncio.gather.

    Returns: {server_id: health_dict}
    """
    tasks = [
        check_agent_health(server["health_check_url"])
        for server in servers
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    health_map = {}
    for server, result in zip(servers, results):
        if isinstance(result, Exception):
            health_map[server["server_id"]] = {
                "status": "unhealthy",
                "load": 100.0,
                "response_time_ms": 0.0,
                "last_check": datetime.now(timezone.utc).isoformat(),
            }
        else:
            health_map[server["server_id"]] = result

    return health_map
