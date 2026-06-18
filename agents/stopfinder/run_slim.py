"""
run_slim.py — StopFinder agent SLIM transport entry point
=========================================================
Runs the StopFinder agent on the SLIM transport alongside the existing A2A server.

  mbta-stopfinder      → uvicorn on :50053  (A2A SSE — existing, unchanged)
  mbta-slim-stopfinder → this file          (SLIM transport — new)

Supervisor env vars required:
  SLIM_LABEL        = stopfinder
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
logger = logging.getLogger("slim-stopfinder")

from a2a.server.tasks import InMemoryTaskStore
from a2a.types import AgentCard, AgentCapabilities, AgentSkill

_AGENT_HOST = os.getenv("AGENT_HOST", "96.126.111.107")

AGENT_CARD = AgentCard(
    name="mbta-stopfinder",
    description=(
        "MBTA Stop Finder — 50+ Boston landmark database, LLM fallback "
        "for unknown locations, StateGraph-compatible query format."
    ),
    url=f"http://{_AGENT_HOST}:50053/",
    version="4.1.0",
    default_input_modes=["text"],
    default_output_modes=["text"],
    capabilities=AgentCapabilities(streaming=True),
    skills=[
        AgentSkill(
            id="landmark_db",
            name="Landmark Database",
            description="50+ Boston landmarks",
            tags=["landmarks", "database"],
            examples=["Fenway Park", "Northeastern"],
        ),
        AgentSkill(
            id="query_extract",
            name="Query Extraction",
            description="Handles StateGraph format",
            tags=["parsing", "stategraph"],
            examples=["Find station: X format"],
        ),
        AgentSkill(
            id="llm_fallback",
            name="LLM Fallback",
            description="AI landmark detection",
            tags=["llm", "landmarks"],
            examples=["Unknown landmarks"],
        ),
    ],
)


async def main():
    from slim_stopfinder_wrapper_fixed import StopFinderExecutor
    from agents.common.slim_runner import run_slim_server

    mbta_key   = os.getenv("MBTA_API_KEY", "")
    openai_key = os.getenv("OPENAI_API_KEY", "")

    executor   = StopFinderExecutor(mbta_api_key=mbta_key, openai_api_key=openai_key)
    task_store = InMemoryTaskStore()

    logger.info("📍 StopFinder agent SLIM transport starting…")
    await run_slim_server(AGENT_CARD, executor, task_store)


if __name__ == "__main__":
    asyncio.run(main())
