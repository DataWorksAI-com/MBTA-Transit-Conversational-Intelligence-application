"""
MBTA Alerts Agent v6.0 - FINAL COMPLETE VERSION
- Answers historical pattern questions without needing current alerts
- Filters out accessibility alerts (elevators/escalators)
- Dynamic domain expertise with real MBTA 2020-2023 data
"""

import asyncio
import logging
import os
import sys
from typing import Optional, Dict, Any, List
from uuid import uuid4
from datetime import datetime

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
from openai import OpenAI

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
    logger.warning("OPENAI_API_KEY not found!")


class AlertsExecutor(AgentExecutor):
    """
    FINAL Complete Alerts Agent with Domain Expertise
    
    Features:
    - Answers historical pattern questions
    - Analyzes current incidents with historical context
    - Filters accessibility alerts properly
    - Uses real MBTA 2020-2023 data (41,970 incidents)
    """
    
    # REAL DATA from MBTA Service Alerts 2020-2023
    HISTORICAL_PATTERNS = {
        "TECHNICAL_PROBLEM": {
            "min": 25, "max": 73, "median": 41, "avg": 76,
            "sample_size": 23104,
            "description": "technical or signal equipment issues"
        },
        "POLICE_ACTIVITY": {
            "min": 20, "max": 50, "median": 33, "avg": 45,
            "sample_size": 2393,
            "description": "police investigations or incidents"
        },
        "MEDICAL_EMERGENCY": {
            "min": 23, "max": 63, "median": 33, "avg": 72,
            "sample_size": 1953,
            "description": "medical emergencies"
        },
        "ACCIDENT": {
            "min": 18, "max": 68, "median": 40, "avg": 62,
            "sample_size": 1047,
            "description": "vehicle accidents"
        },
        "MAINTENANCE": {
            "min": 28, "max": 82, "median": 46, "avg": 151,
            "sample_size": 976,
            "description": "maintenance work"
        },
        "WEATHER": {
            "min": 86, "max": 559, "median": 268, "avg": 298,
            "sample_size": 149,
            "description": "weather-related disruptions"
        },
        "UNKNOWN_CAUSE": {
            "min": 21, "max": 90, "median": 34, "avg": 103,
            "sample_size": 12061,
            "description": "unspecified disruptions"
        }
    }
    
    # PLANNED WORK IMPACT PATTERNS (Estimated - not from incident data)
    # These are typical delay impacts for different types of scheduled work
    PLANNED_WORK_PATTERNS = {
        "signal_work": {
            "delay_impact_min": 10,
            "delay_impact_max": 15,
            "description": "signal equipment upgrades or maintenance",
            "note": "Estimated additional travel time during work hours"
        },
        "track_work": {
            "delay_impact_min": 15,
            "delay_impact_max": 25,
            "description": "track maintenance or replacement",
            "note": "May require shuttle buses or single tracking"
        },
        "station_work": {
            "delay_impact_min": 5,
            "delay_impact_max": 10,
            "description": "station improvements or repairs",
            "note": "Minor delays from skip-stop service or platform work"
        },
        "general_maintenance": {
            "delay_impact_min": 10,
            "delay_impact_max": 15,
            "description": "general maintenance work",
            "note": "Typical impact during scheduled work periods"
        }
    }
    
    RAPID_TRANSIT = ["Red", "Orange", "Blue", "Green-B", "Green-C", "Green-D", "Green-E", "Mattapan"]
    
    def __init__(self, mbta_api_key: str, openai_api_key: str):
        self.mbta_api_key = mbta_api_key
        self.openai_client = OpenAI(api_key=openai_api_key) if openai_api_key else None
        logger.info("? Alerts Agent v6.0 - FINAL Complete Version")
    
    def is_historical_question(self, query: str) -> bool:
        """Detect if asking about historical patterns (not current status)"""
        q = query.lower()
        historical_indicators = [
            "typically", "usually", "how long do", "how long does",
            "based on past", "historical", "on average", "generally"
        ]
        return any(indicator in q for indicator in historical_indicators)
    
    def extract_cause_from_query(self, query: str) -> Optional[str]:
        """Extract what type of delay they're asking about"""
        q = query.lower()
        
        if any(w in q for w in ["technical", "signal", "equipment"]):
            return "TECHNICAL_PROBLEM"
        elif any(w in q for w in ["police", "investigation"]):
            return "POLICE_ACTIVITY"
        elif any(w in q for w in ["medical", "passenger"]):
            return "MEDICAL_EMERGENCY"
        elif any(w in q for w in ["accident", "collision"]):
            return "ACCIDENT"
        elif any(w in q for w in ["weather", "snow"]):
            return "WEATHER"
        elif any(w in q for w in ["maintenance", "construction"]):
            return "MAINTENANCE"
        
        return None
    
    def answer_historical_question(self, query: str) -> str:
        """
        Answer questions about historical patterns WITHOUT needing current alerts.
        
        NEW in v6.0: Can answer "how long do X delays take?" from data alone.
        """
        
        cause = self.extract_cause_from_query(query)
        
        if cause and cause in self.HISTORICAL_PATTERNS:
            pattern = self.HISTORICAL_PATTERNS[cause]
            
            response = f"Based on analysis of {pattern['sample_size']:,} {pattern['description']} from MBTA data (2020-2023):\n\n"
            response += f"• Typical duration: {pattern['median']} minutes (median)\n"
            response += f"• Range: {pattern['min']}-{pattern['max']} minutes (25th-75th percentile)\n"
            response += f"• Average: {pattern['avg']} minutes\n\n"
            response += f"This data shows {pattern['description']} usually resolve within this timeframe, though individual incidents can vary."
            
            logger.info(f"? Answered historical question from data: {cause}")
            return response
        
        # General question - show all patterns
        response = "Based on MBTA Service Alerts data (2020-2023), here are typical delay durations:\n\n"
        
        for cause_name, pattern in list(self.HISTORICAL_PATTERNS.items())[:4]:
            response += f"• {pattern['description'].title()}: {pattern['median']} min typical ({pattern['sample_size']:,} incidents)\n"
        
        response += f"\nThese are median durations from analysis of 41,970 total subway incidents."
        
        return response
    
    def extract_route(self, query: str) -> Optional[str]:
        """Extract route from query"""
        q = query.lower()
        mapping = {"red": "Red", "orange": "Orange", "blue": "Blue", "green": "Green-B"}
        for k, v in mapping.items():
            if k in q:
                return v
        return None
    
    def is_accessibility_alert(self, alert: Dict) -> bool:
        """Filter out elevator/escalator alerts"""
        attrs = alert.get("attributes", {})
        header = (attrs.get("header") or "").lower()
        desc = (attrs.get("description") or "").lower()
        
        # Accessibility indicators to filter OUT
        accessibility_keywords = [
            "elevator", "escalator", "lift", "accessibility",
            "wheelchair", "ada"
        ]
        
        return any(kw in header + desc for kw in accessibility_keywords)
    
    def calculate_elapsed(self, created_at: str) -> Optional[int]:
        """Calculate elapsed minutes"""
        if not created_at:
            return None
        try:
            created = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
            elapsed = datetime.now(created.tzinfo) - created
            return int(elapsed.total_seconds() / 60)
        except:
            return None
    
    def is_planned_work(self, alert: Dict) -> bool:
        """Detect planned work"""
        attrs = alert.get("attributes", {})
        header = (attrs.get("header") or "").lower()
        desc = (attrs.get("description") or "").lower()
        
        planned_keywords = [
            "planned", "scheduled", "construction", "signal work",
            "track work", "maintenance", "upgrade", "project"
        ]
        
        return any(kw in header + desc for kw in planned_keywords)
    
    def identify_planned_work_type(self, alert: Dict) -> str:
        """Identify type of planned work for impact estimation"""
        attrs = alert.get("attributes", {})
        header = (attrs.get("header") or "").lower()
        desc = (attrs.get("description") or "").lower()
        text = header + " " + desc
        
        if "signal work" in text or "signal" in text:
            return "signal_work"
        elif "track work" in text or "track" in text:
            return "track_work"
        elif "station" in text:
            return "station_work"
        else:
            return "general_maintenance"
    
    def analyze_planned_work(self, alert: Dict) -> str:
        """
        Analyze planned work and provide impact estimate.
        
        NEW: Uses PLANNED_WORK_PATTERNS for impact predictions.
        """
        attrs = alert.get("attributes", {})
        header = attrs.get("header") or ""
        
        # Identify work type
        work_type = self.identify_planned_work_type(alert)
        pattern = self.PLANNED_WORK_PATTERNS.get(work_type, self.PLANNED_WORK_PATTERNS["general_maintenance"])
        
        response = f"?? Scheduled: {header}\n\n"
        response += f"   Impact: Expect {pattern['delay_impact_min']}-{pattern['delay_impact_max']} minutes additional travel time\n"
        response += f"   Type: {pattern['description']}\n"
        response += f"   Note: {pattern['note']}\n"
        
        return response
    
    def analyze_active_incident(self, alert: Dict) -> str:
        """
        Analyze active incident with historical context.
        Returns formatted string showing the analysis.
        """
        attrs = alert.get("attributes", {})
        header = (attrs.get("header") or "")
        cause = (attrs.get("cause") or "UNKNOWN_CAUSE").upper()
        elapsed = self.calculate_elapsed(attrs.get("created_at"))
        
        # Get historical pattern
        pattern = self.HISTORICAL_PATTERNS.get(cause, self.HISTORICAL_PATTERNS["UNKNOWN_CAUSE"])
        
        # Build response
        response = f"?? {header}\n\n"
        response += f"?? Historical Context (from {pattern['sample_size']:,} past incidents, 2020-2023):\n"
        response += f"   Typical duration: {pattern['median']} min median (range: {pattern['min']}-{pattern['max']} min)\n\n"
        
        if elapsed:
            if elapsed > 180:
                response += f"   Status: Long-term disruption ({elapsed}+ minutes)\n"
                response += f"   Recommendation: This is likely a service change, not an acute delay\n"
            elif elapsed < pattern['median']:
                remaining = pattern['median'] - elapsed
                pct = int((elapsed / pattern['median']) * 100)
                response += f"   Current: {elapsed} minutes elapsed ({pct}% through typical duration)\n"
                response += f"   Prediction: Expect ~{remaining} more minutes based on median\n"
                response += f"   Recommendation: Wait if not urgent, or allow extra time\n"
            else:
                response += f"   Current: {elapsed} minutes elapsed (exceeding median of {pattern['median']} min)\n"
                response += f"   Status: Taking longer than typical\n"
                response += f"   Recommendation: Consider alternative routes\n"
        
        return response
    
    def extract_routes_from_alert(self, alert: Dict) -> List[str]:
        """Extract routes"""
        attrs = alert.get("attributes", {})
        informed = attrs.get("informed_entity", [])
        return list(set(e.get("route") for e in informed if e.get("route")))
    
    async def get_alerts(self, route: Optional[str] = None) -> List[Dict]:
        """Get alerts with proper filtering"""
        try:
            params = {"api_key": self.mbta_api_key}
            if route:
                params["filter[route]"] = route
            
            async with httpx.AsyncClient() as client:
                response = await client.get(f"{MBTA_BASE_URL}/alerts", params=params, timeout=10)
                response.raise_for_status()
            
            all_alerts = response.json().get("data", [])
            logger.info(f"Fetched {len(all_alerts)} total alerts")
            
            # Filter out accessibility alerts AND non-rapid-transit
            filtered = []
            for alert in all_alerts:
                # Skip accessibility alerts
                if self.is_accessibility_alert(alert):
                    continue
                
                # If route filter, keep all for that route
                if route:
                    filtered.append(alert)
                else:
                    # Filter to rapid transit only
                    routes = self.extract_routes_from_alert(alert)
                    if any(r in self.RAPID_TRANSIT for r in routes):
                        filtered.append(alert)
            
            logger.info(f"Filtered: {len(filtered)} transit alerts (removed {len(all_alerts)-len(filtered)} accessibility/bus)")
            return filtered
        
        except Exception as e:
            logger.error(f"Error: {e}")
            return []
    
    async def execute(self, context: RequestContext, event_queue: EventQueue):
        """Execute with smart historical data usage"""
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
            
            logger.info(f"?? Query: '{message_text[:80]}'")
            
            # ================================================================
            # Mode 1: Pure historical pattern question
            # ================================================================
            if self.is_historical_question(message_text):
                logger.info("?? Historical question - answering from data")
                response_text = self.answer_historical_question(message_text)
                
                response_message = Message(
                    message_id=str(uuid4()),
                    parts=[TextPart(text=response_text)],
                    role="agent"
                )
                await event_queue.enqueue_event(response_message)
                return
            
            # ================================================================
            # Mode 2: Current alerts with smart historical enhancement
            # ================================================================
            route = self.extract_route(message_text)
            alerts = await self.get_alerts(route)
            
            if not alerts:
                response_text = f"? No current transit delays on {route + ' Line' if route else 'the subway'}."
                
                response_message = Message(
                    message_id=str(uuid4()),
                    parts=[TextPart(text=response_text)],
                    role="agent"
                )
                await event_queue.enqueue_event(response_message)
                return
            
            # ================================================================
            # SMART: Check if query wants prediction/recommendation
            # ================================================================
            query_lower = message_text.lower()
            wants_prediction = any(kw in query_lower for kw in [
                "should i wait", "how long", "when will", "worth waiting",
                "should i", "recommend", "better to"
            ])
            
            logger.info(f"?? Analyzing {len(alerts)} alerts (wants_prediction={wants_prediction})")
            
            # Separate planned work from active incidents
            planned_alerts = []
            active_alerts = []
            
            for alert in alerts[:5]:
                if self.is_planned_work(alert):
                    if wants_prediction:
                        # User wants impact info - provide analysis
                        planned_alerts.append(self.analyze_planned_work(alert))
                    else:
                        # Just status check - simple format
                        attrs = alert.get("attributes", {})
                        header = attrs.get("header") or ""
                        planned_alerts.append(f"?? Scheduled: {header}")
                else:
                    # Active incident!
                    active_alerts.append(alert)
            
            # Build response
            response_parts = []
            
            # Show planned work if any
            if planned_alerts:
                response_parts.append("Current scheduled maintenance:\n" + "\n".join(planned_alerts))
            
            # ================================================================
            # SMART: Add historical prediction ONLY if relevant
            # ================================================================
            if active_alerts and wants_prediction:
                # User asked for prediction AND there's an active incident
                # Show historical analysis!
                logger.info("?? Active incident + prediction query ? Adding historical context")
                
                for alert in active_alerts[:2]:
                    analysis = self.analyze_active_incident(alert)
                    response_parts.append(analysis)
            
            elif active_alerts and not wants_prediction:
                # User just checking status, don't overwhelm with data
                for alert in active_alerts[:2]:
                    attrs = alert.get("attributes", {})
                    header = attrs.get("header") or ""
                    response_parts.append(f"?? Active: {header}")
            
            # Combine parts
            if response_parts:
                response_text = "\n\n".join(response_parts)
            else:
                response_text = "No significant transit delays currently."
            
            # Send
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
    mbta_api_key = os.getenv("MBTA_API_KEY", "")
    openai_api_key = os.getenv("OPENAI_API_KEY", "")
    
    skills = [
        AgentSkill(
            id="historical_patterns",
            name="Historical Pattern Analysis",
            description="Answers questions about typical delay durations from 41,970 incidents (2020-2023)",
            tags=["historical", "patterns", "data"],
            examples=["How long do medical delays take?", "Typical duration for signal problems?"]
        ),
        AgentSkill(
            id="dynamic_analysis",
            name="Current Incident Analysis",
            description="Analyzes current incidents with historical context",
            tags=["current", "analysis"],
            examples=["Should I wait?", "How serious is this?"]
        )
    ]
    
    agent_card = AgentCard(
        name="mbta-alerts",
        description="MBTA alerts with domain expertise - analyzes using 41,970 historical incidents (2020-2023)",
        url="http://96.126.111.107:50051/",
        version="6.0.0",
        default_input_modes=["text"],
        default_output_modes=["text"],
        skills=skills,
        capabilities=AgentCapabilities(streaming=True)
    )
    
    executor = AlertsExecutor(mbta_api_key, openai_api_key)
    handler = DefaultRequestHandler(executor, task_store=InMemoryTaskStore())
    server = A2AStarletteApplication(agent_card=agent_card, http_handler=handler)
    app = server.build()
    
    logger.info("=" * 80)
    logger.info("?? MBTA Alerts Agent v6.0 - FINAL")
    logger.info("   ? Answers historical pattern questions")
    logger.info("   ? Analyzes current incidents with context")
    logger.info("   ? Filters accessibility alerts")
    logger.info("   ? Real MBTA data (41,970 incidents)")
    logger.info("=" * 80)
    
    uvicorn.run(app, host="0.0.0.0", port=50051, log_level="info")


if __name__ == "__main__":
    main()

