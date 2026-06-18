"""
MBTA Fare & Accessibility Agent — multi-region node.

Identical capability everywhere; deployed to multiple regions (US-East "NJ"
node and EU-Central "Frankfurt" node). ANS/geo ranking prefers the node with
lower latency from the requesting exchange server.

All wiring (registry URL, region, public IP) and secrets (OPENAI_API_KEY) come
from environment variables set by supervisor — nothing is hardcoded here.

Start: python slim_wrapper.py
"""
import asyncio
import logging
import os
from uuid import uuid4

import uvicorn
from a2a.server.apps import A2AStarletteApplication
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events.event_queue import EventQueue
from a2a.types import AgentCard, AgentSkill, AgentCapabilities, Message, TextPart
import httpx

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("mbta-fares-agent")

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
REGISTRY_URL   = os.getenv("REGISTRY_URL",   "")
PUBLIC_IP      = os.getenv("PUBLIC_IP",      "0.0.0.0")
AGENT_HOST     = os.getenv("AGENT_HOST",     "0.0.0.0")
AGENT_PORT     = int(os.getenv("AGENT_PORT", "50054"))
ANS_TLD        = os.getenv("ANS_TLD",        "agents.dataworksai.com")
ANS_APP        = os.getenv("ANS_APP",        "mbta-transit-ci")
AGENT_ID       = os.getenv("AGENT_ID",       "mbta-fares")
AGENT_LABEL    = os.getenv("ANS_LABEL",      "fares")
AUTH_NS_URL    = os.getenv("AUTH_NS_URL",    "")
AGENT_REGION       = os.getenv("AGENT_REGION",       "us-east")
AGENT_REGION_LABEL = os.getenv("AGENT_REGION_LABEL", "Boston, MA")
AGENT_FLAG         = os.getenv("AGENT_FLAG",         "\U0001f1fa\U0001f1f8")
AGENT_DESCRIPTION  = os.getenv(
    "AGENT_DESCRIPTION",
    "MBTA Fare & Accessibility specialist — regional node",
)

FARES_KB = """
MBTA FARE INFORMATION (2024):
- Local Bus: $1.70 (CharlieCard) / $2.00 (cash)
- Subway (all lines): $2.40 (CharlieCard) / $2.40 (cash/ticket)
- Commuter Rail Zone 1A: $2.40 | Zone 1: $7.00 | Zone 2: $8.25 | Zone 3: $9.75 | Zone 4: $10.50 | Zone 5: $11.50 | Zone 6: $12.25 | Zone 7: $12.75 | Zone 8: $13.25 | Zone 9: $13.25 | Zone 10: $13.25
- Ferry: Inner Harbor $3.70, Outer Harbor $7.00
- Monthly Pass (subway): $90.00
- Monthly Pass (bus+subway): $90.00
- Senior/TAP/Youth: half price on subway and bus
- CharlieCard available at any MBTA station or retail locations
- Reduced fare: seniors 65+, people with disabilities, Medicare card holders

ACCESSIBILITY:
- All 111+ MBTA subway stations have accessibility features
- Wheelchair accessible: all Red, Orange, Blue, Green (most) Line stations
- THE RIDE paratransit: $3.35 per trip for ADA-eligible riders
- All MBTA buses are wheelchair accessible with low floors and ramps
- Audio announcements and visual displays on all vehicles
- Service animals always permitted on all MBTA vehicles

MBTA HISTORY & STATS:
- Founded: 1964 (successor to MTA, founded 1947)
- Oldest subway in America: Tremont Street Subway, opened 1897
- Daily ridership (pre-COVID): ~1.3 million trips
- Serves: 79 cities and towns in Greater Boston
"""

SYSTEM_PROMPT = f"""You are an MBTA Fare & Accessibility specialist.
Answer questions about fares, passes, accessibility, and MBTA history.
Use this knowledge base:
{FARES_KB}
Be concise, accurate, and helpful."""


async def answer_with_llm(question: str) -> str:
    if not OPENAI_API_KEY:
        q = question.lower()
        if "subway" in q or "charliecard" in q:
            return "Subway fare is $2.40 with CharlieCard or cash. Monthly pass is $90."
        if "bus" in q:
            return "Local bus is $1.70 with CharlieCard, $2.00 cash."
        if "commuter rail" in q or "zone" in q:
            return "Commuter Rail fares range from $2.40 (Zone 1A) to $13.25 (Zone 10). Monthly passes available."
        if "ferry" in q:
            return "Ferry: Inner Harbor $3.70, Outer Harbor $7.00."
        if "monthly" in q or "pass" in q:
            return "Monthly pass: $90 for subway and bus. Commuter Rail passes vary by zone."
        if "accessibility" in q or "wheelchair" in q:
            return "All MBTA buses are wheelchair accessible. Most subway stations are accessible. THE RIDE paratransit: $3.35/trip."
        if "history" in q or "old" in q or "found" in q:
            return "The MBTA was founded in 1964. The Tremont Street Subway (1897) is the oldest subway in America."
        return "MBTA fares: Subway $2.40, Bus $1.70 (CharlieCard), Monthly pass $90. All buses wheelchair accessible."
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
                json={"model": "gpt-4o-mini", "max_tokens": 300, "temperature": 0.1,
                      "messages": [{"role": "system", "content": SYSTEM_PROMPT},
                                   {"role": "user",   "content": question}]},
            )
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        log.error(f"LLM call failed: {e}")
        return "MBTA Fares Agent: Subway $2.40 with CharlieCard, bus $1.70. Monthly pass $90."


class FaresAgentExecutor(AgentExecutor):
    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
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
        log.info(f"Question: {question[:100]}")
        answer = await answer_with_llm(question)
        log.info(f"Answer: {answer[:100]}")
        response_message = Message(
            message_id=str(uuid4()),
            parts=[TextPart(text=answer)],
            role="agent",
        )
        await event_queue.enqueue_event(response_message)

    async def cancel(self, context: RequestContext) -> None:
        log.info("Cancellation requested")


async def register_with_registry(public_ip: str, port: int):
    if not REGISTRY_URL:
        log.warning("REGISTRY_URL not set — skipping registry registration")
        return
    agent_url = f"http://{public_ip}:{port}"
    urn = f"urn:{ANS_TLD}:{ANS_APP}:{AGENT_LABEL}"
    payload = {
        "agent_id": AGENT_ID,
        "agent_url": agent_url,
        "api_url": agent_url,
        "agent_name": urn,
        "description": AGENT_DESCRIPTION,
        "capabilities": ["fares", "accessibility", "mbta-history", "pricing"],
        "status": "active",
    }
    for attempt in range(5):
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.post(f"{REGISTRY_URL}/register", json=payload)
                if r.status_code in (200, 201):
                    log.info(f"Registered with registry. URN: {urn}")
                    return
                log.warning(f"Registry returned {r.status_code}: {r.text[:100]}")
        except Exception as e:
            log.warning(f"Registry attempt {attempt+1} failed: {e}")
        await asyncio.sleep(5)
    log.error("Could not register with registry after 5 attempts")


async def update_auth_ns(public_ip: str, port: int):
    if not AUTH_NS_URL:
        log.info("AUTH_NS_URL not set — skipping auth-ns update (registry fallback)")
        return
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.post(f"{AUTH_NS_URL}/register_agent", json={
                "label":        AGENT_LABEL,
                "endpoint":     f"http://{public_ip}:{port}",
                "agent_id":     AGENT_ID,
                "region":       AGENT_REGION,
                "region_label": AGENT_REGION_LABEL,
                "flag":         AGENT_FLAG,
            })
            log.info(f"Auth NS: {r.status_code} {r.text[:80]}")
    except Exception as e:
        log.info(f"Auth NS update skipped: {e}")


def build_app(public_ip: str, port: int):
    agent_card = AgentCard(
        name="MBTA Fares & Accessibility Agent",
        description="Answers MBTA fare, accessibility, and history questions.",
        url=f"http://{public_ip}:{port}/",
        version="1.0.0",
        capabilities=AgentCapabilities(streaming=True),
        skills=[
            AgentSkill(id="fares", name="MBTA Fares",
                       description="Current MBTA fares for subway, bus, commuter rail, and ferry",
                       tags=["mbta", "fares", "pricing"]),
            AgentSkill(id="accessibility", name="Accessibility",
                       description="Wheelchair access, THE RIDE paratransit, and station accessibility info",
                       tags=["mbta", "accessibility", "wheelchair"]),
        ],
        defaultInputModes=["text"],
        defaultOutputModes=["text"],
    )
    handler = DefaultRequestHandler(
        agent_executor=FaresAgentExecutor(),
        task_store=InMemoryTaskStore(),
    )
    return A2AStarletteApplication(agent_card=agent_card, http_handler=handler).build()


async def main():
    public_ip = PUBLIC_IP
    if not public_ip or public_ip == "0.0.0.0":
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                r = await client.get("https://api.ipify.org?format=json")
                public_ip = r.json()["ip"]
                log.info(f"Detected public IP: {public_ip}")
        except Exception:
            public_ip = "localhost"

    log.info(f"Starting MBTA Fares Agent ({AGENT_ID}) on {AGENT_HOST}:{AGENT_PORT}")
    log.info(f"   Public endpoint: http://{public_ip}:{AGENT_PORT}")

    asyncio.create_task(register_with_registry(public_ip, AGENT_PORT))
    asyncio.create_task(update_auth_ns(public_ip, AGENT_PORT))

    app = build_app(public_ip, AGENT_PORT)
    config = uvicorn.Config(app, host=AGENT_HOST, port=AGENT_PORT, log_level="info")
    server = uvicorn.Server(config)
    await server.serve()


if __name__ == "__main__":
    asyncio.run(main())
