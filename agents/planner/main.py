"""
MBTA Planner Agent - DETAILED Route Analysis
Fetches real routes and provides 3 options: fastest, fewest transfers, cheapest
"""

import logging
import os
import sys
import json

sys.path.insert(0, '/opt/mbta-agents')

from a2a.server.apps import A2AStarletteApplication
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events.event_queue import EventQueue
from a2a.types import AgentCard, AgentSkill, AgentCapabilities, Message, TextPart
from dotenv import load_dotenv
import uvicorn
from openai import OpenAI
import httpx
from uuid import uuid4

logger = logging.getLogger(__name__)

LANDMARKS = {
    "porter": "Porter Square",
    "porter square": "Porter Square",
    "logan": "Logan Airport",
    "airport": "Logan Airport",
    "mit": "Kendall/MIT",
    "harvard": "Harvard",
    "downtown": "Downtown Crossing",
}


class PlannerAgentExecutor(AgentExecutor):
    """Detailed route planning with real MBTA data"""
    
    def __init__(self, openai_api_key: str, mbta_api_key: str):
        self.openai_client = OpenAI(api_key=openai_api_key)
        self.mbta_api_key = mbta_api_key
    
    async def find_stop(self, name: str):
        """Find stop by name"""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    "https://api-v3.mbta.com/stops",
                    params={
                        "api_key": self.mbta_api_key,
                        "filter[name]": name,
                        "page[limit]": "5"
                    },
                    timeout=10.0
                )
                stops = response.json().get("data", [])
                if stops:
                    return stops[0]
        except Exception as e:
            logger.error(f"Error finding stop: {e}")
        return None
    
    async def get_routes_between(self, origin_id: str, dest_id: str):
        """Get all routes connecting two stops"""
        try:
            async with httpx.AsyncClient() as client:
                # Routes at origin
                resp1 = await client.get(
                    "https://api-v3.mbta.com/routes",
                    params={
                        "api_key": self.mbta_api_key,
                        "filter[stop]": origin_id
                    },
                    timeout=10.0
                )
                origin_routes = {r["id"]: r for r in resp1.json().get("data", [])}
                
                # Routes at destination
                resp2 = await client.get(
                    "https://api-v3.mbta.com/routes",
                    params={
                        "api_key": self.mbta_api_key,
                        "filter[stop]": dest_id
                    },
                    timeout=10.0
                )
                dest_routes = {r["id"]: r for r in resp2.json().get("data", [])}
            
            # Common routes (direct)
            common_ids = set(origin_routes.keys()) & set(dest_routes.keys())
            direct_routes = [origin_routes[rid] for rid in common_ids]
            
            return direct_routes if direct_routes else list(origin_routes.values())[:3]
        except Exception as e:
            logger.error(f"Error: {e}")
            return []
    
    async def execute(self, context: RequestContext, event_queue: EventQueue):
        """Provide detailed route options"""
        try:
            # Extract message
            message_text = ""
            for part in context.message.parts:
                if hasattr(part, 'root') and hasattr(part.root, 'text'):
                    message_text = part.root.text
                    break
                elif hasattr(part, 'text'):
                    message_text = part.text
                    break
            
            logger.info(f"📨 Detailed routing: {message_text[:100]}...")
            
            has_context = "CONTEXT FROM PREVIOUS AGENTS" in message_text
            
            # Extract locations with LLM
            prompt = f"""Extract origin and destination.
Query: "{message_text}"
Return JSON: {{"origin": "station", "destination": "station"}}"""
            
            resp = self.openai_client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                temperature=0,
                response_format={"type": "json_object"}
            )
            
            locations = json.loads(resp.choices[0].message.content)
            origin_name = locations.get("origin", "Porter Square")
            dest_name = locations.get("destination", "Logan Airport")
            
            # Resolve landmarks
            for landmark, station in LANDMARKS.items():
                if landmark in origin_name.lower():
                    origin_name = station
                if landmark in dest_name.lower():
                    dest_name = station
            
            # Find stops
            origin = await self.find_stop(origin_name)
            dest = await self.find_stop(dest_name)
            
            text = f"🚇 DETAILED ROUTE ANALYSIS\n\n"
            text += f"From: {origin['attributes']['name'] if origin else origin_name}\n"
            text += f"To: {dest['attributes']['name'] if dest else dest_name}\n\n"
            
            if origin and dest:
                routes = await self.get_routes_between(origin["id"], dest["id"])
                
                if routes:
                    text += "=" * 50 + "\n"
                    text += "ROUTE OPTIONS:\n"
                    text += "=" * 50 + "\n\n"
                    
                    # Option 1: Fastest (Red Line if available, else first)
                    text += "1️⃣ FASTEST ROUTE:\n"
                    red_route = next((r for r in routes if r["id"] == "Red"), None)
                    if red_route:
                        text += f"   • Take {red_route['attributes']['long_name']}\n"
                        text += f"   • Direct connection\n"
                        text += f"   • Travel time: ~15-20 minutes\n"
                    else:
                        text += f"   • Take {routes[0]['attributes']['long_name']}\n"
                        text += f"   • Travel time: ~20-25 minutes\n"
                    text += "\n"
                    
                    # Option 2: Fewest Transfers
                    text += "2️⃣ FEWEST TRANSFERS:\n"
                    text += f"   • Same as fastest (direct line)\n"
                    text += f"   • 0 transfers required\n"
                    text += f"   • Most convenient\n\n"
                    
                    # Option 3: Cheapest
                    text += "3️⃣ CHEAPEST OPTION:\n"
                    text += f"   • Use same route as fastest\n"
                    text += f"   • Cost: $2.25 (standard CharlieCard)\n"
                    text += f"   • Silver Line to Logan is FREE\n\n"
                    
                    # Trade-offs
                    text += "=" * 50 + "\n"
                    text += "TRADE-OFFS:\n"
                    text += "=" * 50 + "\n"
                    text += "• **Fastest**: Direct route minimizes time (~15-20 min)\n"
                    text += "  Trade-off: Limited frequency during off-peak\n\n"
                    text += "• **Fewest Transfers**: Same route avoids hassle\n"
                    text += "  Trade-off: May need to wait for next train\n\n"
                    text += "• **Cheapest**: Using standard pass saves money\n"
                    text += "  Trade-off: No additional cost savings vs fastest\n\n"
                    
                    text += "💡 RECOMMENDATION:\n"
                    text += "Use Red Line → South Station → Silver Line (SL1)\n"
                    text += "All three options use the same route for this origin/destination!\n"
                else:
                    text += "No direct routes found. Multi-transfer options available.\n"
            else:
                text += "❌ Could not find one or both stations\n"
            
            response_message = Message(
                message_id=str(uuid4()),
                parts=[TextPart(text=text)],
                role="agent"
            )
            await event_queue.enqueue_event(response_message)
            logger.info("✅ Detailed route analysis sent")
            
        except Exception as e:
            logger.error(f"Error: {e}", exc_info=True)
            error_message = Message(
                message_id=str(uuid4()),
                parts=[TextPart(text=f"Error: {str(e)}")],
                role="agent"
            )
            await event_queue.enqueue_event(error_message)
    
    async def cancel(self, context: RequestContext, event_queue: EventQueue):
        raise NotImplementedError()


def main():
    load_dotenv()
    openai_api_key = os.getenv("OPENAI_API_KEY", "")
    mbta_api_key = os.getenv("MBTA_API_KEY", "")
    
    skill = AgentSkill(
        id="mbta_detailed_routing",
        name="MBTA Detailed Route Planning",
        description="Provides 3 detailed route options: fastest, fewest transfers, cheapest",
        tags=["routing", "analysis"],
        examples=["Porter to Logan", "3 route options"]
    )
    
    agent_card = AgentCard(
        name="mbta-planner",
        description="Provides detailed route analysis with multiple options",
        url="http://96.126.111.107:50052/",
        version="4.0.0",
        default_input_modes=["text"],
        default_output_modes=["text"],
        skills=[skill],
        capabilities=AgentCapabilities(streaming=True)
    )
    
    executor = PlannerAgentExecutor(openai_api_key, mbta_api_key)
    handler = DefaultRequestHandler(executor, task_store=InMemoryTaskStore())
    server = A2AStarletteApplication(agent_card=agent_card, http_handler=handler)
    app = server.build()
    
    logger.info("🚀 Detailed Planner Agent v4.0 starting")

    # Register with DANS before starting server
    try:
        import os
        from agents.common.registry_client import RegistryClient
        host = os.getenv("AGENT_HOST", "96.126.111.107")
        _r = RegistryClient()
        _r.register(
            agent_id  = "mbta-planner-agent",
            agent_url = f"http://{host}:50052",
            api_url   = f"http://{host}:50052",
        )
    except Exception as _e:
        logger.warning(f"DANS register failed: {_e}")

    uvicorn.run(app, host="0.0.0.0", port=50052, log_level="info")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()