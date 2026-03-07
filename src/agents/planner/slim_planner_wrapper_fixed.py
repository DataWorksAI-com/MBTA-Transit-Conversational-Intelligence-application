"""
MBTA Route Planner Agent - v5.0 with Domain Context Awareness
Receives alerts domain analysis and plans routes accordingly
Version: 5.0 - Context-Aware Domain Expert
"""

import asyncio
import logging
import os
import sys
import json
import re
from typing import Optional, Dict, Any, List, Tuple
from uuid import uuid4

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

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

# Configuration
MBTA_API_KEY = os.getenv('MBTA_API_KEY', 'c845eff5ae504179bc9cfa69914059de')
MBTA_BASE_URL = "https://api-v3.mbta.com"
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')

openai_client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

if not MBTA_API_KEY:
    logger.warning("MBTA_API_KEY not found!")
if not OPENAI_API_KEY:
    logger.warning("OPENAI_API_KEY not found - LLM disabled!")


class PlannerExecutor(AgentExecutor):
    """
    Enhanced planner v5.0 with context awareness
    
    NEW in v5.0:
    - Extracts alerts context from incoming messages
    - Considers disruption severity when planning
    - Avoids routes marked as problematic
    - Provides reasoning about route choices
    """
    
    def __init__(self, openai_api_key: str, mbta_api_key: str):
        self.openai_client = OpenAI(api_key=openai_api_key) if openai_api_key else None
        self.mbta_api_key = mbta_api_key
        logger.info("? PlannerExecutor v5.0 initialized with context awareness")
    
    def extract_alerts_context(self, message: str) -> Dict[str, Any]:
        """
        Extract alerts context from incoming message.
        
        StateGraph passes context like:
        "ALERTS ANALYSIS CONTEXT:
         - Overall recommendation: take_alternative
         - Severity: major
         - AVOID these routes: Red Line"
        
        Returns:
            {
                "has_context": bool,
                "recommendation": str,
                "severity": str,
                "avoid_routes": List[str]
            }
        """
        context = {
            "has_context": False,
            "recommendation": "unknown",
            "severity": "unknown",
            "avoid_routes": []
        }
        
        if "ALERTS ANALYSIS CONTEXT" not in message and "ALERTS CONTEXT" not in message:
            return context
        
        context["has_context"] = True
        logger.info("?? Detected alerts context in message")
        
        # Extract recommendation
        rec_match = re.search(r"recommendation:\s*(\w+)", message, re.IGNORECASE)
        if rec_match:
            context["recommendation"] = rec_match.group(1).lower()
        
        # Extract severity
        sev_match = re.search(r"severity:\s*(\w+)", message, re.IGNORECASE)
        if sev_match:
            context["severity"] = sev_match.group(1).lower()
        
        # Extract routes to avoid
        avoid_match = re.search(r"AVOID.*?:\s*([^\n]+)", message, re.IGNORECASE)
        if avoid_match:
            avoid_text = avoid_match.group(1)
            # Parse route names
            for route in ["Red Line", "Orange Line", "Blue Line", "Green Line"]:
                if route in avoid_text:
                    context["avoid_routes"].append(route.split()[0])  # Extract "Red", "Orange", etc.
        
        logger.info(f"? Extracted context:")
        logger.info(f"  Recommendation: {context['recommendation']}")
        logger.info(f"  Severity: {context['severity']}")
        logger.info(f"  Avoid: {context['avoid_routes']}")
        
        return context
    
    def detect_multiple_routes_request(self, query: str) -> bool:
        """Detect if user wants multiple route options"""
        query_lower = query.lower()
        
        keywords = [
            "two route", "three route", "multiple route", "route option",
            "different route", "alternative", "give me options",
            "show me options", "compare routes", "ranked by",
            "several route", "provide two", "provide multiple"
        ]
        
        detected = any(kw in query_lower for kw in keywords)
        if detected:
            logger.info(f"? Multiple routes requested")
        return detected
    
    async def generate_multiple_routes_with_llm(
        self,
        origin: str,
        destination: str,
        avoid_routes: List[str] = None,
        num_options: int = 2
    ) -> str:
        """
        Generate multiple route options using LLM.
        
        NEW in v5.0: Considers routes to avoid based on alerts context.
        """
        if not self.openai_client:
            return f"LLM not available."
        
        try:
            # Build avoid instruction
            avoid_instruction = ""
            if avoid_routes:
                avoid_instruction = f"\nIMPORTANT: AVOID these routes due to service disruptions: {', '.join(avoid_routes)}"
                avoid_instruction += f"\nProvide alternative routes that don't use these lines."
            
            prompt = f"""You are a Boston MBTA transit expert. Generate {num_options} DIFFERENT route options from {origin} to {destination}.
{avoid_instruction}

MBTA System:
- Red Line: Alewife ? Ashmont/Braintree (via Park Street, South Station)
- Orange Line: Oak Grove ? Forest Hills (via North Station, Downtown Crossing, Back Bay)
- Blue Line: Wonderland ? Bowdoin (via Airport, Aquarium, Government Center)
- Green Line: B,C,D,E branches (all through Park Street, Kenmore)

Transfer Stations:
- Park Street: Red + Green
- Downtown Crossing: Red + Orange
- Government Center: Blue + Green
- North Station: Orange + Green
- State: Orange + Blue

For EACH route:
- Option number
- Lines used
- Transfers (if any)
- Stops count
- Estimated time
- Brief description

Make routes DIFFERENT (use different lines or transfers).

Format:

**Option 1:**
- Lines: Red Line
- Transfers: None
- Stops: 3
- Time: ~8 min
- From {origin}, take Red towards [direction] to {destination}

**Option 2:**
- Lines: Green + Red
- Transfers: at Park Street
- Stops: 5  
- Time: ~12 min
- From {origin}, take Green to Park, transfer to Red to {destination}

Be realistic."""
            
            logger.info(f"?? Generating {num_options} routes (avoid: {avoid_routes or 'none'})")
            
            response = self.openai_client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.7,
                max_tokens=600
            )
            
            routes_text = response.choices[0].message.content
            
            # Add context note if routes were avoided
            if avoid_routes:
                routes_text += f"\n\n?? Note: Alternative routes provided to avoid disruptions on {', '.join(avoid_routes)}."
            
            logger.info(f"? Generated routes")
            return routes_text
            
        except Exception as e:
            logger.error(f"Error: {e}")
            return f"Error generating routes: {e}"
    
    async def generate_single_route_with_llm(
        self,
        origin: str,
        destination: str,
        avoid_routes: List[str] = None
    ) -> str:
        """
        Generate single route using LLM.
        
        NEW in v5.0: Considers routes to avoid.
        """
        if not self.openai_client:
            return f"Route from {origin} to {destination}"
        
        try:
            avoid_instruction = ""
            if avoid_routes:
                avoid_instruction = f"\nIMPORTANT: Avoid {', '.join(avoid_routes)} due to service disruptions. Provide alternative route."
            
            prompt = f"""Provide clear Boston MBTA route from {origin} to {destination}.
{avoid_instruction}

Include:
- Lines to take
- Transfers (if needed)
- Stops count
- Estimated time

One natural sentence.

Example: "From Park Street, take Red towards Alewife to Harvard (3 stops, ~8 min)."
"""
            
            response = self.openai_client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=200
            )
            
            route_text = response.choices[0].message.content.strip()
            
            if avoid_routes:
                route_text += f" (Avoiding {', '.join(avoid_routes)} due to disruptions)"
            
            return route_text
            
        except Exception as e:
            logger.error(f"Error: {e}")
            return f"Route from {origin} to {destination}"
    
    async def extract_locations_with_llm(self, query: str) -> Tuple[Optional[str], Optional[str]]:
        """Extract origin and destination using LLM"""
        if not self.openai_client:
            return await self.extract_locations_basic(query)
        
        prompt = f"""Extract origin and destination from query.

Query: "{query}"

Return ONLY: origin|destination

If only destination: none|destination

Examples:
- "from park street to harvard" ? park street|harvard
- "to harvard" ? none|harvard

Response:"""

        try:
            response = self.openai_client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                temperature=0,
                max_tokens=50
            )
            
            result = response.choices[0].message.content.strip()
            
            if "|" in result:
                parts = result.split("|")
                origin = parts[0].strip() if parts[0].strip().lower() != "none" else None
                destination = parts[1].strip() if len(parts) > 1 and parts[1].strip().lower() != "none" else None
                
                logger.info(f"? LLM: origin='{origin}', dest='{destination}'")
                return origin, destination
            
            return await self.extract_locations_basic(query)
            
        except Exception as e:
            logger.error(f"LLM extraction failed: {e}")
            return await self.extract_locations_basic(query)
    
    async def extract_locations_basic(self, query: str) -> Tuple[Optional[str], Optional[str]]:
        """Basic parsing fallback"""
        query_lower = query.lower()
        origin = None
        destination = None
        
        if " from " in query_lower and " to " in query_lower:
            parts = query_lower.split(" from ")
            if len(parts) > 1:
                from_part = parts[1]
                to_parts = from_part.split(" to ")
                if len(to_parts) >= 2:
                    origin = to_parts[0].strip()
                    destination = to_parts[1].strip()
        
        elif " to " in query_lower:
            parts = query_lower.split(" to ")
            if len(parts) >= 2:
                destination = parts[1].strip()
        
        if origin:
            origin = origin.strip("?.,!").strip()
        if destination:
            destination = destination.strip("?.,!").strip()
        
        logger.info(f"? Basic: origin='{origin}', dest='{destination}'")
        return origin, destination
    
    async def find_stop_by_name(self, name: str) -> Optional[Dict[str, Any]]:
        """Find stop by name"""
        if not name:
            return None
        
        try:
            params = {
                "api_key": self.mbta_api_key,
                "page[limit]": 500,
                "filter[location_type]": "1"
            }
            
            async with httpx.AsyncClient() as client:
                response = await client.get(f"{MBTA_BASE_URL}/stops", params=params, timeout=10)
                response.raise_for_status()
            
            stops = response.json().get("data", [])
            name_lower = name.lower().strip()
            
            for stop in stops:
                stop_name = stop.get("attributes", {}).get("name", "").lower()
                if name_lower in stop_name:
                    attributes = stop.get("attributes", {})
                    result = {
                        "id": stop.get("id"),
                        "name": attributes.get("name"),
                        "latitude": attributes.get("latitude"),
                        "longitude": attributes.get("longitude")
                    }
                    logger.info(f"Found: {result['name']}")
                    return result
            
            logger.warning(f"No stop matching '{name}'")
            return None
        
        except Exception as e:
            logger.error(f"Error finding stop: {e}")
            return None
    
    async def get_routes_between_stops(self, origin_id: str, destination_id: str) -> List[Dict[str, Any]]:
        """Find routes serving both stops"""
        if not origin_id or not destination_id:
            return []
        
        try:
            params = {"api_key": self.mbta_api_key, "filter[stop]": origin_id}
            
            async with httpx.AsyncClient() as client:
                response = await client.get(f"{MBTA_BASE_URL}/routes", params=params, timeout=10)
                response.raise_for_status()
            
            origin_routes = response.json().get("data", [])
            origin_ids = {r.get("id") for r in origin_routes}
            
            params["filter[stop]"] = destination_id
            
            async with httpx.AsyncClient() as client:
                response = await client.get(f"{MBTA_BASE_URL}/routes", params=params, timeout=10)
                response.raise_for_status()
            
            dest_routes = response.json().get("data", [])
            dest_ids = {r.get("id") for r in dest_routes}
            
            common_ids = origin_ids.intersection(dest_ids)
            
            common_routes = []
            for route in origin_routes:
                if route.get("id") in common_ids:
                    attributes = route.get("attributes", {})
                    common_routes.append({
                        "id": route.get("id"),
                        "short_name": attributes.get("short_name", ""),
                        "long_name": attributes.get("long_name", "Unknown"),
                    })
            
            logger.info(f"Found {len(common_routes)} routes")
            return common_routes
        
        except Exception as e:
            logger.error(f"Error: {e}")
            return []
    
    async def plan_route_with_context(
        self,
        origin: str,
        destination: str,
        alerts_context: Dict[str, Any],
        wants_multiple: bool = False
    ) -> Dict[str, Any]:
        """
        Plan route considering alerts domain analysis context.
        
        NEW in v5.0: Uses alerts analysis to make better routing decisions.
        """
        try:
            logger.info(f"Planning: '{origin}' ? '{destination}'")
            if alerts_context.get("has_context"):
                logger.info(f"?? With context: recommendation={alerts_context['recommendation']}, avoid={alerts_context['avoid_routes']}")
            
            # Find stops
            origin_stop = await self.find_stop_by_name(origin)
            if not origin_stop:
                return {"ok": False, "text": f"Couldn't find '{origin}'."}
            
            dest_stop = await self.find_stop_by_name(destination)
            if not dest_stop:
                return {"ok": False, "text": f"Couldn't find '{destination}'."}
            
            logger.info(f"Stops: {origin_stop['name']} ? {dest_stop['name']}")
            
            # Get avoid routes from context
            avoid_routes = alerts_context.get("avoid_routes", []) if alerts_context.get("has_context") else []
            
            # ================================================================
            # ALWAYS CHECK API FIRST (Critical Fix!)
            # ================================================================
            logger.info(f"?? Checking MBTA API for direct routes...")
            api_routes = await self.get_routes_between_stops(origin_stop["id"], dest_stop["id"])
            
            if api_routes:
                logger.info(f"? Found {len(api_routes)} direct routes via API")
                
                # Check if direct route should be avoided
                direct_route_id = api_routes[0]["id"]
                
                # Extract route name (e.g., "Red" from route_id)
                route_name = direct_route_id.split("-")[0] if "-" in direct_route_id else direct_route_id
                
                should_avoid_direct = avoid_routes and route_name in avoid_routes
                
                if should_avoid_direct:
                    logger.info(f"?? Direct route {route_name} should be avoided - generating alternatives")
                    
                    # Generate alternative routes via LLM
                    routes_text = await self.generate_multiple_routes_with_llm(
                        origin_stop['name'],
                        dest_stop['name'],
                        avoid_routes=avoid_routes,
                        num_options=2
                    )
                    
                    if alerts_context.get("has_context"):
                        explanation = self.generate_context_explanation(alerts_context)
                        routes_text = explanation + "\n\n" + routes_text
                    
                    return {"ok": True, "text": routes_text, "avoided_direct": True}
                
                else:
                    # Direct route is fine - USE IT (don't hallucinate)
                    logger.info(f"? Using direct route: {api_routes[0]['long_name']}")
                    
                    route = api_routes[0]
                    
                    # Simple direct route response
                    if wants_multiple:
                        # User wants options - give direct + alternative
                        routes_text = await self.generate_multiple_routes_with_llm(
                            origin_stop['name'],
                            dest_stop['name'],
                            avoid_routes=None,  # Don't avoid, just show options
                            num_options=2
                        )
                        return {"ok": True, "text": routes_text}
                    else:
                        # Single direct route
                        text = f"Take the {route['long_name']} from {origin_stop['name']} to {dest_stop['name']}."
                        
                        # Add context note if there are delays on this route
                        if alerts_context.get("has_context"):
                            text += f"\n\nNote: {alerts_context.get('recommendation', 'monitor').replace('_', ' ').title()} due to current service conditions."
                        
                        return {"ok": True, "text": text}
            
            else:
                # No direct route found via API - use LLM for transfer suggestions
                logger.info(f"? No direct routes via API - using LLM for transfers")
                
                routes_text = await self.generate_multiple_routes_with_llm(
                    origin_stop['name'],
                    dest_stop['name'],
                    avoid_routes=avoid_routes,
                    num_options=2 if wants_multiple else 1
                )
                
                if alerts_context.get("has_context"):
                    explanation = self.generate_context_explanation(alerts_context)
                    routes_text = explanation + "\n\n" + routes_text
                
                return {"ok": True, "text": routes_text}
            
        except Exception as e:
            logger.error(f"Error: {e}", exc_info=True)
            return {"ok": False, "text": "Error planning route."}
    
    def generate_context_explanation(self, context: Dict[str, Any]) -> str:
        """Generate explanation of routing decision based on context"""
        
        if not context.get("has_context"):
            return ""
        
        explanation = "?? **Route Planning Considering Current Conditions:**\n"
        
        recommendation = context.get("recommendation", "unknown")
        severity = context.get("severity", "unknown")
        avoid = context.get("avoid_routes", [])
        
        if recommendation == "take_alternative":
            explanation += f"?? Major disruptions detected ({severity} severity)"
            if avoid:
                explanation += f" on {', '.join(avoid)}"
            explanation += ".\n"
            explanation += "Providing alternative routes to avoid delays.\n"
        
        elif recommendation == "monitor":
            explanation += f"?? Some disruptions detected ({severity} severity).\n"
            explanation += "Routes optimized considering current conditions.\n"
        
        elif recommendation == "wait":
            explanation += "? Delays are resolving. Standard routes should be available.\n"
        
        return explanation
    
    async def execute(self, context: RequestContext, event_queue: EventQueue):
        """
        Execute with context awareness.
        
        NEW in v5.0: Extracts and uses alerts context from StateGraph.
        """
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
            
            logger.info(f"?? Planner: '{message_text[:150]}'")
            
            # NEW: Extract alerts context from message
            alerts_context = self.extract_alerts_context(message_text)
            
            # Detect if multiple routes wanted
            wants_multiple = self.detect_multiple_routes_request(message_text)
            
            # Extract locations (clean message first if it has context markers)
            clean_message = message_text.split("ALERTS")[0].strip()  # Remove context section
            origin, destination = await self.extract_locations_with_llm(clean_message)
            
            logger.info(f"Locations: '{origin}' ? '{destination}'")
            
            # Validation
            if not destination:
                response_text = "Please specify destination."
                response_message = Message(
                    message_id=str(uuid4()),
                    parts=[TextPart(text=response_text)],
                    role="agent"
                )
                await event_queue.enqueue_event(response_message)
                return
            
            if not origin:
                response_text = f"Where are you starting from? Example: 'From Park Street to {destination}'"
                response_message = Message(
                    message_id=str(uuid4()),
                    parts=[TextPart(text=response_text)],
                    role="agent"
                )
                await event_queue.enqueue_event(response_message)
                return
            
            # Plan route WITH alerts context
            result = await self.plan_route_with_context(
                origin,
                destination,
                alerts_context,
                wants_multiple
            )
            
            response_text = result.get("text", "Could not plan route")
            
            if result.get("ok"):
                response_text += "\n\n? Route planning complete"
            
            # Send response
            response_message = Message(
                message_id=str(uuid4()),
                parts=[TextPart(text=response_text)],
                role="agent"
            )
            
            await event_queue.enqueue_event(response_message)
            logger.info("? Response sent")
            
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
    
    skills = [
        AgentSkill(
            id="context_aware_planning",
            name="Context-Aware Route Planning",
            description="Plans routes considering service alerts, disruptions, and recommendations from domain analysis",
            tags=["context", "intelligent", "adaptive"],
            examples=["Best route considering delays", "Route avoiding disruptions"]
        ),
        AgentSkill(
            id="multiple_routes",
            name="Multiple Route Options",
            description="Generate 2-3 different route alternatives",
            tags=["options", "alternatives"],
            examples=["Give me two routes", "Show options"]
        ),
        AgentSkill(
            id="disruption_aware",
            name="Disruption-Aware Routing",
            description="Automatically avoids routes with major service disruptions",
            tags=["smart", "avoid", "disruptions"],
            examples=["Route avoiding delays", "Alternative without Red Line"]
        ),
    ]
    
    agent_card = AgentCard(
        name="mbta-planner",
        description="Context-aware MBTA route planner that considers service alerts and provides alternatives based on current conditions",
        url="http://96.126.111.107:50052/",
        version="5.0.0",
        default_input_modes=["text"],
        default_output_modes=["text"],
        skills=skills,
        capabilities=AgentCapabilities(streaming=True)
    )
    
    executor = PlannerExecutor(openai_api_key, mbta_api_key)
    handler = DefaultRequestHandler(executor, task_store=InMemoryTaskStore())
    server = A2AStarletteApplication(agent_card=agent_card, http_handler=handler)
    app = server.build()
    
    logger.info("=" * 80)
    logger.info("?? MBTA Planner Agent v5.0 - Context-Aware Domain Expert")
    logger.info("=" * 80)
    logger.info("? Extracts alerts context from messages")
    logger.info("? Avoids disrupted routes automatically")
    logger.info("? Provides alternative routes when needed")
    logger.info("? Explains routing decisions based on context")
    logger.info("=" * 80)
    
    uvicorn.run(app, host="0.0.0.0", port=50052, log_level="info")


if __name__ == "__main__":
    main()

