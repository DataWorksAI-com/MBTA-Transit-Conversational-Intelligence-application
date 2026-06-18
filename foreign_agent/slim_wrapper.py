"""
MBTA Fare & Accessibility Agent — Foreign Node
Runs on a remote Linode (Frankfurt / Singapore / etc.)
Registers with the Boston registry, discovered via ANS.

Start: python slim_wrapper.py
"""

import asyncio
import logging
import os
import sys
from uuid import uuid4
from typing import Optional

import uvicorn
from a2a.server.apps import A2AStarletteApplication
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events.event_queue import EventQueue
from a2a.types import AgentCard, AgentSkill, AgentCapabilities, Message, TextPart, TaskState
import httpx

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("mbta-fares-agent")

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
REGISTRY_URL   = os.getenv("REGISTRY_URL",   "http://97.107.132.213:6900")
AGENT_HOST     = os.getenv("AGENT_HOST",     "0.0.0.0")      # public IP set at runtime
AGENT_PORT     = int(os.getenv("AGENT_PORT", "50054"))
ANS_TLD        = os.getenv("ANS_TLD",        "agents.dataworksai.com")
ANS_APP        = os.getenv("ANS_APP",        "mbta-transit-ci")
AGENT_ID       = os.getenv("AGENT_ID",       "mbta-fares")
AGENT_LABEL    = os.getenv("ANS_LABEL",      "fares")

# ── Embedded knowledge base (no API calls needed) ─────────────────────────────
FARES_KB = """
MBTA FARE INFORMATION (2024):
- Local Bus: $1.70 (CharlieCard) / $2.00 (cash)
- Subway (all lines): $2.40 (CharlieCard) / $2.40 (cash/ticket)
- Commuter Rail Zone 1A: $2.40 | Zone 1: $7.00 | Zone 2: $8.25 | ... Zone 10: $13.25
- Ferry: Inner Harbor $3.70, Outer Harbor $7.00
- Monthly Pass (subway): $90.00
- Monthly Pass (bus+subway): $90.00
- Senior/TAP/Youth: half price on subway and bus
- CharlieCard available at any MBTA station or retail locations
- Reduced fare: seniors 65+, people with disabilities, Medicare card holders

ACCESSIBILITY:
- All subway stations have accessible entrances (some still being upgraded)
- Blue Line: fully accessible
- Red/Orange/Green/Silver Line: mostly accessible, check mbta.com for exceptions
- Key stations: Park Street, Downtown Crossing, South Station, Back Bay — fully accessible
- Paratransit: THE RIDE service for those who cannot use fixed-route transit
- THE RIDE fares: $3.35 per trip for ADA-eligible riders
- All MBTA buses are low-floor, kneeling buses with ramp access
- Audio and visual announcements on all new vehicles

MBTA HISTORY & STATS:
- Founded: 1964 (successor to MTA, founded 1947)
- Oldest subway in America: Tremont Street Subway, opened 1897
- Daily ridership (pre-COVID): ~1.3 million trips
- Serves: 79 cities and towns in Greater Boston
- Fleet: ~400 subway cars, ~1,000 buses, ~500 commuter rail cars
- Track miles: 160+ miles of rail
"""


async def answer_with_llm(question: str) -> str:
    """Use OpenAI to answer fare/accessibility questions from the knowledge base."""
    if not OPENAI_API_KEY:
        # Fallback: simple keyword matching
        q = question.lower()
        if "fare" in q or "cost" in q or "price" in q or "pay" in q:
            return "Subway fare is $2.40 with CharlieCard. Bus is $1.70. Monthly pass is $90."
        if "access" in q or "wheelchair" in q or "disabled" in q or "ride" in q:
            return "All MBTA buses are wheelchair accessible. Most subway stations are accessible. THE RIDE paratransit serves ADA-eligible riders for $3.35/trip."
        if "history" in q or "old" in q or "found" in q:
            return "The MBTA was founded in 1964. The Tremont Street Subway (1897) is the oldest subway in America."
        return f"MBTA Fares Agent (Frankfurt): {FARES_KB[:300]}..."

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
                json={
                    "model": "gpt-4o-mini",
                    "messages": [
                        {"role": "system", "content":
                            f"You are the MBTA Fares & Accessibility Agent. "
                            f"Answer questions about MBTA fares, accessibility, and history. "
                            f"Be concise (2-3 sentences). Use this knowledge:\n\n{FARES_KB}"},
                        {"role": "user", "content": question}
                    ],
                    "temperature": 0.1,
                    "max_tokens": 200,
                }
            )
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        log.error(f"LLM call failed: {e}")
        return f"MBTA Fares Agent: Subway $2.40 with CharlieCard, bus $1.70. Monthly pass $90. All buses wheelchair accessible."


# ── A2A Agent Executor ─────────────────────────────────────────────────────────
class FaresAgentExecutor(AgentExecutor):
    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        # ... your existing logic ...
        question = ""
        if context.message and context.message.parts:
            for part in context.message.parts:
                inner = getattr(part, "root", part)
                text = getattr(inner, "text", None)
                if text:
                    question = text
                    break

        if not question:
            question = "What are the MBTA fares?"

        log.info(f"📨 Question: {question[:100]}")
        answer = await answer_with_llm(question)
        log.info(f"✅ Answer: {answer[:100]}")

        response_message = Message(
            message_id=str(uuid4()),
            parts=[TextPart(text=answer)],
            role="agent",
        )
        await event_queue.enqueue_event(response_message)

    # ADD THIS METHOD BELOW:
    async def cancel(self, context: RequestContext) -> None:
        """Handle task cancellation if requested by the registry."""
        log.info(f"🛑 Cancellation requested for task: {context.task_id}")


# ── Registry registration ──────────────────────────────────────────────────────
async def register_with_registry(public_ip: str, port: int):
    """Register this agent with the Boston registry so ANS can discover it."""
    agent_url  = f"http://{public_ip}:{port}"
    api_url    = f"http://{public_ip}:{port}"
    urn        = f"urn:{ANS_TLD}:{ANS_APP}:{AGENT_LABEL}"

    payload = {
        "agent_id":   AGENT_ID,
        "agent_url":  agent_url,
        "api_url":    api_url,
        "agent_name": urn,
        "description": "MBTA Fare & Accessibility specialist — remote node (Frankfurt/Singapore)",
        "capabilities": ["fares", "accessibility", "mbta-history", "pricing"],
        "status": "active",
    }

    for attempt in range(5):
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.post(f"{REGISTRY_URL}/register", json=payload)
                if r.status_code in (200, 201):
                    log.info(f"✅ Registered with registry: {REGISTRY_URL}")
                    log.info(f"   URN: {urn}")
                    log.info(f"   Endpoint: {agent_url}")
                    return
                else:
                    log.warning(f"Registry returned {r.status_code}: {r.text[:100]}")
        except Exception as e:
            log.warning(f"Registration attempt {attempt+1} failed: {e}")
        await asyncio.sleep(5)
    log.error("❌ Could not register with registry after 5 attempts")


# ── Auth NS update (tell agents server about this new agent) ──────────────────
async def update_auth_ns(public_ip: str, port: int):
    """Optionally ping Auth NS to add this agent dynamically."""
    auth_ns_url = os.getenv("AUTH_NS_URL", "http://96.126.111.107:8300")
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.post(f"{auth_ns_url}/register_agent", json={
                "label":     AGENT_LABEL,
                "endpoint":  f"http://{public_ip}:{port}",
                "health_url": f"http://{public_ip}:{port}/.well-known/agent.json",
                "protocols": ["A2A"],
            })
            if r.status_code == 200:
                log.info(f"✅ Auth NS updated with new agent")
    except Exception as e:
        log.info(f"ℹ️  Auth NS update skipped (will use registry fallback): {e}")


# ── App setup ─────────────────────────────────────────────────────────────────
def build_app(public_ip: str, port: int):
    agent_card = AgentCard(
        name="MBTA Fares & Accessibility Agent",
        description="Answers MBTA fare, accessibility, and history questions. Remote node.",
        url=f"http://{public_ip}:{port}/",
        version="1.0.0",
        capabilities=AgentCapabilities(streaming=True),
        skills=[
            AgentSkill(
                id="fares",
                name="MBTA Fares",
                description="Current MBTA fares for subway, bus, commuter rail, and ferry",
                tags=["mbta", "fares", "pricing"],
            ),
            AgentSkill(
                id="accessibility",
                name="Accessibility",
                description="Wheelchair access, THE RIDE paratransit, and station accessibility info",
                tags=["mbta", "accessibility", "wheelchair"],
            ),
        ],
        defaultInputModes=["text"],
        defaultOutputModes=["text"],
    )
    task_store = InMemoryTaskStore()
    executor   = FaresAgentExecutor()
    handler    = DefaultRequestHandler(executor, task_store)
    return A2AStarletteApplication(agent_card=agent_card, http_handler=handler).build()


async def main():
    # Determine public IP (from env or auto-detect)
    public_ip = os.getenv("PUBLIC_IP", "")
    if not public_ip or public_ip == "0.0.0.0":
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                r = await client.get("https://api.ipify.org?format=json")
                public_ip = r.json()["ip"]
                log.info(f"🌍 Detected public IP: {public_ip}")
        except Exception:
            public_ip = "localhost"

    log.info(f"🚀 Starting MBTA Fares Agent on {AGENT_HOST}:{AGENT_PORT}")
    log.info(f"   Public endpoint: http://{public_ip}:{AGENT_PORT}")

    # Register in background (don't block startup)
    asyncio.create_task(register_with_registry(public_ip, AGENT_PORT))
    asyncio.create_task(update_auth_ns(public_ip, AGENT_PORT))

    app = build_app(public_ip, AGENT_PORT)

    config = uvicorn.Config(
        app,
        host=AGENT_HOST,
        port=AGENT_PORT,
        log_level="info",
    )
    server = uvicorn.Server(config)
    await server.serve()


if __name__ == "__main__":
    asyncio.run(main())
