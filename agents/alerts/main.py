"""
MBTA Alerts Agent - Real API + Historical Intelligence
Fetches live service alerts from MBTA API v3 and enriches with
41,970 historical incident patterns (2020-2023) for delay type
classification and duration estimates.
"""

from fastapi import FastAPI, Query, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Dict, Any, Optional, List
import logging
import os
import requests
from datetime import datetime
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
import agentviz
agentviz.init(server="http://172.104.13.21:8000", project="mbta")

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("alerts-agent")

try:
    from src.observability.otel_config import setup_otel
    setup_otel("alerts-agent")
except Exception as e:
    log.warning(f"Could not setup telemetry: {e}")

app = FastAPI(title="mbta-alerts-agent", version="2.0.0")

@app.on_event("startup")
async def _dans_register():
    try:
        import os
        from agents.common.registry_client import RegistryClient
        host = os.getenv("AGENT_HOST", "96.126.111.107")
        port = int(os.getenv("PORT", "8001"))
        _r = RegistryClient()
        _r.register(
            agent_id  = "mbta-alerts-agent",
            agent_url = f"http://{host}:{port}",
            api_url   = f"http://{host}:{port}",
        )
    except Exception as _e:
        import logging; logging.getLogger("alerts-agent").warning(f"DANS register failed: {_e}")
try:
    FastAPIInstrumentor.instrument_app(app)
except Exception as e:
    log.warning(f"Could not instrument FastAPI: {e}")

# ─── Configuration ────────────────────────────────────────────────────────────
MBTA_API_KEY = os.getenv('MBTA_API_KEY')
MBTA_BASE_URL = "https://api-v3.mbta.com"
if not MBTA_API_KEY:
    log.warning("MBTA_API_KEY not found in environment variables!")

# ─── Historical Patterns (41,970 incidents 2020-2023) ─────────────────────────
HISTORICAL_PATTERNS = {
    "MEDICAL_EMERGENCY": {
        "min": 23, "max": 63, "median": 33, "avg": 72,
        "sample_size": 1953,
        "label": "Medical Emergency",
        "emoji": "🚑",
        "description": "medical emergencies requiring EMS response",
        "typical": "typically 23–63 min, median 33 min",
    },
    "TECHNICAL_PROBLEM": {
        "min": 25, "max": 73, "median": 41, "avg": 76,
        "sample_size": 23104,
        "label": "Technical / Signal Problem",
        "emoji": "⚙️",
        "description": "signal failures, equipment malfunctions, disabled trains",
        "typical": "typically 25–73 min, median 41 min",
    },
    "POLICE_ACTIVITY": {
        "min": 20, "max": 50, "median": 33, "avg": 45,
        "sample_size": 2393,
        "label": "Police Activity",
        "emoji": "🚔",
        "description": "police investigations or security incidents",
        "typical": "typically 20–50 min, median 33 min",
    },
    "ACCIDENT": {
        "min": 18, "max": 68, "median": 40, "avg": 62,
        "sample_size": 1047,
        "label": "Accident",
        "emoji": "💥",
        "description": "vehicle collisions or on-track accidents",
        "typical": "typically 18–68 min, median 40 min",
    },
    "MAINTENANCE": {
        "min": 28, "max": 82, "median": 46, "avg": 151,
        "sample_size": 976,
        "label": "Scheduled Maintenance",
        "emoji": "🔧",
        "description": "planned maintenance, track work, shuttle replacements",
        "typical": "typically 28–82 min (acute impact), planned work varies widely",
    },
    "WEATHER": {
        "min": 86, "max": 559, "median": 268, "avg": 298,
        "sample_size": 149,
        "label": "Weather-Related",
        "emoji": "🌧️",
        "description": "storms, snow, ice, extreme weather disruptions",
        "typical": "typically 86–559 min, median ~4.5 hours — longest category",
    },
    "UNKNOWN_CAUSE": {
        "min": 21, "max": 90, "median": 34, "avg": 103,
        "sample_size": 12061,
        "label": "General Disruption",
        "emoji": "ℹ️",
        "description": "unspecified or mixed disruptions",
        "typical": "typically 21–90 min, median 34 min",
    },
}

# ─── Query → Delay Type Mapping ───────────────────────────────────────────────
QUERY_DELAY_KEYWORDS: Dict[str, List[str]] = {
    "MEDICAL_EMERGENCY": [
        "medical", "medical emergency", "medical delay", "medic", "ems",
        "ambulance", "paramedic", "health emergency", "sick passenger",
        "sick customer",
    ],
    "TECHNICAL_PROBLEM": [
        "technical", "signal", "signals", "equipment", "mechanical",
        "disabled train", "power outage", "electrical", "circuit",
        "broken", "malfunction", "failure",
    ],
    "POLICE_ACTIVITY": [
        "police", "police activity", "law enforcement", "investigation",
        "security incident", "suspicious package",
    ],
    "ACCIDENT": [
        "accident", "collision", "crash", "struck",
    ],
    "MAINTENANCE": [
        "maintenance", "repair", "track work", "shuttle", "planned work",
        "scheduled", "infrastructure",
    ],
    "WEATHER": [
        "weather", "storm", "snow", "ice", "rain", "wind", "fog",
        "blizzard", "hurricane", "flooding",
    ],
}

# ─── Alert Text → Delay Type Classification ───────────────────────────────────
ALERT_CLASSIFY_KEYWORDS: Dict[str, List[str]] = {
    "MEDICAL_EMERGENCY": [
        "medical emergency", "medical", "ambulance", "ems", "sick passenger",
        "sick customer", "health emergency",
    ],
    "TECHNICAL_PROBLEM": [
        "signal problem", "signal issue", "equipment problem", "mechanical",
        "disabled train", "power problem", "electrical failure", "circuit",
        "signal failure",
    ],
    "POLICE_ACTIVITY": [
        "police activity", "police investigation", "law enforcement",
        "suspicious package", "security incident",
    ],
    "ACCIDENT": ["accident", "collision", "struck by"],
    "MAINTENANCE": [
        "shuttle buses", "shuttle service", "track work", "maintenance",
        "planned", "scheduled", "infrastructure upgrade",
    ],
    "WEATHER": ["weather", "storm", "snow", "ice", "flooding", "wind"],
}

# Duration / "how long" query signals
DURATION_KEYWORDS = [
    "how long", "how much time", "how many minutes", "duration",
    "take to resolve", "take to fix", "last", "how long does",
    "time does", "time do", "how long do",
]

# ─── Pydantic Models ──────────────────────────────────────────────────────────
class A2AMessage(BaseModel):
    type: str
    payload: Dict[str, Any]
    metadata: Dict[str, Any] = {}


# ─── Helper Functions ─────────────────────────────────────────────────────────

def parse_route_from_query(query: str) -> Optional[str]:
    """Extract MBTA route from user query."""
    q = query.lower()
    mapping = {
        "red line": "Red", "red": "Red",
        "orange line": "Orange", "orange": "Orange",
        "blue line": "Blue", "blue": "Blue",
        "green line": "Green", "green": "Green",
        "green-b": "Green-B", "green-c": "Green-C",
        "green-d": "Green-D", "green-e": "Green-E",
        "mattapan": "Mattapan",
        "silver line": "741", "silver": "741",
    }
    for kw, route_id in mapping.items():
        if kw in q:
            return route_id
    return None


def detect_delay_type(query: str) -> Optional[str]:
    """Return the HISTORICAL_PATTERNS key that best matches the user's query."""
    q = query.lower()
    for delay_type, keywords in QUERY_DELAY_KEYWORDS.items():
        for kw in keywords:
            if kw in q:
                return delay_type
    return None


def is_duration_query(query: str) -> bool:
    """Return True if the user is asking how long a delay type typically lasts."""
    q = query.lower()
    return any(kw in q for kw in DURATION_KEYWORDS)


def classify_alert(alert_header: str, alert_desc: str) -> Optional[str]:
    """Classify a live MBTA alert into one of our delay categories."""
    text = ((alert_header or "") + " " + (alert_desc or "")).lower()
    for delay_type, keywords in ALERT_CLASSIFY_KEYWORDS.items():
        for kw in keywords:
            if kw in text:
                return delay_type
    return None


def format_historical_insight(delay_type: str) -> str:
    """Format a clear, human-readable historical insight block."""
    p = HISTORICAL_PATTERNS.get(delay_type)
    if not p:
        return ""
    return (
        f"\n\n📊 Historical data from {p['sample_size']:,} {p['label']} incidents (MBTA 2020–2023):\n"
        f"  • Typical duration: {p['typical']}\n"
        f"  • Shortest recorded: {p['min']} min  |  Longest: {p['max']} min\n"
        f"  • Average resolution: ~{p['avg']} min\n"
        f"  Note: Times measured from incident start to service resumption."
    )


def answer_duration_question(delay_type: str) -> str:
    """Generate a direct answer to 'how long does X take?' queries."""
    p = HISTORICAL_PATTERNS.get(delay_type)
    if not p:
        return "I don't have specific historical data for that delay type."
    return (
        f"{p['emoji']} **{p['label']} delays** — based on {p['sample_size']:,} real MBTA incidents (2020–2023):\n\n"
        f"  ⏱️  Typical range: **{p['min']}–{p['max']} minutes**\n"
        f"  📌  Median (most common): **{p['median']} minutes**\n"
        f"  📈  Average: **{p['avg']} minutes**\n\n"
        f"What causes this range?\n"
        f"  • {p['description'].capitalize()}.\n"
        f"  • Shortest cases resolve quickly with no secondary issues.\n"
        f"  • Longer cases involve cascading effects, crew repositioning, or waiting for external responders.\n\n"
        f"**Bottom line:** If you're waiting due to a {p['label'].lower()}, expect "
        f"roughly {p['median']}–{p['avg']} minutes in a typical case."
    )


# ─── Core Alerts Fetching ─────────────────────────────────────────────────────

@agentviz.trace(name="AlertsAgent", color="#E74C3C")
def get_alerts(
    route: Optional[str] = None,
    activity: Optional[str] = None,
    target_delay_type: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Fetch real-time alerts from MBTA API and enrich with historical context.

    When target_delay_type is provided, active alerts are classified and
    filtered/highlighted for that type, and historical duration data is appended.
    """
    try:
        params = {"api_key": MBTA_API_KEY}
        if route:
            params["filter[route]"] = route
        if activity:
            params["filter[activity]"] = activity

        log.info(f"Fetching alerts from MBTA API (route={route}, target_type={target_delay_type})")
        response = requests.get(f"{MBTA_BASE_URL}/alerts", params=params, timeout=10)
        response.raise_for_status()

        data = response.json()
        alerts = data.get("data", [])
        log.info(f"Found {len(alerts)} total alerts")

        # ── Classify every alert ──────────────────────────────────────────────
        processed_alerts = []
        for alert in alerts[:15]:
            attrs = alert.get("attributes", {})
            header = attrs.get("header") or "Service Alert"
            desc = attrs.get("description") or ""
            classified_type = classify_alert(header, desc)

            processed_alerts.append({
                "id": alert.get("id"),
                "header": header,
                "description": desc,
                "severity": attrs.get("severity", "unknown"),
                "effect": attrs.get("effect", "unknown"),
                "lifecycle": attrs.get("lifecycle", "unknown"),
                "created_at": attrs.get("created_at"),
                "updated_at": attrs.get("updated_at"),
                "classified_type": classified_type,
            })

        # ── Filter for target type if requested ───────────────────────────────
        if target_delay_type:
            matched = [a for a in processed_alerts if a["classified_type"] == target_delay_type]
            p = HISTORICAL_PATTERNS[target_delay_type]

            if matched:
                lines = [
                    f"{p['emoji']} **Active {p['label']} delay detected** "
                    f"({len(matched)} alert{'s' if len(matched) > 1 else ''}):\n"
                ]
                for i, a in enumerate(matched, 1):
                    lines.append(f"{i}. {a['header']}")
                    if a["description"]:
                        lines.append(f"   {a['description'][:200]}")
                text = "\n".join(lines)
                text += format_historical_insight(target_delay_type)
            else:
                text = (
                    f"✅ No active **{p['label'].lower()}** alerts detected on MBTA right now.\n"
                    f"All current service disruptions appear to be of a different type."
                )
                text += format_historical_insight(target_delay_type)

            # Still surface other active alerts briefly
            other = [a for a in processed_alerts if a["classified_type"] != target_delay_type]
            if other:
                text += f"\n\n📋 Other active alerts ({len(other)}):\n"
                for a in other[:3]:
                    text += f"  • {a['header']}\n"
                if len(other) > 3:
                    text += f"  ... and {len(other) - 3} more."

            return {
                "ok": True,
                "count": len(alerts),
                "matched_count": len(matched),
                "alerts": processed_alerts,
                "target_delay_type": target_delay_type,
                "text": text,
                "summary": f"{len(matched)} active {p['label']} alert(s)",
            }

        # ── Generic response with type-annotated alerts ────────────────────────
        if len(alerts) == 0:
            route_text = f"the {route} Line" if route else "any MBTA services"
            return {
                "ok": True,
                "count": 0,
                "alerts": [],
                "text": f"✅ No active alerts for {route_text}. Service is running normally.",
                "summary": "No alerts",
            }

        route_text = f"the {route} Line" if route else "MBTA services"
        severity_emoji = {"10": "🚨", "7": "⚠️", "5": "ℹ️", "3": "ℹ️"}

        lines = [f"Found **{len(alerts)} active alert(s)** for {route_text}:\n"]
        for i, a in enumerate(processed_alerts[:8], 1):
            emoji = severity_emoji.get(str(a["severity"]), "ℹ️")
            type_tag = ""
            if a["classified_type"] and a["classified_type"] in HISTORICAL_PATTERNS:
                hp = HISTORICAL_PATTERNS[a["classified_type"]]
                type_tag = f" [{hp['emoji']} {hp['label']}]"
            lines.append(f"{i}. {emoji} {a['header']}{type_tag}")

        if len(alerts) > 8:
            lines.append(f"\n... and {len(alerts) - 8} more alerts.")

        # Summarise types found
        type_counts: Dict[str, int] = {}
        for a in processed_alerts:
            t = a["classified_type"] or "UNKNOWN_CAUSE"
            type_counts[t] = type_counts.get(t, 0) + 1

        if type_counts:
            lines.append("\n\n🗂️ Delay type breakdown:")
            for t, cnt in sorted(type_counts.items(), key=lambda x: -x[1]):
                hp = HISTORICAL_PATTERNS.get(t)
                if hp:
                    lines.append(f"  {hp['emoji']} {hp['label']}: {cnt}  ({hp['typical']})")

        return {
            "ok": True,
            "count": len(alerts),
            "alerts": processed_alerts,
            "text": "\n".join(lines),
            "summary": f"{len(alerts)} active alerts",
        }

    except requests.exceptions.RequestException as e:
        log.error(f"MBTA API request failed: {e}")
        return {
            "ok": False,
            "error": str(e),
            "text": "Sorry, I couldn't retrieve alerts at this time. Please try again later.",
        }
    except Exception as e:
        log.error(f"Unexpected error in get_alerts: {e}")
        return {"ok": False, "error": str(e), "text": "An unexpected error occurred."}


# ─── REST Endpoints ───────────────────────────────────────────────────────────

@app.get("/health")
def health():
    # load_percent used by ANS health checker for dynamic TTL
    try:
        import psutil
        cpu = psutil.cpu_percent(interval=0.1)
        load_percent = round(min(cpu * 1.5, 100.0), 1)
    except Exception:
        load_percent = 50.0
    status = "healthy" if load_percent < 75 else "degraded"
    return {
        "ok": True,
        "status": status,
        "service": "mbta-alerts-agent",
        "agent_id": os.getenv("AGENT_ID", "mbta-alerts"),
        "version": "2.0.0",
        "load_percent": load_percent,
        "historical_patterns": len(HISTORICAL_PATTERNS),
        "total_incidents_analyzed": 41970,
        "mbta_api_configured": MBTA_API_KEY is not None,
    }


@app.get("/alerts")
def get_alerts_endpoint(
    route: Optional[str] = Query(None),
    activity: Optional[str] = Query(None),
    delay_type: Optional[str] = Query(None),
):
    try:
        return get_alerts(route=route, activity=activity, target_delay_type=delay_type)
    except Exception as e:
        log.error(f"Error in /alerts endpoint: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/historical/{delay_type}")
def get_historical(delay_type: str):
    """Return historical statistics for a specific delay type."""
    key = delay_type.upper()
    if key not in HISTORICAL_PATTERNS:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown delay type. Valid types: {list(HISTORICAL_PATTERNS.keys())}"
        )
    return {"delay_type": key, "data": HISTORICAL_PATTERNS[key]}


# ─── A2A Endpoint ─────────────────────────────────────────────────────────────

@app.post("/a2a/message")
async def a2a_message(message: A2AMessage):
    """
    Agent-to-agent protocol endpoint.
    Handles delay-type queries, duration questions, and general alert queries.
    """
    log.info(f"Received A2A message: type={message.type}")

    try:
        if message.type != "request":
            return {
                "type": "error",
                "payload": {"error": f"Unsupported message type: {message.type}",
                            "text": "This agent only supports 'request' messages."},
                "metadata": {"status": "error"},
            }

        query = message.payload.get("message", "")
        log.info(f"Processing query: '{query}'")

        # ── 1. Detect delay type the user is asking about ─────────────────────
        target_delay_type = detect_delay_type(query)

        # ── 2. Pure duration question? → Answer from historical data directly ──
        if target_delay_type and is_duration_query(query):
            answer = answer_duration_question(target_delay_type)
            return {
                "type": "response",
                "payload": {
                    "ok": True,
                    "count": 0,
                    "text": answer,
                    "summary": f"Historical data for {HISTORICAL_PATTERNS[target_delay_type]['label']}",
                    "source": "historical_patterns",
                    "delay_type": target_delay_type,
                },
                "metadata": {
                    "status": "success",
                    "agent": "mbta-alerts-agent",
                    "query_type": "duration_lookup",
                    "delay_type": target_delay_type,
                    "timestamp": datetime.now().isoformat(),
                },
            }

        # ── 3. Presence query → Live alerts + historical enrichment ───────────
        route = parse_route_from_query(query)
        result = get_alerts(route=route, target_delay_type=target_delay_type)

        return {
            "type": "response",
            "payload": result,
            "metadata": {
                "status": "success",
                "agent": "mbta-alerts-agent",
                "route_detected": route,
                "delay_type_detected": target_delay_type,
                "timestamp": datetime.now().isoformat(),
            },
        }

    except Exception as e:
        log.error(f"A2A error: {e}")
        return {
            "type": "error",
            "payload": {"error": str(e), "text": "An error occurred while processing your request."},
            "metadata": {"status": "error"},
        }


# ─── MCP Endpoints ────────────────────────────────────────────────────────────

@app.post("/mcp/tools/list")
def mcp_tools_list():
    return {
        "tools": [
            {
                "name": "get_mbta_alerts",
                "description": (
                    "Get real-time MBTA service alerts enriched with historical delay intelligence. "
                    "Supports delay type filtering (medical, technical, weather, police, accident, maintenance) "
                    "and historical duration lookup from 41,970 incidents (2020-2023)."
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "route": {
                            "type": "string",
                            "description": "Optional route filter (Red, Orange, Blue, Green, etc.)",
                            "enum": ["Red", "Orange", "Blue", "Green", "Green-B", "Green-C", "Green-D", "Green-E"],
                        },
                        "delay_type": {
                            "type": "string",
                            "description": "Filter by delay category",
                            "enum": list(HISTORICAL_PATTERNS.keys()),
                        },
                        "duration_lookup": {
                            "type": "boolean",
                            "description": "If true, return only historical duration stats for the delay_type",
                        },
                    },
                },
            }
        ]
    }


@app.post("/mcp/tools/call")
def mcp_tools_call(request: Dict[str, Any]):
    tool_name = request.get("name")
    arguments = request.get("arguments", {})

    if tool_name != "get_mbta_alerts":
        return {"error": f"Unknown tool: {tool_name}"}

    route = arguments.get("route")
    delay_type = arguments.get("delay_type")
    duration_lookup = arguments.get("duration_lookup", False)

    if duration_lookup and delay_type:
        text = answer_duration_question(delay_type.upper())
    else:
        result = get_alerts(route=route, target_delay_type=delay_type.upper() if delay_type else None)
        text = result.get("text", "No alerts information available")

    return {"content": [{"type": "text", "text": text}]}


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "8001"))
    log.info(f"Starting MBTA Alerts Agent v2.0 on port {port}")
    uvicorn.run(app, host="0.0.0.0", port=port)
