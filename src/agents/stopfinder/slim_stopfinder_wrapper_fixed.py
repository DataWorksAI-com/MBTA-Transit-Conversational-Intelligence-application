"""
MBTA Stop Finder Agent - FIXED LLM Prompt
Stops hallucinating station names as landmarks
"""

import asyncio
import logging
import os
import sys
import string
import json
from typing import Optional, Dict, Any, List
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
import httpx

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

# Configuration
MBTA_API_KEY = os.getenv('MBTA_API_KEY', 'c845eff5ae504179bc9cfa69914059de')
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY', '')
MBTA_BASE_URL = "https://api-v3.mbta.com"

if not MBTA_API_KEY:
    logger.warning("MBTA_API_KEY not found!")
if not OPENAI_API_KEY:
    logger.warning("OPENAI_API_KEY not found - LLM disabled")


class StopFinderExecutor(AgentExecutor):
    """StopFinder with FIXED LLM landmark detection"""
    
    def __init__(self, mbta_api_key: str, openai_api_key: str = ""):
        self.mbta_api_key = mbta_api_key
        self.openai_api_key = openai_api_key
        self.llm_enabled = bool(openai_api_key)
    
    async def detect_landmark_with_llm(self, query: str) -> Dict[str, Any]:
        """
        FIXED: Better LLM prompt that doesn't confuse stations with landmarks
        """
        if not self.llm_enabled:
            return {"has_landmark": False}
        
        try:
            # IMPROVED PROMPT: Use landmark name directly, don't guess geography
            prompt = f"""Analyze this Boston transit query:

Query: "{query}"

Task: Determine if this is a LANDMARK or an MBTA STATION NAME.

RULES:
1. If query mentions an MBTA station name ? respond has_landmark=false
2. If query mentions a landmark/building/place ? respond has_landmark=true

CRITICAL FOR search_query:
- Use the landmark's actual NAME or main keyword
- DO NOT try to guess nearby stations or neighborhoods
- Just use the landmark name itself for searching

If STATION NAME:
{{
    "has_landmark": false
}}

If LANDMARK:
{{
    "has_landmark": true,
    "landmark_name": "proper name",
    "landmark_type": "park|museum|hospital|university|building|stadium|other",
    "search_query": "the landmark's name or main keyword",
    "confidence": 0.0-1.0
}}

Examples:
- "South Station" ? {{"has_landmark": false}}
- "Fenway Park" ? {{"has_landmark": true, "landmark_name": "Fenway Park", "landmark_type": "stadium", "search_query": "fenway"}}
- "Museum of Fine Arts" ? {{"has_landmark": true, "landmark_name": "Museum of Fine Arts", "landmark_type": "museum", "search_query": "museum of fine arts"}}
- "Boston University" ? {{"has_landmark": true, "landmark_name": "Boston University", "landmark_type": "university", "search_query": "boston university"}}
- "that big hospital in Longwood" ? {{"has_landmark": true, "landmark_name": "Boston Children's Hospital", "landmark_type": "hospital", "search_query": "longwood"}}
- "Prudential Center" ? {{"has_landmark": true, "landmark_name": "Prudential Center", "landmark_type": "building", "search_query": "prudential"}}
- "Boston Common" ? {{"has_landmark": true, "landmark_name": "Boston Common", "landmark_type": "park", "search_query": "park street"}}

Respond ONLY with JSON.
"""
            
            logger.info(f"?? LLM landmark detection: '{query}'")
            
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    "https://api.openai.com/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.openai_api_key}",
                        "Content-Type": "application/json"
                    },
                    json={
                        "model": "gpt-4o-mini",
                        "messages": [{"role": "user", "content": prompt}],
                        "temperature": 0.1,
                        "max_tokens": 200
                    },
                    timeout=10
                )
                response.raise_for_status()
            
            data = response.json()
            content = data["choices"][0]["message"]["content"]
            
            # LOG THE RAW RESPONSE
            logger.info(f"?? LLM raw response: '{content[:100]}'")
            
            # STRIP MARKDOWN CODE FENCES
            content = content.strip()
            if content.startswith("```json"):
                content = content[7:]  # Remove ```json
            if content.startswith("```"):
                content = content[3:]  # Remove ```
            if content.endswith("```"):
                content = content[:-3]  # Remove trailing ```
            content = content.strip()
            
            result = json.loads(content)
            
            logger.info(f"? LLM result: {result}")
            return result
            
        except json.JSONDecodeError as e:
            logger.error(f"? LLM JSON parse error: {e}")
            if 'content' in locals():
                logger.error(f"   Raw content was: '{content}'")
            return {"has_landmark": False}
        except KeyError as e:
            logger.error(f"? LLM response format error: {e}")
            if 'data' in locals():
                logger.error(f"   Response data: {data}")
            return {"has_landmark": False}
        except Exception as e:
            logger.error(f"? LLM error: {e}")
            return {"has_landmark": False}
    
    def extract_route_from_query(self, query: str) -> Optional[str]:
        """Extract route/line name"""
        query_lower = query.lower()
        
        route_mapping = {
            "red line": "Red", "red": "Red",
            "orange line": "Orange", "orange": "Orange",
            "blue line": "Blue", "blue": "Blue",
            "green line": "Green-B", "green": "Green-B",
            "green-b": "Green-B", "green b": "Green-B",
            "green-c": "Green-C", "green c": "Green-C",
            "green-d": "Green-D", "green d": "Green-D",
            "green-e": "Green-E", "green e": "Green-E",
            "mattapan": "Mattapan", "silver line": "741", "silver": "741",
        }
        
        for keyword, route_id in route_mapping.items():
            if keyword in query_lower:
                logger.info(f"Detected route: {route_id}")
                return route_id
        
        return None
    
    def extract_search_terms(self, query: str) -> set:
        """Extract search terms"""
        query_clean = query.translate(str.maketrans('', '', string.punctuation))
        
        common_words = {
            'find', 'the', 'nearest', 'station', 'to', 'near', 'search', 'for',
            'show', 'me', 'where', 'is', 'stops', 'on', 'in', 'at', 'list',
            'how', 'many', 'are', 'there', 'what', 'can', 'get', 'have',
            'been', 'have', 'has', 'do', 'does', 'by', 'from',
            'all', 'line', 'lines', 'station', 'stations', 'stop', 'that', 'big'
        }
        
        query_words = set(query_clean.lower().split()) - common_words
        query_words = {w for w in query_words if len(w) >= 3}
        return query_words
    
    async def find_stops(self, query: Optional[str] = None, route: Optional[str] = None) -> Dict[str, Any]:
        """Find MBTA stops"""
        try:
            logger.info(f"Finding stops - query: '{query}', route: '{route}'")
            
            params = {
                "api_key": self.mbta_api_key,
                "page[limit]": 500
            }
            
            if route:
                params["filter[route]"] = route
            else:
                params["filter[location_type]"] = "1"
            
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{MBTA_BASE_URL}/stops",
                    params=params,
                    timeout=10
                )
                response.raise_for_status()
            
            data = response.json()
            all_stops = data.get("data", [])
            
            logger.info(f"Fetched {len(all_stops)} stops")
            
            if query:
                query_lower = query.lower().strip()
                filtered_stops = []
                for stop in all_stops:
                    stop_name = stop.get("attributes", {}).get("name", "").lower()
                    if query_lower in stop_name:
                        filtered_stops.append(stop)
                
                stops = filtered_stops
                logger.info(f"Found {len(stops)} matching '{query}'")
            else:
                stops = all_stops
            
            if len(stops) == 0:
                return {
                    "ok": True,
                    "count": 0,
                    "stops": [],
                    "text": f"Sorry, I couldn't find any stops matching '{query}'."
                }
            
            processed_stops = []
            for stop in stops[:50]:
                attributes = stop.get("attributes", {})
                processed_stops.append({
                    "id": stop.get("id"),
                    "name": attributes.get("name", "Unknown"),
                    "latitude": attributes.get("latitude"),
                    "longitude": attributes.get("longitude"),
                    "wheelchair_accessible": attributes.get("wheelchair_boarding") == 1,
                    "municipality": attributes.get("municipality"),
                    "address": attributes.get("address"),
                })
            
            # Format response
            if route:
                text = f"?? The {route} Line has {len(stops)} stop(s):\n\n"
                for i, stop in enumerate(processed_stops[:20]):
                    wheelchair = " ?" if stop.get("wheelchair_accessible") else ""
                    text += f"{i+1}. {stop['name']}{wheelchair}\n"
                if len(stops) > 20:
                    text += f"\n... and {len(stops) - 20} more stops"
            
            elif query:
                if len(stops) == 1:
                    stop = processed_stops[0]
                    text = f"?? Found: {stop['name']}"
                    if stop.get('municipality'):
                        text += f" in {stop['municipality']}"
                    if stop.get('address'):
                        text += f"\n?? {stop['address']}"
                    if stop.get('wheelchair_accessible'):
                        text += "\n? Wheelchair accessible"
                else:
                    text = f"?? Found {len(stops)} stop(s) matching '{query}':\n\n"
                    for i, stop in enumerate(processed_stops[:15]):
                        municipality = stop.get("municipality", "")
                        wheelchair = " ?" if stop.get("wheelchair_accessible") else ""
                        stop_line = f"{i+1}. {stop['name']}"
                        if municipality:
                            stop_line += f" ({municipality})"
                        stop_line += wheelchair
                        text += stop_line + "\n"
                    if len(stops) > 15:
                        text += f"\n... and {len(stops) - 15} more"
            else:
                text = f"?? The MBTA has {len(stops)} stops. What are you looking for?"
            
            return {
                "ok": True,
                "count": len(stops),
                "stops": processed_stops,
                "text": text
            }
        
        except Exception as e:
            logger.error(f"Error: {e}", exc_info=True)
            return {"ok": False, "text": "Error searching stops."}
    
    async def find_stops_by_search_terms(self, search_terms: set) -> Dict[str, Any]:
        """Find stops by search terms"""
        try:
            if not search_terms:
                return {"ok": True, "count": 0, "stops": [], "text": "Please specify which stop."}
            
            params = {
                "api_key": self.mbta_api_key,
                "page[limit]": 500
            }
            
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{MBTA_BASE_URL}/stops",
                    params=params,
                    timeout=10
                )
                response.raise_for_status()
            
            all_stops = response.json().get("data", [])
            
            matching_stops = []
            for stop in all_stops:
                stop_name = stop.get("attributes", {}).get("name", "").lower()
                stop_words = set(stop_name.split())
                
                for term in search_terms:
                    if term in stop_name or any(w in term for w in stop_words):
                        matching_stops.append(stop)
                        break
            
            # Remove duplicates
            seen = set()
            unique_stops = []
            for stop in matching_stops:
                stop_id = stop.get("id")
                if stop_id not in seen:
                    seen.add(stop_id)
                    unique_stops.append(stop)
            
            if not unique_stops:
                return {"ok": True, "count": 0, "stops": [], "text": f"No stops found."}
            
            processed = []
            for stop in unique_stops[:20]:
                attributes = stop.get("attributes", {})
                processed.append({
                    "id": stop.get("id"),
                    "name": attributes.get("name", "Unknown"),
                    "municipality": attributes.get("municipality"),
                    "wheelchair_accessible": attributes.get("wheelchair_boarding") == 1,
                })
            
            text = f"?? Found {len(unique_stops)} stop(s):\n\n"
            for i, stop in enumerate(processed[:10]):
                municipality = stop.get("municipality", "")
                wheelchair = " ?" if stop.get("wheelchair_accessible") else ""
                stop_line = f"{i+1}. {stop['name']}"
                if municipality:
                    stop_line += f" ({municipality})"
                stop_line += wheelchair
                text += stop_line + "\n"
            
            if len(unique_stops) > 10:
                text += f"\n... and {len(unique_stops) - 10} more"
            
            return {"ok": True, "count": len(unique_stops), "stops": processed, "text": text}
        
        except Exception as e:
            logger.error(f"Error: {e}")
            return {"ok": False, "text": "Error searching stops."}
    
    async def execute(self, context: RequestContext, event_queue: EventQueue):
        """Execute with FIXED LLM detection"""
        try:
            message_text = ""
            for part in context.message.parts:
                if hasattr(part, 'root') and hasattr(part.root, 'text'):
                    message_text = part.root.text
                    break
                elif hasattr(part, 'text'):
                    message_text = part.text
                    break
            
            logger.info(f"?? StopFinder: '{message_text}'")
            
            # LLM Landmark Detection
            landmark_result = await self.detect_landmark_with_llm(message_text)
            
            if landmark_result.get("has_landmark"):
                landmark_name = landmark_result.get("landmark_name", "")
                search_query = landmark_result.get("search_query", "")
                landmark_type = landmark_result.get("landmark_type", "")
                
                logger.info(f"??? Landmark: {landmark_name} ({landmark_type})")
                
                result = await self.find_stops(query=search_query)
                
                if result.get("ok") and result.get("count") > 0:
                    response_text = f"?? {landmark_name} is a {landmark_type}.\n\n{result.get('text', '')}"
                else:
                    response_text = f"?? {landmark_name} ({landmark_type}), but couldn't find nearby stations."
            
            else:
                # No landmark - normal search
                route = self.extract_route_from_query(message_text)
                
                if route:
                    result = await self.find_stops(route=route)
                else:
                    search_terms = self.extract_search_terms(message_text)
                    if search_terms:
                        result = await self.find_stops_by_search_terms(search_terms)
                    else:
                        result = await self.find_stops()
                
                response_text = result.get("text", "Could not find stops")
            
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
                parts=[TextPart(text=f"? Error: {str(e)}")],
                role="agent"
            )
            await event_queue.enqueue_event(error_message)
    
    async def cancel(self, context: RequestContext, event_queue: EventQueue):
        raise NotImplementedError()


def main():
    load_dotenv()
    mbta_api_key = os.getenv("MBTA_API_KEY", "")
    openai_api_key = os.getenv("OPENAI_API_KEY", "")
    
    skills = [
        AgentSkill(
            id="landmark_detection",
            name="LLM Landmark Detection",
            description="AI-powered landmark detection (FIXED - no hallucinations)",
            tags=["landmarks", "llm"],
            examples=["that hospital", "near Fenway", "Prudential building"]
        ),
        AgentSkill(
            id="stop_search",
            name="Stop Search",
            description="Search MBTA stops",
            tags=["stops", "search"],
            examples=["Find Park Street"]
        ),
    ]
    
    agent_card = AgentCard(
        name="mbta-stopfinder",
        description="MBTA stop finder with FIXED AI landmark detection",
        url="http://96.126.111.107:50053/",
        version="3.1.0",
        default_input_modes=["text"],
        default_output_modes=["text"],
        skills=skills,
        capabilities=AgentCapabilities(streaming=True)
    )
    
    executor = StopFinderExecutor(mbta_api_key, openai_api_key)
    handler = DefaultRequestHandler(executor, task_store=InMemoryTaskStore())
    server = A2AStarletteApplication(agent_card=agent_card, http_handler=handler)
    app = server.build()
    
    logger.info("?? StopFinder v3.1 with FIXED LLM")
    logger.info(f"? LLM enabled: {bool(openai_api_key)}")
    
    uvicorn.run(app, host="0.0.0.0", port=50053, log_level="info")


if __name__ == "__main__":
    main()

