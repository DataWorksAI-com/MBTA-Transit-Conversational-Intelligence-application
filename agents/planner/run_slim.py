"""
run_slim.py — Planner agent SLIM transport entry point
=======================================================
Runs the Planner agent on the SLIM transport alongside the existing A2A server.

  mbta-planner      → uvicorn on :50052  (A2A SSE — existing, unchanged)
  mbta-slim-planner → this file          (SLIM transport — new)

Supervisor env vars required:
  SLIM_LABEL        = planner
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
logger = logging.getLogger("slim-planner")

from a2a.server.tasks import InMemoryTaskStore
from a2a.types import AgentCard, AgentCapabilities, AgentSkill

_AGENT_HOST = os.getenv("AGENT_HOST", "96.126.111.107")

AGENT_CARD = AgentCard(
    name="mbta-planner",
    description=(
        "MBTA Route Planner — context-aware routing with alerts integration, "
        "crowding-aware route ranking, and multiple alternative options."
    ),
    url=f"http://{_AGENT_HOST}:50052/",
    version="5.1.0",
    default_input_modes=["text"],
    default_output_modes=["text"],
    capabilities=AgentCapabilities(streaming=True),
    skills=[
        AgentSkill(
            id="context_aware_planning",
            name="Context-Aware Planning",
            description="Plans routes considering alerts context and service disruptions",
            tags=["context", "intelligent"],
            examples=["Route considering delays", "Avoid disrupted lines"],
        ),
        AgentSkill(
            id="crowding_aware_routing",
            name="Crowding-Aware Routing",
            description="Checks vehicle occupancy and ranks routes by comfort",
            tags=["crowding", "comfort"],
            examples=["Route avoiding crowds", "Least crowded option"],
        ),
        AgentSkill(
            id="multiple_routes",
            name="Multiple Route Options",
            description="Generate 2-3 different alternatives",
            tags=["options", "alternatives"],
            examples=["Give me two routes", "Show options"],
        ),
    ],
)


async def main():
    from slim_planner_wrapper_fixed import PlannerExecutor
    from agents.common.slim_runner import run_slim_server

    openai_key = os.getenv("OPENAI_API_KEY", "")
    mbta_key   = os.getenv("MBTA_API_KEY", "")

    executor   = PlannerExecutor(openai_api_key=openai_key, mbta_api_key=mbta_key)
    task_store = InMemoryTaskStore()

    logger.info("🗺️  Planner agent SLIM transport starting…")
    await run_slim_server(AGENT_CARD, executor, task_store)


if __name__ == "__main__":
    asyncio.run(main())
