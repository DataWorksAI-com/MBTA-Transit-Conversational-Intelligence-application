
"""
MBTA Stop Finder Agent v4.0 - FINAL PRODUCTION VERSION
- Landmark database for common Boston locations (Fenway Park, Brigham Circle, etc.)
- LLM fallback for unknown landmarks
- Bidirectional search
- All edge cases handled
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
    """
    Complete StopFinder with landmark database and LLM fallback
    
    NEW in v4.0:
    - Landmark database for 50+ common Boston locations
    - LLM fallback for unknown landmarks
    - Better prompt engineering
    """
    
    # ========================================================================
    # LANDMARK DATABASE - Common Boston locations mapped to nearest stations
    # Fixes: Fenway Park, Brigham Circle, Northeastern, etc.
    # ========================================================================
    
    LANDMARK_TO_STATION = {
        # Sports & Entertainment
        "fenway park": "Kenmore",
        "fenway": "Kenmore",
        "td garden": "North Station",
        "garden": "North Station",
        "boston garden": "North Station",
        
        # Hospitals & Medical Centers
        "brigham and women": "Brigham Circle",
        "brigham and womens": "Brigham Circle",
        "brigham circle": "Brigham Circle",
        "brigham": "Brigham Circle",
        "mass general": "Charles/MGH",
        "massachusetts general": "Charles/MGH",
        "mgh": "Charles/MGH",
        "longwood medical": "Longwood Medical Area",
        "longwood": "Longwood Medical Area",
        "beth israel": "Longwood Medical Area",
        "boston childrens": "Longwood Medical Area",
        "children's hospital": "Longwood Medical Area",
        "dana farber": "Longwood Medical Area",
        
        # Universities
        "northeastern": "Northeastern University",
        "northeastern university": "Northeastern University",
        "neu": "Northeastern University",
        "boston university": "Boston University East",
        "bu": "Boston University East",
        "harvard": "Harvard",
        "harvard university": "Harvard",
        "harvard square": "Harvard",
        "mit": "Kendall/MIT",
        "kendall": "Kendall/MIT",
        "berklee": "Hynes Convention Center",
        "berklee college": "Hynes Convention Center",
        "simmons": "Fenway",
        "emerson": "Boylston",
        
        # Shopping & Commercial
        "prudential": "Prudential",
        "pru": "Prudential",
        "prudential center": "Prudential",
        "copley place": "Copley",
        "copley mall": "Copley",
        "quincy market": "Government Center",
        "faneuil hall": "Government Center",
        "newbury street": "Arlington",
        "newbury": "Arlington",
        
        # Cultural & Tourist Sites
        "museum of fine arts": "Museum of Fine Arts",
        "mfa": "Museum of Fine Arts",
        "symphony hall": "Symphony",
        "boston common": "Park Street",
        "common": "Park Street",
        "public garden": "Arlington",
        "aquarium": "Aquarium",
        "new england aquarium": "Aquarium",
        
        # Neighborhoods & Areas
        "back bay": "Back Bay",
        "south end": "Back Bay",
        "north end": "Haymarket",
        "chinatown": "Chinatown",
        "downtown": "Downtown Crossing",
        "downtown crossing": "Downtown Crossing",
        "financial district": "State",
        "seaport": "South Station",
        "waterfront": "Aquarium",
        
        # Transportation Hubs
        "logan": "Airport",
        "logan airport": "Airport",
        "airport": "Airport",
        "south station": "South Station",
        "north station": "North Station",
        "back bay station": "Back Bay",
    }
    
    def __init__(self, mbta_api_key: str, openai_api_key: str = ""):
        self.mbta_api_key = mbta_api_key
        self.openai_api_key = openai_api_key
        self.llm_enabled = bool(openai_api_key)
        logger.info("✅ StopFinder v4.0 - Landmark Database + LLM Fallback")
    
    def check_landmark_database(self, query: str) -> Optional[str]:
        """
        Check landmark database FIRST (fastest, most accurate).
        
        NEW in v4.0: Handles 50+ common Boston landmarks.
        """
        query_lower = query.lower().strip()
        
        # Direct lookup
        if query_lower in self.LANDMARK_TO_STATION:
            station = self.LANDMARK_TO_STATION[query_lower]
            logger.info(f"✓ Landmark database hit: '{query}' → '{station}'")
            return station
        
        # Partial match (e.g., "near fenway" matches "fenway park")
        for landmark, station in self.LANDMARK_TO_STATION.items():
            if landmark in query_lower or query_lower in landmark:
                logger.info(f"✓ Landmark partial match: '{query}' → '{station}' (via '{landmark}')")
                return station
        
        logger.info(f"❌ Not in landmark database: '{query}'")
        return None
    
    async def detect_landmark_with_llm(self, query: str) -> Dict[str, Any]:
        """LLM fallback for landmarks not in database"""
        if not self.llm_enabled:
            return {"has_landmark": False}
        
        try:
            prompt = f"""Analyze this Boston transit query for landmarks:

Query: "{query}"

Is this asking about an MBTA station name or a landmark/building?

MBTA Station → {{"has_landmark": false}}
Landmark → {{"has_landmark": true, "landmark_name": "name", "landmark_type": "type", "search_query": "keyword"}}

Examples:
- "Park Street" → {{"has_landmark": false}}
- "Museum of Fine Arts" → {{"has_landmark": true, "landmark_name": "Museum of Fine Arts", "landmark_type": "museum", "search_query": "museum"}}
- "that hospital in Longwood" → {{"has_landmark": true, "landmark_name": "hospital", "landmark_type": "hospital", "search_query": "longwood"}}

JSON only:"""
            
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
            
            content = response.json()["choices"][0]["message"]["content"].strip()
            
            # Strip markdown
            if content.startswith("```"):
                content = content.replace("```json", "").replace("```", "").strip()
            
            result = json.loads(content)
            logger.info(f"✓ LLM: {result}")
            return result
            
        except Exception as e:
            logger.error(f"LLM error: {e}")
            return {"has_landmark": False}
    
    def extract_route_from_query(self, query: str) -> Optional[str]:
        """Extract route"""
        query_lower = query.lower()
        
        route_mapping = {
            "red line": "Red", "red": "Red",
            "orange line": "Orange", "orange": "Orange",
            "blue line": "Blue", "blue": "Blue",
            "green line": "Green-B", "green": "Green-B",
            "green-b": "Green-B", "green-c": "Green-C",
            "green-d": "Green-D", "green-e": "Green-E",
        }
        
        for keyword, route_id in route_mapping.items():
            if keyword in query_lower:
                return route_id
        
        return None
    
    def extract_search_terms(self, query: str) -> set:
        """Extract search terms"""
        query_clean = query.translate(str.maketrans('', '', string.punctuation))
        
        common_words = {
            'find', 'the', 'nearest', 'station', 'to', 'near', 'search', 'for',
            'show', 'me', 'where', 'is', 'stops', 'on', 'in', 'at', 'list',
            'how', 'many', 'are', 'there', 'what', 'can', 'get'
        }
        
        query_words = set(query_clean.lower().split()) - common_words
        query_words = {w for w in query_words if len(w) >= 3}
        return query_words
    
    async def find_stops(self, query: Optional[str] = None, route: Optional[str] = None) -> Dict[str, Any]:
        """Find stops"""
        try:
            params = {
                "api_key": self.mbta_api_key,
                "page[limit]": 500
            }
            
            if route:
                params["filter[route]"] = route
            else:
                params["filter[location_type]"] = "1"
            
            async with httpx.AsyncClient() as client:
                response = await client.get(f"{MBTA_BASE_URL}/stops", params=params, timeout=10)
                response.raise_for_status()
            
            all_stops = response.json().get("data", [])
            logger.info(f"Fetched {len(all_stops)} stops")
            
            if query:
                query_lower = query.lower().strip()
                filtered = []
                for stop in all_stops:
                    stop_name = stop.get("attributes", {}).get("name", "").lower()
                    if query_lower in stop_name or stop_name in query_lower:
                        filtered.append(stop)
                
                stops = filtered
                logger.info(f"Matched {len(stops)} for '{query}'")
            else:
                stops = all_stops
            
            if len(stops) == 0:
                return {"ok": True, "count": 0, "text": f"No stops found matching '{query}'."}
            
            # Format response
            if len(stops) == 1:
                stop = stops[0]
                attrs = stop.get("attributes", {})
                text = f"🚉 Found: {attrs.get('name')}"
                if attrs.get('municipality'):
                    text += f" in {attrs.get('municipality')}"
                return {"ok": True, "count": 1, "text": text}
            
            # Multiple stops
            text = f"🚉 Found {len(stops)} stop(s):\n\n"
            for i, stop in enumerate(stops[:10]):
                attrs = stop.get("attributes", {})
                name = attrs.get("name", "Unknown")
                city = attrs.get("municipality", "")
                wheelchair = " ♿" if attrs.get("wheelchair_boarding") == 1 else ""
                
                line = f"{i+1}. {name}"
                if city:
                    line += f" ({city})"
                line += wheelchair
                text += line + "\n"
            
            if len(stops) > 10:
                text += f"\n... and {len(stops) - 10} more"
            
            return {"ok": True, "count": len(stops), "text": text}
        
        except Exception as e:
            logger.error(f"Error: {e}")
            return {"ok": False, "text": "Error searching stops."}
    
    async def find_stops_by_search_terms(self, search_terms: set) -> Dict[str, Any]:
        """Find stops by search terms"""
        try:
            params = {"api_key": self.mbta_api_key, "page[limit]": 500}
            
            async with httpx.AsyncClient() as client:
                response = await client.get(f"{MBTA_BASE_URL}/stops", params=params, timeout=10)
                response.raise_for_status()
            
            all_stops = response.json().get("data", [])
            
            matching = []
            for stop in all_stops:
                stop_name = stop.get("attributes", {}).get("name", "").lower()
                if any(term in stop_name for term in search_terms):
                    matching.append(stop)
            
            # Remove duplicates
            seen = set()
            unique = []
            for stop in matching:
                sid = stop.get("id")
                if sid not in seen:
                    seen.add(sid)
                    unique.append(stop)
            
            if not unique:
                return {"ok": True, "count": 0, "text": "No stops found."}
            
            # Format
            text = f"🚉 Found {len(unique)} stop(s):\n\n"
            for i, stop in enumerate(unique[:10]):
                attrs = stop.get("attributes", {})
                name = attrs.get("name", "Unknown")
                city = attrs.get("municipality", "")
                wheelchair = " ♿" if attrs.get("wheelchair_boarding") == 1 else ""
                
                line = f"{i+1}. {name}"
                if city:
                    line += f" ({city})"
                line += wheelchair
                text += line + "\n"
            
            if len(unique) > 10:
                text += f"\n... and {len(unique) - 10} more"
            
            return {"ok": True, "count": len(unique), "text": text}
        
        except Exception as e:
            logger.error(f"Error: {e}")
            return {"ok": False, "text": "Error."}
    
    async def execute(self, context: RequestContext, event_queue: EventQueue):
        """
        Execute with landmark database FIRST, then LLM fallback
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
            
            logger.info(f"📨 StopFinder: '{message_text}'")
            
            # ================================================================
            # STEP 1: Check landmark database FIRST (fastest, most accurate)
            # ================================================================
            station_from_db = self.check_landmark_database(message_text)
            
            if station_from_db:
                # Found in database!
                response_text = f"🚉 Found: {station_from_db}"
                
                response_message = Message(
                    message_id=str(uuid4()),
                    parts=[TextPart(text=response_text)],
                    role="agent"
                )
                await event_queue.enqueue_event(response_message)
                logger.info(f"✅ Landmark database response: {station_from_db}")
                return
            
            # ================================================================
            # STEP 2: Not in database - try LLM landmark detection
            # ================================================================
            landmark_result = await self.detect_landmark_with_llm(message_text)
            
            if landmark_result.get("has_landmark"):
                landmark_name = landmark_result.get("landmark_name", "")
                search_query = landmark_result.get("search_query", "")
                landmark_type = landmark_result.get("landmark_type", "")
                
                logger.info(f"🏛️ LLM detected: {landmark_name} ({landmark_type})")
                
                result = await self.find_stops(query=search_query)
                
                if result.get("ok") and result.get("count") > 0:
                    response_text = f"📍 {landmark_name} is a {landmark_type}.\n\n{result.get('text', '')}"
                else:
                    response_text = f"📍 {landmark_name} ({landmark_type}), but couldn't find nearby stations."
            
            else:
                # ================================================================
                # STEP 3: Normal station search
                # ================================================================
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
            
            # Send response
            response_message = Message(
                message_id=str(uuid4()),
                parts=[TextPart(text=response_text)],
                role="agent"
            )
            
            await event_queue.enqueue_event(response_message)
            logger.info("✅ Response sent")
            
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
    mbta_api_key = os.getenv("MBTA_API_KEY", "")
    openai_api_key = os.getenv("OPENAI_API_KEY", "")
    
    skills = [
        AgentSkill(
            id="landmark_database",
            name="Landmark Database",
            description="50+ Boston landmarks (Fenway Park, Brigham Circle, Northeastern, etc.)",
            tags=["landmarks", "database"],
            examples=["Fenway Park", "Brigham Circle", "Northeastern"]
        ),
        AgentSkill(
            id="llm_fallback",
            name="LLM Landmark Detection",
            description="AI-powered detection for unknown landmarks",
            tags=["llm", "landmarks"],
            examples=["that hospital near Longwood"]
        ),
        AgentSkill(
            id="stop_search",
            name="Stop Search",
            description="Search MBTA stops by name or route",
            tags=["stops"],
            examples=["Find Kendall", "Red Line stops"]
        ),
    ]
    
    agent_card = AgentCard(
        name="mbta-stopfinder",
        description="MBTA stop finder with landmark database and LLM fallback",
        url="http://96.126.111.107:50053/",
        version="4.0.0",
        default_input_modes=["text"],
        default_output_modes=["text"],
        skills=skills,
        capabilities=AgentCapabilities(streaming=True)
    )
    
    executor = StopFinderExecutor(mbta_api_key, openai_api_key)
    handler = DefaultRequestHandler(executor, task_store=InMemoryTaskStore())
    server = A2AStarletteApplication(agent_card=agent_card, http_handler=handler)
    app = server.build()
    
    logger.info("=" * 80)
    logger.info("🚀 StopFinder v4.0 - Final Production")
    logger.info("   ✅ 50+ landmark database")
    logger.info("   ✅ LLM fallback")
    logger.info("   ✅ Bidirectional search")
    logger.info("=" * 80)
    
    uvicorn.run(app, host="0.0.0.0", port=50053, log_level="info")


if __name__ == "__main__":
    main()
