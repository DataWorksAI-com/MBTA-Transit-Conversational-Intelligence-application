"""
run_slim.py — Alerts agent SLIM transport entry point
======================================================
Runs the Alerts agent on the SLIM transport (port 46357 via SLIM controller).
Started as a SEPARATE supervisor process alongside the existing A2A server.

  mbta-alerts      → uvicorn on :50051  (A2A SSE — existing, unchanged)
  mbta-slim-alerts → this file          (SLIM transport — new)

Both share the same AlertsExecutor logic; only the transport differs.

Supervisor env vars required:
  SLIM_LABEL        = alerts
  SLIM_ENDPOINT     = http://96.126.111.107:46357
  SLIM_SHARED_SECRET= <same 64-char secret on all servers>
  MBTA_API_KEY, OPENAI_API_KEY
"""

import asyncio
import logging
import os
import sys

from dotenv import load_dotenv
load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("slim-alerts")

# ── agent card (mirrors slim_alerts_wrapper_fixed.py) ────────────────────────
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import AgentCard, AgentCapabilities, AgentSkill

_AGENT_HOST = os.getenv("AGENT_HOST", "96.126.111.107")

AGENT_CARD = AgentCard(
    name="mbta-alerts",
    description=(
        "MBTA Alerts Agent — real-time crowding, historical delay patterns "
        "(41,970 incidents), active incident analysis, service alerts."
    ),
    url=f"http://{_AGENT_HOST}:50051/",
    version="7.0.0",
    default_input_modes=["text"],
    default_output_modes=["text"],
    capabilities=AgentCapabilities(streaming=True),
    skills=[
        AgentSkill(
            id="crowding_estimation",
            name="Real-Time Crowding Estimation",
            description="Vehicle occupancy sensors with next train predictions",
            tags=["crowding", "real-time"],
            examples=["How crowded is Red Line?", "Crowding at Park Street?"],
        ),
        AgentSkill(
            id="historical_patterns",
            name="Historical Delay Analysis",
            description="41,970 incidents (2020-2023) for delay predictions",
            tags=["historical", "patterns"],
            examples=["How long do medical delays take?", "Typical signal delay?"],
        ),
        AgentSkill(
            id="active_incident_analysis",
            name="Active Incident Analysis",
            description="Analyzes current incidents with historical context",
            tags=["analysis", "prediction"],
            examples=["Should I wait?", "How serious is this delay?"],
        ),
        AgentSkill(
            id="service_alerts",
            name="Current Service Alerts",
            description="Real-time disruptions and delays",
            tags=["alerts", "current"],
            examples=["Red Line delays?", "Current issues?"],
        ),
    ],
)


async def main():
    from slim_alerts_wrapper_fixed import AlertsExecutor
    from agents.common.slim_runner import run_slim_server

    mbta_key   = os.getenv("MBTA_API_KEY", "")
    openai_key = os.getenv("OPENAI_API_KEY", "")

    executor   = AlertsExecutor(mbta_api_key=mbta_key, openai_api_key=openai_key)
    task_store = InMemoryTaskStore()

    logger.info("🚦 Alerts agent SLIM transport starting…")
    await run_slim_server(AGENT_CARD, executor, task_store)


if __name__ == "__main__":
    asyncio.run(main())
