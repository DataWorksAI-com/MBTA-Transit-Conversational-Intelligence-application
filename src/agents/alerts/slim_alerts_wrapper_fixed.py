
"""
MBTA Alerts Agent v7.0 - COMPLETE FINAL VERSION
- Real-time crowding estimation with next train predictions
- Historical delay patterns (41,970 incidents, 2020-2023)
- Active incident analysis with historical context
- Filters accessibility alerts (elevators/escalators)
- Domain expertise for recommendations
- Full transparency disclaimers
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

MBTA_API_KEY = os.getenv('MBTA_API_KEY', 'c845eff5ae504179bc9cfa69914059de')
MBTA_BASE_URL = "https://api-v3.mbta.com"
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
openai_client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

if not MBTA_API_KEY:
    logger.warning("MBTA_API_KEY not found!")
if not OPENAI_API_KEY:
    logger.warning("OPENAI_API_KEY not found!")


class AlertsExecutor(AgentExecutor):
    HISTORICAL_PATTERNS = {
        "TECHNICAL_PROBLEM": {"min": 25, "max": 73, "median": 41, "avg": 76, "sample_size": 23104, "description": "technical or signal equipment issues"},
        "POLICE_ACTIVITY": {"min": 20, "max": 50, "median": 33, "avg": 45, "sample_size": 2393, "description": "police investigations or incidents"},
        "MEDICAL_EMERGENCY": {"min": 23, "max": 63, "median": 33, "avg": 72, "sample_size": 1953, "description": "medical emergencies"},
        "ACCIDENT": {"min": 18, "max": 68, "median": 40, "avg": 62, "sample_size": 1047, "description": "vehicle accidents"},
        "MAINTENANCE": {"min": 28, "max": 82, "median": 46, "avg": 151, "sample_size": 976, "description": "maintenance work"},
        "WEATHER": {"min": 86, "max": 559, "median": 268, "avg": 298, "sample_size": 149, "description": "weather-related disruptions"},
        "UNKNOWN_CAUSE": {"min": 21, "max": 90, "median": 34, "avg": 103, "sample_size": 12061, "description": "unspecified disruptions"},
    }
    PLANNED_WORK_PATTERNS = {
        "signal_work": {"delay_impact_min": 10, "delay_impact_max": 15, "description": "signal equipment upgrades or maintenance"},
        "track_work": {"delay_impact_min": 15, "delay_impact_max": 25, "description": "track maintenance or replacement"},
        "station_work": {"delay_impact_min": 5, "delay_impact_max": 10, "description": "station improvements or repairs"},
        "general_maintenance": {"delay_impact_min": 10, "delay_impact_max": 15, "description": "general maintenance work"},
    }
    OCCUPANCY_SCORES = {
        "EMPTY": 0, "MANY_SEATS_AVAILABLE": 20, "FEW_SEATS_AVAILABLE": 50, "STANDING_ROOM_ONLY": 75,
        "CRUSHED_STANDING_ROOM_ONLY": 90, "FULL": 100, "NOT_ACCEPTING_PASSENGERS": 100, None: 50
    }
    CROWDING_PATTERNS = {"morning_rush": (7, 9, 80), "afternoon_rush": (15, 18, 75), "midday": (11, 15, 30), "evening": (18, 22, 50)}
    RAPID_TRANSIT = ["Red", "Orange", "Blue", "Green-B", "Green-C", "Green-D", "Green-E", "Mattapan"]

    def __init__(self, mbta_api_key: str, openai_api_key: str):
        self.mbta_api_key = mbta_api_key
        self.openai_client = OpenAI(api_key=openai_api_key) if openai_api_key else None
        logger.info("✅ Alerts Agent v7.0 - COMPLETE FINAL")

    def is_historical_question(self, query: str) -> bool:
        q = query.lower()
        return any(i in q for i in ["typically", "usually", "how long do", "how long does", "based on past", "historical", "on average", "generally"])

    def extract_cause_from_query(self, query: str) -> Optional[str]:
        q = query.lower()
        if any(w in q for w in ["technical", "signal", "equipment"]): return "TECHNICAL_PROBLEM"
        if any(w in q for w in ["police", "investigation"]): return "POLICE_ACTIVITY"
        if any(w in q for w in ["medical", "passenger"]): return "MEDICAL_EMERGENCY"
        if any(w in q for w in ["accident", "collision"]): return "ACCIDENT"
        if any(w in q for w in ["weather", "snow"]): return "WEATHER"
        if any(w in q for w in ["maintenance", "construction"]): return "MAINTENANCE"
        return None

    def answer_historical_question(self, query: str) -> str:
        cause = self.extract_cause_from_query(query)
        if cause and cause in self.HISTORICAL_PATTERNS:
            pattern = self.HISTORICAL_PATTERNS[cause]
            return (
                f"Based on analysis of {pattern['sample_size']:,} {pattern['description']} from MBTA data (2020-2023):\n\n"
                f"• Typical duration: {pattern['median']} minutes (median)\n"
                f"• Range: {pattern['min']}-{pattern['max']} minutes (25th-75th percentile)\n"
                f"• Average: {pattern['avg']} minutes\n\n"
                f"This data shows {pattern['description']} usually resolve within this timeframe, though individual incidents vary.\n\n"
                "ℹ️ *Based on historical MBTA data (41,970 incidents, 2020-2023). Individual incidents may differ. Not a prediction of current delay duration.*"
            )
        response = "Based on MBTA Service Alerts data (2020-2023), typical delay durations:\n\n"
        for _, pattern in list(self.HISTORICAL_PATTERNS.items())[:4]:
            response += f"• {pattern['description'].title()}: {pattern['median']} min median ({pattern['sample_size']:,} incidents)\n"
        response += "\nFrom analysis of 41,970 total subway incidents.\n\n"
        response += "ℹ️ *Historical data (2020-2023). Individual delays vary. Not a guarantee of current conditions.*"
        return response

    def calculate_elapsed(self, created_at: str) -> Optional[int]:
        if not created_at: return None
        try:
            created = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
            return int((datetime.now(created.tzinfo) - created).total_seconds() / 60)
        except:
            return None

    def is_planned_work(self, alert: Dict) -> bool:
        attrs = alert.get("attributes", {})
        text = ((attrs.get("header") or "") + " " + (attrs.get("description") or "")).lower()
        return any(kw in text for kw in ["planned", "scheduled", "construction", "signal work", "track work", "maintenance", "upgrade"])

    def identify_planned_work_type(self, alert: Dict) -> str:
        text = ((alert.get("attributes", {}).get("header") or "") + " " + (alert.get("attributes", {}).get("description") or "")).lower()
        if "signal work" in text or "signal" in text: return "signal_work"
        if "track work" in text or "track" in text: return "track_work"
        if "station" in text: return "station_work"
        return "general_maintenance"

    def analyze_planned_work(self, alert: Dict) -> str:
        header = alert.get("attributes", {}).get("header") or ""
        work_type = self.identify_planned_work_type(alert)
        pattern = self.PLANNED_WORK_PATTERNS.get(work_type, self.PLANNED_WORK_PATTERNS["general_maintenance"])
        return (
            f"📋 Scheduled: {header}\n\n"
            f"   Impact: Expect {pattern['delay_impact_min']}-{pattern['delay_impact_max']} minutes additional travel time\n"
            f"   Type: {pattern['description']}\n"
        )

    def analyze_active_incident(self, alert: Dict) -> str:
        attrs = alert.get("attributes", {})
        header = attrs.get("header") or ""
        cause = (attrs.get("cause") or "UNKNOWN_CAUSE").upper()
        elapsed = self.calculate_elapsed(attrs.get("created_at"))
        pattern = self.HISTORICAL_PATTERNS.get(cause, self.HISTORICAL_PATTERNS["UNKNOWN_CAUSE"])
        response = (
            f"⚠️ {header}\n\n"
            f"📊 Historical Context ({pattern['sample_size']:,} past incidents, 2020-2023):\n"
            f"   Typical: {pattern['median']} min median (range: {pattern['min']}-{pattern['max']} min)\n\n"
        )
        if elapsed:
            if elapsed < pattern['median']:
                remaining = pattern['median'] - elapsed
                pct = int((elapsed / pattern['median']) * 100)
                response += f"   Current: {elapsed} min elapsed ({pct}% through typical duration)\n"
                response += f"   Prediction: Expect ~{remaining} more minutes based on median\n"
            else:
                response += f"   Current: {elapsed} min elapsed (exceeding median)\n"
                response += "   Status: Taking longer than typical\n"
                response += "   Recommendation: Consider alternative routes\n"
        return response

    def extract_routes_from_alert(self, alert: Dict) -> List[str]:
        informed = alert.get("attributes", {}).get("informed_entity", [])
        return list(set(e.get("route") for e in informed if e.get("route")))

    def is_crowding_question(self, query: str) -> bool:
        q = query.lower()
        return any(kw in q for kw in ["crowded", "crowd", "busy", "full", "packed", "space", "capacity", "occupancy", "how full", "standing room", "seats available", "room on", "packed train"])

    async def extract_stop_id_from_query(self, query: str) -> Optional[str]:
        q = query.lower()
        stop_map = {
            "park street": "place-pktrm", "park": "place-pktrm", "harvard": "place-harsq", "south station": "place-sstat",
            "downtown crossing": "place-dwnxg", "downtown": "place-dwnxg", "north station": "place-north", "kendall": "place-knncl",
            "central": "place-cntsq", "kenmore": "place-kencl", "copley": "place-coecl", "back bay": "place-bbsta",
        }
        for name, stop_id in stop_map.items():
            if name in q:
                return stop_id
        return None

    async def get_crowding_estimate(self, route: str, stop_id: Optional[str] = None) -> Dict[str, Any]:
        try:
            params = {"api_key": self.mbta_api_key, "filter[route]": route}
            async with httpx.AsyncClient() as client:
                response = await client.get(f"{MBTA_BASE_URL}/vehicles", params=params, timeout=10)
                response.raise_for_status()
            vehicles_data = response.json().get('data', [])
            if not vehicles_data:
                return self.get_time_based_crowding()
            vehicle_occupancy_map = {}
            occupancy_scores = []
            for vehicle in vehicles_data:
                vid = vehicle.get('id')
                attrs = vehicle.get('attributes', {})
                status = attrs.get('occupancy_status')
                score = self.OCCUPANCY_SCORES.get(status, 50)
                vehicle_occupancy_map[vid] = {"status": status or "UNKNOWN", "score": score, "label": attrs.get('label', 'Unknown')}
                occupancy_scores.append(score)
            avg_score = sum(occupancy_scores) / len(occupancy_scores)
            if avg_score < 30:
                level, emoji, rec = "low", "🟢", "Trains have plenty of space. Good time to travel!"
            elif avg_score < 60:
                level, emoji, rec = "moderate", "🟡", "Trains moderately busy. You'll likely find a seat."
            else:
                level, emoji, rec = "high", "🔴", "Trains crowded. Consider waiting or off-peak travel."
            result = {"route": route, "level": level, "emoji": emoji, "average_occupancy": round(avg_score, 1), "vehicles_analyzed": len(occupancy_scores), "recommendation": rec, "source": "real_time_vehicles", "next_trains": []}
            if stop_id:
                pred_params = {"api_key": self.mbta_api_key, "filter[stop]": stop_id, "filter[route]": route, "page[limit]": 5}
                async with httpx.AsyncClient() as client:
                    pred_response = await client.get(f"{MBTA_BASE_URL}/predictions", params=pred_params, timeout=10)
                    pred_response.raise_for_status()
                predictions = pred_response.json().get('data', [])
                next_trains = []
                for pred in predictions[:5]:
                    pred_attrs = pred.get('attributes', {})
                    vehicle_id = pred.get('relationships', {}).get('vehicle', {}).get('data', {}).get('id')
                    arrival_time = pred_attrs.get('arrival_time')
                    if arrival_time and vehicle_id:
                        occ_info = vehicle_occupancy_map.get(vehicle_id, {"status": "UNKNOWN", "score": 50})
                        try:
                            arrival_dt = datetime.fromisoformat(arrival_time.replace('Z', '+00:00'))
                            now = datetime.now(arrival_dt.tzinfo)
                            minutes = int((arrival_dt - now).total_seconds() / 60)
                            next_trains.append({"minutes": minutes, "occupancy": occ_info['status'], "occupancy_score": occ_info['score']})
                        except:
                            pass
                next_trains.sort(key=lambda t: t['minutes'])
                result["next_trains"] = next_trains[:3]
            return result
        except:
            return self.get_time_based_crowding()

    def get_time_based_crowding(self) -> Dict[str, Any]:
        now = datetime.now()
        hour = now.hour
        for period_name, (start, end, expected) in self.CROWDING_PATTERNS.items():
            if start <= hour < end:
                level = "high" if expected > 70 else "moderate" if expected > 40 else "low"
                emoji = "🔴" if level == "high" else "🟡" if level == "moderate" else "🟢"
                return {"level": level, "emoji": emoji, "average_occupancy": expected, "source": "time_based_estimate", "recommendation": f"Based on time ({period_name.replace('_', ' ')}): {level} crowding expected."}
        return {"level": "moderate", "emoji": "🟡", "average_occupancy": 50, "source": "time_based_default", "recommendation": "Moderate crowding expected."}

    def format_crowding_response(self, crowding: Dict[str, Any]) -> str:
        route = crowding.get('route', '')
        level = crowding.get('level', '')
        avg = crowding.get('average_occupancy', 0)
        emoji = crowding.get('emoji', '')
        rec = crowding.get('recommendation', '')
        source = crowding.get('source', '')
        next_trains = crowding.get('next_trains', [])
        response = f"{emoji} **{route} Line Crowding: {level.upper()}**\n\n"
        response += f"📊 Overall: {avg:.0f}% average occupancy"
        response += f" across {crowding.get('vehicles_analyzed', 0)} trains\n\n" if source == "real_time_vehicles" else "\n\n"
        if next_trains:
            response += "⏰ **Next Trains at This Stop:**\n\n"
            for i, train in enumerate(next_trains, 1):
                minutes = train['minutes']
                occ = train['occupancy'].replace('_', ' ').title()
                score = train['occupancy_score']
                t_emoji = "🟢" if score < 30 else "🟡" if score < 60 else "🔴"
                time_txt = f"{minutes} min" if minutes > 0 else "Arriving now"
                response += f"{t_emoji} Train {i}: {time_txt}\n"
                response += f"   Crowding: {occ} ({score}%)\n"
            response += "\n"
        response += f"{rec}\n\n"
        response += "ℹ️ *Data from MBTA real-time vehicle occupancy sensors (updated every 10-30 seconds)*" if source == "real_time_vehicles" else "ℹ️ *Estimated from typical patterns. Live vehicle data not available.*"
        return response

    def extract_route(self, query: str) -> Optional[str]:
        q = query.lower()
        mapping = {"red": "Red", "orange": "Orange", "blue": "Blue", "green": "Green-B"}
        for k, v in mapping.items():
            if k in q: return v
        return None

    def is_accessibility_alert(self, alert: Dict) -> bool:
        attrs = alert.get("attributes", {})
        header = (attrs.get("header") or "").lower()
        desc = (attrs.get("description") or "").lower()
        effect = (attrs.get("effect") or "").lower()
        informed = attrs.get("informed_entity", [])
        for entity in informed:
            if entity.get("facility"):
                return True
        accessibility_keywords = ["elevator", "escalator", "lift", "accessibility", "wheelchair", "ada", "ramp", "pedal & park", "bike rack", "parking", "facility"]
        full_text = header + " " + desc + " " + effect
        return any(kw in full_text for kw in accessibility_keywords)

    async def get_alerts(self, route: Optional[str] = None) -> List[Dict]:
        try:
            params = {"api_key": self.mbta_api_key}
            if route:
                params["filter[route]"] = route
            async with httpx.AsyncClient() as client:
                response = await client.get(f"{MBTA_BASE_URL}/alerts", params=params, timeout=10)
                response.raise_for_status()
            all_alerts = response.json().get("data", [])
            filtered = []
            for alert in all_alerts:
                if self.is_accessibility_alert(alert):
                    continue
                if route:
                    filtered.append(alert)
                else:
                    routes = self.extract_routes_from_alert(alert)
                    if any(r in self.RAPID_TRANSIT for r in routes):
                        filtered.append(alert)
            return filtered
        except Exception as e:
            logger.error(f"Error: {e}")
            return []

    async def execute(self, context: RequestContext, event_queue: EventQueue):
        try:
            message_text = ""
            for part in context.message.parts:
                if hasattr(part, 'root') and hasattr(part.root, 'text'):
                    message_text = part.root.text
                    break
                elif hasattr(part, 'text'):
                    message_text = part.text
                    break
            logger.info(f"📨 Alerts: '{message_text[:80]}'")

            if self.is_crowding_question(message_text):
                route = self.extract_route(message_text)
                if not route:
                    response_text = "Which line would you like crowding info for? (Red, Orange, Blue, or Green)"
                else:
                    stop_id = await self.extract_stop_id_from_query(message_text)
                    crowding = await self.get_crowding_estimate(route, stop_id)
                    response_text = self.format_crowding_response(crowding)
                await event_queue.enqueue_event(Message(message_id=str(uuid4()), parts=[TextPart(text=response_text)], role="agent"))
                return

            if self.is_historical_question(message_text):
                response_text = self.answer_historical_question(message_text)
                await event_queue.enqueue_event(Message(message_id=str(uuid4()), parts=[TextPart(text=response_text)], role="agent"))
                return

            route = self.extract_route(message_text)
            alerts = await self.get_alerts(route)
            if not alerts:
                response_text = f"✅ No current transit delays on {route + ' Line' if route else 'the subway'}."
                await event_queue.enqueue_event(Message(message_id=str(uuid4()), parts=[TextPart(text=response_text)], role="agent"))
                return

            query_lower = message_text.lower()
            wants_prediction = any(kw in query_lower for kw in ["should i wait", "how long", "when will", "worth waiting", "should i", "recommend", "better to"])
            planned_alerts = []
            active_alerts = []
            for alert in alerts[:5]:
                if self.is_planned_work(alert):
                    if wants_prediction:
                        planned_alerts.append(self.analyze_planned_work(alert))
                    else:
                        header = alert.get("attributes", {}).get("header") or ""
                        planned_alerts.append(f"📋 Scheduled: {header}")
                else:
                    active_alerts.append(alert)

            response_parts = []
            if planned_alerts:
                response_parts.append("Current scheduled maintenance:\n" + "\n".join(planned_alerts))
            if active_alerts and wants_prediction:
                for alert in active_alerts[:2]:
                    response_parts.append(self.analyze_active_incident(alert))
            elif active_alerts and not wants_prediction:
                for alert in active_alerts[:2]:
                    header = alert.get("attributes", {}).get("header") or ""
                    response_parts.append(f"⚠️ Active: {header}")
            response_text = "\n\n".join(response_parts) if response_parts else "No significant transit delays."
            await event_queue.enqueue_event(Message(message_id=str(uuid4()), parts=[TextPart(text=response_text)], role="agent"))
            logger.info("✅ Response sent")
        except Exception as e:
            logger.error(f"Error: {e}", exc_info=True)
            await event_queue.enqueue_event(Message(message_id=str(uuid4()), parts=[TextPart(text=f"Error: {str(e)}")], role="agent"))

    async def cancel(self, context: RequestContext, event_queue: EventQueue):
        raise NotImplementedError()


def main():
    load_dotenv()
    mbta_api_key = os.getenv("MBTA_API_KEY", "")
    openai_api_key = os.getenv("OPENAI_API_KEY", "")
    skills = [
        AgentSkill(id="crowding_estimation", name="Real-Time Crowding Estimation", description="Vehicle occupancy sensors with next train predictions", tags=["crowding", "real-time"], examples=["How crowded is Red Line?", "Crowding at Park Street?"]),
        AgentSkill(id="historical_patterns", name="Historical Delay Analysis", description="41,970 incidents (2020-2023) for delay predictions", tags=["historical", "patterns"], examples=["How long do medical delays take?", "Typical signal delay?"]),
        AgentSkill(id="active_incident_analysis", name="Active Incident Analysis", description="Analyzes current incidents with historical context", tags=["analysis", "prediction"], examples=["Should I wait?", "How serious is this delay?"]),
        AgentSkill(id="service_alerts", name="Current Service Alerts", description="Real-time disruptions and delays", tags=["alerts", "current"], examples=["Red Line delays?", "Current issues?"]),
    ]
    agent_card = AgentCard(
        name="mbta-alerts",
        description="Complete MBTA alerts agent with crowding estimation, historical pattern analysis (41,970 incidents), and domain expertise",
        url="http://96.126.111.107:50051/",
        version="7.0.0",
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
    logger.info("🚀 MBTA Alerts Agent v7.0 - COMPLETE FINAL")
    logger.info("=" * 80)
    logger.info("✅ Real-time crowding estimation")
    logger.info("✅ Next train predictions with crowding")
    logger.info("✅ Historical delay patterns (41,970 incidents)")
    logger.info("✅ Active incident analysis")
    logger.info("✅ Domain expertise recommendations")
    logger.info("✅ Full transparency disclaimers")
    logger.info("=" * 80)
    uvicorn.run(app, host="0.0.0.0", port=50051, log_level="info")


if __name__ == "__main__":
    main()
