"""
StateGraph Orchestrator v4.5 - Semantic Discovery + Domain Expertise
Combines v4.4's complete synthesis with v4.5's registry-side filtering
Production ready for 3 to 1000+ agents
"""

import os
from typing import TypedDict, Annotated, Sequence, Literal, Dict, List, Any, Tuple
from langgraph.graph import StateGraph, END
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage
import operator
from dataclasses import dataclass
import asyncio
import httpx
from opentelemetry import trace
import logging
from urllib.parse import urlparse
from datetime import datetime, timedelta
import json
import re

# Import SLIM client
try:
    from .slim_client import SlimAgentClient
    SLIM_AVAILABLE = True
except ImportError:
    SLIM_AVAILABLE = False
    logger = logging.getLogger(__name__)
    logger.warning("SLIM not available")

# ANS Dynamic Resolution
ANS_ENABLED = os.getenv("ANS_ENABLED", "false").lower() == "true"
try:
    # Try package-relative import first (production), then sys.path fallback (local run)
    try:
        from .resolver_client import ResolverClient, get_urn_for_agent
    except ImportError:
        import sys as _sys, os as _os
        _sys.path.insert(0, _os.path.join(_os.path.dirname(__file__), "..", "..", "prototype"))
        from resolver_client import ResolverClient, get_urn_for_agent
    ANS_AVAILABLE = True
except ImportError:
    ANS_AVAILABLE = False

tracer = trace.get_tracer(__name__)
logger = logging.getLogger(__name__)

# Configuration
REGISTRY_URL = os.getenv("REGISTRY_URL", "http://97.107.132.213:6900")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")

# Caching
_agent_catalog_cache = None
_catalog_cache_time = None
_catalog_cache_ttl = timedelta(minutes=5)
_current_orchestrator = None


# ============================================================================
# STATE
# ============================================================================

class AgentState(TypedDict):
    user_message: str
    conversation_id: str
    intent: str
    confidence: float
    matched_agents: List[str]
    agent_queries: Dict[str, str]
    llm_matching_decision: Dict[str, Any]
    messages: Annotated[Sequence[BaseMessage], operator.add]
    agents_called: List[str]
    agent_responses: List[Dict[str, Any]]
    
    # Parsed values
    origin_text: str
    destination_text: str
    
    # Resolved station names
    resolved_origin: str
    resolved_destination: str
    
    # Disruption tracking + domain analysis
    has_disruptions: bool
    affected_routes: List[str]
    severity_level: str
    alerts_domain_analysis: Dict[str, Any]
    
    final_response: str
    should_end: bool
    routing_decision: str
    
    # NEW: Semantic discovery metadata
    semantic_scores: Dict[str, float]
    discovery_method: str

    # ANS resolution trace (one entry per agent resolved via ANS)
    ans_traces: List[Dict[str, Any]]

    # Firewall gate-zero result — set True when firewall_node blocks before discovery
    firewall_blocked: bool


@dataclass
class AgentConfig:
    name: str
    url: str
    port: int
    description: str
    capabilities: List[str]
    discovered_from_registry: bool = True
    relevance_score: float = 0.0
    resolved_via_ans: bool = False  # True when endpoint came from ANS resolution
    full_proxy_url: str = ""        # Set when ANS returns a proxy URL with a path (e.g. /dans/proxy/planner)
    resolved_protocol: str = ""     # Protocol negotiated by DANS (e.g. "slim", "a2a", "http")
    protocol_metadata: dict = None  # Per-protocol hints from DANS registration


# ============================================================================
# QUERY PARSING (from v4.4)
# ============================================================================

def extract_origin_destination(query: str) -> Dict[str, str]:
    """Extract origin and destination from natural language"""
    q = query.lower()
    result = {"origin": "", "destination": ""}

    # Pattern 1: "I'm at X and need/want to get to Y"
    match = re.search(r"i(?:'m| am) at (.+?) and (?:need to |want to )?get to (.+?)(?:\s+in time|\s+for|\s+\.|$)", q)
    if match:
        result["origin"] = match.group(1).strip()
        result["destination"] = match.group(2).strip()
        logger.info(f"✓ PARSED (pattern 1): origin='{result['origin']}', dest='{result['destination']}'")
        return result

    # Pattern 2a: "from X to Y" — standard order
    match = re.search(r"\bfrom\s+(.+?)\s+to\s+(.+?)(?:\s*,|\s+in time|\s+for|\s+\.|$)", q)
    if match:
        result["origin"] = match.group(1).strip()
        result["destination"] = match.group(2).strip()
        logger.info(f"✓ PARSED (pattern 2a): origin='{result['origin']}', dest='{result['destination']}'")
        return result

    # Pattern 2b: "to X from Y" — reversed order (common in conversational queries)
    match = re.search(r"\bto\s+(.+?)\s+from\s+(.+?)(?:\s*,|\s+in time|\s+for|\s+\.|$)", q)
    if match:
        result["destination"] = match.group(1).strip()
        result["origin"] = match.group(2).strip()
        logger.info(f"✓ PARSED (pattern 2b): origin='{result['origin']}', dest='{result['destination']}'")
        return result

    # Pattern 3: destination only — "go to X" / "get to X"
    match = re.search(r"(?:get |go )?to (.+?)(?:\s+in time|\s+for|\s+\.|$)", q)
    if match:
        result["destination"] = match.group(1).strip()
        logger.info(f"✓ PARSED (pattern 3): dest='{result['destination']}'")
        return result

    logger.warning(f"⚠️ No parse match for: '{query}'")
    return result


def is_likely_station_name(text: str) -> bool:
    """Check if text is likely already an MBTA station name"""
    if not text:
        return False
    
    text_lower = text.strip().lower()
    
    station_indicators = [
        "station", "square", "/mit", "kendall",
        "alewife", "davis", "porter", "harvard", "central",
        "park street", "downtown crossing", "south station",
        "broadway", "andrew", "jfk", "quincy",
        "oak grove", "malden", "wellington", "sullivan",
        "community college", "north station", "haymarket",
        "state", "chinatown", "tufts", "back bay",
        "forest hills", "ruggles",
        "wonderland", "revere", "beachmont", "suffolk downs",
        "airport", "wood island", "aquarium", "government center",
        "lechmere", "science park", "boylston",
        "arlington", "copley", "hynes", "kenmore",
        "blandford", "boston university", "pleasant street",
        "saint paul", "kent street", "st paul", "hawes street",
        "longwood", "brookline village", "brookline hills",
        "beaconsfield", "reservoir", "chestnut hill",
        "newton", "riverside", "heath street",
        "street", "square", "center", "place", "ave"
    ]
    
    if any(indicator in text_lower for indicator in station_indicators):
        logger.info(f"✓ '{text}' looks like a station name (skipping resolution)")
        return True
    
    if len(text.split()) <= 2 and len(text) < 20:
        return False
    
    logger.info(f"✓ '{text}' looks like a landmark (needs resolution)")
    return False


def extract_station_from_stopfinder(text: str) -> str:
    """Extract station name from StopFinder response"""
    match = re.search(r"Found:\s*([^\n]+)", text)
    if match:
        station = match.group(1).strip()
        station = re.sub(r' in [A-Z][a-z]+', '', station)
        station = station.split('\n')[0].split('📍')[0].strip()
        return station
    
    match = re.search(r'^\d+\.\s+([^(♿\n]+)', text, re.MULTILINE)
    if match:
        return match.group(1).strip()
    
    return ""


def extract_alerts_domain_analysis(alerts_response: str) -> Dict[str, Any]:
    """Extract domain analysis from Alerts Agent response"""
    analysis = {
        "has_analysis": False,
        "overall_recommendation": "unknown",
        "affected_routes": [],
        "severity": "unknown",
        "should_avoid_routes": [],
        "delay_impact": "unknown"
    }
    
    if not alerts_response:
        return analysis
    
    is_scheduled = "scheduled" in alerts_response.lower() or "📋" in alerts_response
    
    impact_match = re.search(r"(\d+)-(\d+)\s*minutes?\s*additional", alerts_response.lower())
    if impact_match:
        impact_min = int(impact_match.group(1))
        impact_max = int(impact_match.group(2))
        analysis["delay_impact"] = f"{impact_min}-{impact_max} min"
        
        if impact_max > 20:
            analysis["severity"] = "major"
        else:
            analysis["severity"] = "minor"
    
    for line in ["Red Line", "Orange Line", "Blue Line", "Green Line"]:
        if line in alerts_response:
            analysis["affected_routes"].append(line.split()[0])
    
    if is_scheduled:
        if analysis["severity"] == "minor":
            analysis["should_avoid_routes"] = []
            analysis["overall_recommendation"] = "allow_extra_time"
            logger.info(f"✓ Scheduled work with minor impact - route still usable")
        else:
            analysis["should_avoid_routes"] = analysis["affected_routes"]
            analysis["overall_recommendation"] = "consider_alternative"
            logger.info(f"✓ Major scheduled work - consider alternatives")
    else:
        if "🔴" in alerts_response or "critical" in alerts_response.lower():
            analysis["severity"] = "critical"
            analysis["should_avoid_routes"] = analysis["affected_routes"]
            analysis["overall_recommendation"] = "take_alternative"
        elif "🟠" in alerts_response or "major" in alerts_response.lower():
            analysis["severity"] = "major"
            analysis["should_avoid_routes"] = analysis["affected_routes"]
            analysis["overall_recommendation"] = "take_alternative"
    
    logger.info(f"✓ Context: severity={analysis['severity']}, avoid={analysis['should_avoid_routes']}, impact={analysis['delay_impact']}")
    
    return analysis


# ============================================================================
# REGISTRY + SEMANTIC DISCOVERY (from v4.5)
# ============================================================================

async def validate_registry() -> bool:
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(f"{REGISTRY_URL}/health")
            if r.status_code == 200:
                data = r.json()
                if data.get("semantic_search"):
                    logger.info(f"✅ Registry v{data.get('version', 'unknown')} with semantic search")
                    return True
            return False
    except:
        return False


async def get_agent_catalog() -> List[Dict]:
    """Get full agent catalog"""
    global _agent_catalog_cache, _catalog_cache_time
    
    if _agent_catalog_cache and _catalog_cache_time:
        if datetime.now() - _catalog_cache_time < _catalog_cache_ttl:
            return _agent_catalog_cache
    
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(f"{REGISTRY_URL}/list")
            r.raise_for_status()
            agent_list = r.json()
            
            agents = []
            for aid in agent_list.keys():
                if aid == 'agent_status':
                    continue
                try:
                    ar = await client.get(f"{REGISTRY_URL}/agents/{aid}")
                    if ar.status_code == 200:
                        ad = ar.json()
                        if ad.get("alive"):
                            agents.append(ad)
                except:
                    pass
            
            _agent_catalog_cache = agents
            _catalog_cache_time = datetime.now()
            logger.info(f"✓ Registry: {len(agents)} agents")
            return agents
    except:
        return []


def query_from_intent(intent: str, message: str) -> str:
    """NEW: Convert intent + message into semantic search query"""
    msg_lower = message.lower()
    keywords = []
    
    # Extract station/location keywords
    station_words = []
    for word in msg_lower.split():
        if any(ind in word for ind in ['street', 'square', 'station', 'center', 'copley', 'park', 'harvard']):
            station_words.append(word)
    
    # Extract action verbs
    if any(w in msg_lower for w in ['find', 'locate', 'where']):
        keywords.append('find locate where search')
    
    if intent == "alerts":
        base = "alerts delays disruptions service status real-time monitoring incidents problems"
        for line in ['red', 'orange', 'blue', 'green']:
            if line in msg_lower:
                keywords.append(f"{line} line")
        query = f"{base} {' '.join(keywords)}"
        
    elif intent == "stop_info":
        # CRITICAL: More specific keywords for StopFinder matching
        base = "stops stations find locate search nearby location where address proximity"
        keywords.extend(station_words)
        if 'near' in msg_lower:
            keywords.append('nearby around')
        if 'where' in msg_lower:
            keywords.append('location position')
        query = f"{base} {' '.join(keywords)}"
        
    elif intent == "trip_planning":
        base = "route planning directions trip navigation path travel connections transfers"
        if 'from' in msg_lower or 'to' in msg_lower:
            keywords.append('origin destination from to')
        query = f"{base} {' '.join(keywords)}"
        
    else:
        query = message
    
    logger.info(f"🔍 Semantic query: '{query[:80]}...'")
    return query


async def semantic_discovery_v4(intent: str, message: str, max_results: int = 5) -> Tuple[List[AgentConfig], Dict[str, float]]:
    """
    NEW: Use registry-side semantic search (scales to 1000+ agents)
    Returns: (agent_configs, scores_dict)
    """
    search_query = query_from_intent(intent, message)
    
    logger.info(f"🔍 Semantic v4.5: intent={intent}")
    
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.post(
                f"{REGISTRY_URL}/search/semantic",
                json={
                    "query": search_query,
                    "max_results": max_results,
                    "alive_only": False
                },
                timeout=10.0
            )
            
            if r.status_code == 200:
                data = r.json()
                results = data.get('results', [])
                
                logger.info(f"✅ Registry filtered: {data.get('total_candidates', 0)} → {len(results)} agents")
                
                configs = []
                scores = {}
                
                for agent in results:
                    agent_id = agent.get('agent_id', '')
                    api_url = agent.get('api_url') or agent.get('agent_url', '')
                    relevance = agent.get('relevance_score', 0.0)
                    
                    logger.info(f"   {agent_id}: score={relevance:.2f}")
                    
                    if api_url:
                        try:
                            p = urlparse(api_url if '://' in api_url else f"http://{api_url}")
                            url_scheme = p.scheme or 'http'
                            url_host = p.hostname
                            url_port = p.port if p.port else (443 if url_scheme == 'https' else 80)
                            url = f"{url_scheme}://{url_host}"
                            port = url_port

                            config = AgentConfig(
                                name=agent_id,
                                url=url,
                                port=port,
                                description=agent.get('description', ''),
                                capabilities=agent.get('capabilities', []),
                                discovered_from_registry=True,
                                relevance_score=relevance
                            )
                            
                            configs.append(config)
                            scores[agent_id] = relevance
                            
                        except Exception as e:
                            logger.warning(f"Failed to parse URL for {agent_id}: {e}")
                            continue
                
                return configs, scores
            else:
                logger.warning(f"Registry search returned {r.status_code}")
                return [], {}
                
    except Exception as e:
        logger.warning(f"Semantic discovery failed: {e}, falling back to v4.4 LLM discovery")
        # Fallback to v4.4's LLM-based discovery
        return await semantic_discovery_v44_fallback(message)


async def semantic_discovery_v44_fallback(query: str) -> Tuple[List[AgentConfig], Dict[str, float]]:
    """Fallback to v4.4 LLM-based discovery if registry fails"""
    catalog = await get_agent_catalog()
    if not catalog:
        return [], {}
    
    descriptions = [f"• {a['agent_id']}: {a['description']}" for a in catalog]
    catalog_text = "\n".join(descriptions)
    
    prompt = f"""Match query to relevant agents.

Query: "{query}"

Available Agents:
{catalog_text}

Return JSON: {{"matched_agents": ["id1", "id2"]}}"""
    
    try:
        async with httpx.AsyncClient() as client:
            r = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"},
                json={
                    "model": "gpt-4o-mini",
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.2,
                    "max_tokens": 150,
                    "response_format": {"type": "json_object"}
                },
                timeout=10
            )
            r.raise_for_status()
        
        result = json.loads(r.json()["choices"][0]["message"]["content"])
        matched_ids = result.get("matched_agents", [])
        
        configs = []
        scores = {}
        
        for aid in matched_ids:
            ainfo = next((a for a in catalog if a['agent_id'] == aid), None)
            if ainfo:
                p = urlparse(ainfo['agent_url'])
                scheme = p.scheme or 'http'
                port = p.port if p.port else (443 if scheme == 'https' else 80)
                configs.append(AgentConfig(
                    name=ainfo['agent_id'],
                    url=f"{scheme}://{p.hostname}",
                    port=port,
                    description=ainfo['description'],
                    capabilities=ainfo.get('capabilities', []),
                    relevance_score=1.0
                ))
                scores[aid] = 1.0
        
        logger.info(f"✓ Fallback discovery: {matched_ids}")
        return configs, scores
    except:
        return [], {}


# Fallback configurations (HTTP/A2A ports, not SLIM/gRPC ports)
FALLBACK_AGENTS = {
    "mbta-alerts":     {"url": "http://96.126.111.107", "port": 8001},
    "mbta-stopfinder": {"url": "http://96.126.111.107", "port": 8003},
    "mbta-planner":    {"url": "http://96.126.111.107", "port": 8002},
    "mbta-fares":      {"url": "http://50.116.57.161",  "port": 50054},  # Boston (primary); Frankfurt is ANS failover
}


async def get_agent_config_fallback(agent_name: str) -> AgentConfig:
    """Fallback to hardcoded configuration"""
    fallback_key = agent_name.lower().replace('_', '-')
    
    if fallback_key in FALLBACK_AGENTS:
        config = FALLBACK_AGENTS[fallback_key]
        logger.info(f"📌 Using fallback for {agent_name}: {config['url']}:{config['port']}")
        return AgentConfig(
            name=agent_name,
            url=config['url'],
            port=config['port'],
            description="",
            capabilities=[],
            discovered_from_registry=False
        )
    
    logger.warning(f"⚠️  No discovery or fallback for {agent_name}")
    return AgentConfig(
        name=agent_name,
        url="http://localhost",
        port=8001,
        description="",
        capabilities=[],
        discovered_from_registry=False
    )


# ============================================================================
# AGENT COMMUNICATION (from v4.4)
# ============================================================================

async def call_agent_slim(slim_client, config: AgentConfig, msg: str) -> Dict:
    agent_map = {
        "mbta-alerts":       "alerts",
        "mbta-planner":      "planner",
        "mbta-route-planner":"planner",
        "mbta-stops":        "stopfinder",
        "mbta-stopfinder":   "stopfinder",
        "mbta-fares":        "fares",
        "mbta-fares-boston": "fares",
    }

    name = agent_map.get(config.name)
    if not name:
        raise ValueError(f"No SLIM mapping: {config.name}")

    # If the config carries an ANS-resolved URL, pass it through so the slim
    # client calls the dynamically-selected endpoint (Boston vs Frankfurt)
    # rather than the static AGENT_ENDPOINTS fallback.
    resolved_url = None
    if getattr(config, "resolved_via_ans", False) and config.url and config.port:
        resolved_url = f"{config.url}:{config.port}"

    return await slim_client.call_agent(name, msg, base_url=resolved_url)


async def call_agent_http(config: AgentConfig, msg: str, conv_id: str) -> Dict:
    """
    Call an agent over HTTP/A2A.

    Supports two payload formats:
    - Custom format  (alerts/planner/stopfinder): POST /a2a/message  {type, payload, metadata}
    - Google A2A     (fares):                     POST /             {jsonrpc, method, params}

    The format is selected from config.protocol_metadata["a2a"]["format"].
    Defaults to "custom" for backward compatibility with existing agents.
    """
    import uuid as _uuid

    # ── Determine endpoint path ────────────────────────────────────────────────
    # Read path and format from protocol_metadata if available.
    #
    # DANS /resolve returns a flat dict for the selected protocol:
    #   {"version": "0.2.1", "path": "/", "format": "google_a2a"}
    #
    # Agent registration may nest by protocol name:
    #   {"a2a": {"version": "0.2.1", ...}, "http": {...}}
    #
    # Handle both by checking for the resolved protocol key first,
    # then falling back to the flat dict.
    _meta_path = ""
    _proto_format = "custom"
    if getattr(config, "protocol_metadata", None):
        _pm = config.protocol_metadata
        _proto_key = (getattr(config, "resolved_protocol", "") or "a2a").lower()
        # Try nested format (e.g. {"a2a": {...}}) first; fall back to flat dict
        _a2a_meta = _pm.get(_proto_key) or _pm
        _meta_path    = _a2a_meta.get("path", "")
        _proto_format = _a2a_meta.get("format", "custom")

    if getattr(config, 'full_proxy_url', ''):
        # ANS returned a DANS proxy URL — append the agent's declared path
        _agent_path = _meta_path if _meta_path else "/a2a/message"
        # Normalise: proxy URL already ends without slash; path must start with /
        if not _agent_path.startswith("/"):
            _agent_path = "/" + _agent_path
        url = config.full_proxy_url.rstrip('/') + _agent_path
        logger.info(f"📌 Using DANS proxy URL: {url} (format={_proto_format})")
    else:
        # Non-ANS path — reconstruct from host + port
        SLIM_TO_HTTP_PORT = {50051: 8001, 50052: 8002, 50053: 8003, 50054: 50054}
        actual_port = config.port
        if getattr(config, 'resolved_via_ans', False) and config.port in SLIM_TO_HTTP_PORT:
            actual_port = SLIM_TO_HTTP_PORT[config.port]
            logger.info(f"📌 HTTP fallback: SLIM port {config.port} → HTTP port {actual_port}")

        scheme = config.url.split("://")[0] if "://" in config.url else "http"
        is_standard_port = (scheme == "https" and actual_port == 443) or (scheme == "http" and actual_port == 80)
        _base = config.url if is_standard_port else f"{config.url}:{actual_port}"
        _agent_path = _meta_path if _meta_path else "/a2a/message"
        if not _agent_path.startswith("/"):
            _agent_path = "/" + _agent_path
        url = _base + _agent_path

    # ── Build payload ──────────────────────────────────────────────────────────
    if _proto_format == "google_a2a":
        # Proper Google A2A JSON-RPC (used by fares agent and any real A2A agent)
        payload = {
            "jsonrpc": "2.0",
            "method":  "message/send",
            "params": {
                "message": {
                    "messageId": str(_uuid.uuid4()),
                    "role":  "user",
                    "parts": [{"type": "text", "text": msg}],
                }
            },
            "id": 1,
        }
    else:
        # Custom format used by alerts / planner / stopfinder
        payload = {
            "type": "request",
            "payload": {"message": msg, "conversation_id": conv_id},
            "metadata": {"source": "stategraph-v45"},
        }

    async with httpx.AsyncClient(timeout=15.0) as client:
        r = await client.post(url, json=payload)
        # Firewall block — surface as a distinct sentinel, not a generic error
        if r.status_code == 403:
            detail = {}
            try:
                detail = r.json()
            except Exception:
                pass
            reason = detail.get("reason", "firewall")
            logger.warning(f"🛡️ DANS Firewall blocked call to {config.name}: {reason}")
            return {
                "firewall_blocked": True,
                "reason": reason,
                "response": "🛡️ Request blocked by DANS Firewall",
                "agent_used": config.name,
            }
        r.raise_for_status()
        result = r.json()

        # ── Parse response ─────────────────────────────────────────────────────
        if _proto_format == "google_a2a":
            # Google A2A response: {jsonrpc, id, result: {kind, parts: [{type, text}]}}
            _rparts = result.get("result", {}).get("parts", [])
            _text = " ".join(
                p.get("text", "") for p in _rparts if p.get("type") == "text" or p.get("kind") == "text"
            )
            return {"response": _text, "agent_used": config.name}

        # Custom format response
        if result.get("type") == "response" and "payload" in result:
            return {"response": result["payload"].get("text", ""), "agent_used": config.name}
        return result


async def call_stopfinder_for_location(location: str, config: AgentConfig, conv_id: str) -> str:
    """Call StopFinder and extract station name.

    Uses DANS-negotiated protocol (config.resolved_protocol) when available;
    falls back to the global USE_SLIM flag for non-ANS paths.
    """
    if not location:
        return ""

    query = f"Find station: {location}"

    global _current_orchestrator

    try:
        # Prefer DANS-negotiated protocol; fall back to global flag
        _proto = getattr(config, "resolved_protocol", "").lower()
        _use_slim = (
            _proto == "slim"
            or (not _proto and _current_orchestrator and _current_orchestrator.use_slim)
        )
        if _use_slim and _current_orchestrator and _current_orchestrator.slim_client:
            logger.info(f"   StopFinder location resolve via SLIM (proto={_proto or 'global_flag'})")
            try:
                result = await call_agent_slim(_current_orchestrator.slim_client, config, query)
            except Exception:
                logger.info("   StopFinder SLIM failed, falling back to HTTP")
                result = await call_agent_http(config, query, conv_id)
        else:
            logger.info(f"   StopFinder location resolve via HTTP (proto={_proto or 'http'})")
            result = await call_agent_http(config, query, conv_id)

        response_text = result.get("response", "")
        station = extract_station_from_stopfinder(response_text)

        logger.info(f"   '{location}' → '{station}'")
        return station

    except Exception as e:
        logger.error(f"StopFinder error for '{location}': {e}")
        return ""


# ============================================================================
# NODES
# ============================================================================

def route_after_firewall(state: AgentState) -> str:
    """Kept for graph compatibility — firewall enforcement is handled by DANS proxy layer."""
    if state.get("firewall_blocked"):
        return "synthesize"
    return "discovery"


async def discovery_node(state: AgentState) -> AgentState:
    """Semantic agent discovery using registry-side filtering"""
    with tracer.start_as_current_span("semantic_discovery_v45"):
        # Infer initial intent — trip_planning takes precedence over alerts when
        # the message has an origin/destination pattern (navigation beats status check)
        msg = state["user_message"].lower()

        has_fares = any(w in msg for w in [
            "fare", "fares", "price", "prices", "cost", "how much", "ticket", "tickets",
            "pay", "charliecard", "monthly pass", "accessibility", "wheelchair",
            "the ride", "paratransit", "disabled", "senior", "reduced",
            "commuter rail ticket", "commuter rail fare", "ferry fare", "bus fare",
            "subway fare", "mbta history", "founded", "oldest subway",
        ])
        has_navigation = (
            not has_fares  # fares queries containing "from X to Y" must not be hijacked by trip_planning
            and any(w in msg for w in ["from", "to ", "get to", "route", "directions", "travel", "go to", "heading to"])
            and any(w in msg for w in ["from", "get to", "go to", "heading"])
        )
        has_alerts = any(w in msg for w in ["delay", "alert", "issue", "problem", "disruption", "status"])

        # Priority: fares > navigation > alerts > stop_info > general
        if has_fares:
            initial_intent = "fares"
        elif has_navigation:
            initial_intent = "trip_planning"
        elif has_alerts:
            initial_intent = "alerts"
        elif any(w in msg for w in ["stop", "station", "find", "near", "where is", "locate"]):
            initial_intent = "stop_info"
        else:
            initial_intent = "general"
        
        # Use registry semantic search
        matched_configs, scores = await semantic_discovery_v4(initial_intent, state["user_message"], max_results=5)

        CORE_AGENTS = {"mbta-alerts", "mbta-planner", "mbta-stopfinder", "mbta-route-planner", "mbta-stops", "mbta-fares"}
        # Keep all returned agents but put core MBTA agents first so routing logic finds them
        core = [c.name for c in matched_configs if c.name in CORE_AGENTS]
        other = [c.name for c in matched_configs if c.name not in CORE_AGENTS]
        matched_ids = core + other

        # Fallback: if semantic search returned no CORE agents for a known intent, use defaults
        if not core:
            logger.warning(f"⚠️ Semantic search returned 0 results for intent={initial_intent} — using fallback agents")
            if initial_intent == "alerts":
                matched_ids = ["mbta-alerts"]
            elif initial_intent == "stop_info":
                matched_ids = ["mbta-stopfinder"]
            elif initial_intent == "trip_planning":
                matched_ids = ["mbta-alerts", "mbta-planner"]
            elif initial_intent == "fares":
                matched_ids = ["mbta-fares"]
            # scores stay empty; execute_agents_node will use get_agent_config_fallback

        # Only refine intent from agent descriptions when keyword detection was inconclusive
        intent = initial_intent
        conf = 0.85 if matched_ids else 0.5

        if initial_intent == "general" and matched_configs:
            first = matched_configs[0]
            d = first.description.lower() if first.description else ""

            if any(w in d for w in ["route", "plan", "trip"]):
                intent, conf = "trip_planning", 0.85
            elif any(w in d for w in ["alert", "delay"]):
                intent, conf = "alerts", 0.85
            elif any(w in d for w in ["stop", "station"]):
                intent, conf = "stop_info", 0.85
            else:
                conf = 0.5
        
        parsed = extract_origin_destination(state["user_message"])
        
        logger.info(f"✓ Semantic discovery: {len(matched_ids)} agents, intent={intent}")
        
        return {
            **state,
            "matched_agents": matched_ids,
            "intent": intent,
            "confidence": conf,
            "origin_text": parsed["origin"],
            "destination_text": parsed["destination"],
            "agent_queries": {},
            "agents_called": [],
            "agent_responses": [],
            "messages": [HumanMessage(content=state["user_message"])],
            "llm_matching_decision": {"matched_agents": matched_ids, "scores": scores},
            "resolved_origin": "",
            "resolved_destination": "",
            "has_disruptions": False,
            "affected_routes": [],
            "severity_level": "none",
            "alerts_domain_analysis": {},
            "routing_decision": "",
            "semantic_scores": scores,
            "discovery_method": "semantic_v45"
        }


def routing_node(state: AgentState) -> AgentState:
    """Intelligent routing decision (from v4.4)"""
    intent = state["intent"]
    matched = state.get("matched_agents", [])

    # Only ever call core MBTA agents — filter out unrelated agents from semantic search
    CORE_AGENTS = {"mbta-alerts", "mbta-planner", "mbta-stopfinder", "mbta-route-planner", "mbta-stops", "mbta-fares"}
    core_matched = [a for a in matched if a in CORE_AGENTS]

    logger.info(f"🎯 Routing: {intent}, core agents: {core_matched}")

    if intent == "trip_planning":
        # FULL_CHAIN: stopfinder (if landmark needed) → alerts → planner
        ordered = []
        for a in core_matched:
            if "stopfinder" in a or "stops" in a:
                ordered.append(a)
                break
        if not any("alerts" in a for a in ordered):
            ordered.append("mbta-alerts")
        for a in core_matched:
            if "planner" in a or "route" in a:
                ordered.append(a)
                break
        if not any("planner" in a or "route" in a for a in ordered):
            ordered.append("mbta-planner")
        state["matched_agents"] = list(dict.fromkeys(ordered))
        state["routing_decision"] = "FULL_CHAIN"
        logger.info(f"✓ Chain: {' → '.join(state['matched_agents'])}")

    elif intent == "alerts":
        # Alerts-only: only mbta-alerts, no planner
        state["matched_agents"] = ["mbta-alerts"] if any("alert" in a for a in core_matched) else core_matched[:1]
        state["routing_decision"] = "ALERTS_ONLY"
        logger.info(f"✓ Alerts only: {state['matched_agents']}")

    elif intent == "stop_info":
        # Stop info: only stopfinder
        sf = [a for a in core_matched if "stopfinder" in a or "stops" in a]
        state["matched_agents"] = sf if sf else (["mbta-stopfinder"] if not core_matched else core_matched[:1])
        state["routing_decision"] = "STOP_ONLY"
        logger.info(f"✓ Stop only: {state['matched_agents']}")

    elif intent == "fares":
        # Fares: route to mbta-fares agent (Frankfurt)
        fares = [a for a in core_matched if "fares" in a]
        state["matched_agents"] = fares if fares else ["mbta-fares"]
        state["routing_decision"] = "FARES_ONLY"
        logger.info(f"✓ Fares: {state['matched_agents']}")

    else:
        # General: use top core agent only
        state["matched_agents"] = core_matched[:1] if core_matched else matched[:1]
        state["routing_decision"] = "SINGLE"
        logger.info(f"✓ Single: {state['matched_agents']}")

    return state


async def execute_agents_node(state: AgentState) -> AgentState:
    """Execute agents (v4.4 logic with v4.5 config handling)"""
    with tracer.start_as_current_span("execute_agents"):
        matched = state.get("matched_agents", [])
        if not matched:
            return {**state, "agents_called": [], "agent_responses": []}
        
        global _current_orchestrator
        
        # Get agent configurations
        agent_configs = {}
        
        # Build agent configs from catalog (with HTTPS-aware URL parsing)
        catalog = await get_agent_catalog()
        scores = state.get("semantic_scores") or {}
        ans_traces: List[Dict[str, Any]] = list(state.get("ans_traces") or [])

        for agent_id in matched:
            # ── ANS Dynamic Resolution path ───────────────────────────────
            ans_resolved = False
            if (
                _current_orchestrator
                and getattr(_current_orchestrator, "use_ans", False)
                and getattr(_current_orchestrator, "resolver_client", None)
            ):
                urn = get_urn_for_agent(agent_id)
                if urn:
                    with tracer.start_as_current_span(f"ans_resolve_{agent_id}") as span:
                        span.set_attribute("ans.urn", urn)
                        resolved = await _current_orchestrator.resolver_client.resolve(urn)
                        if resolved:
                            p = urlparse(resolved.endpoint_url)
                            scheme = p.scheme or 'http'
                            port = p.port if p.port else (443 if scheme == 'https' else 80)
                            # If the resolved URL has a path (e.g. /dans/proxy/planner),
                            # preserve the full URL so call_agent_http can use it directly.
                            has_path = bool(p.path and p.path not in ("", "/"))
                            agent_configs[agent_id] = AgentConfig(
                                name=agent_id,
                                url=f"{scheme}://{p.hostname}",
                                port=port,
                                description="",
                                capabilities=[],
                                discovered_from_registry=True,
                                relevance_score=scores.get(agent_id, 0.0),
                                resolved_via_ans=True,
                                full_proxy_url=resolved.endpoint_url if has_path else "",
                                resolved_protocol=resolved.protocol,
                                protocol_metadata=getattr(resolved, "protocol_metadata", {}) or {},
                            )
                            span.set_attribute("ans.endpoint", resolved.endpoint_url)
                            span.set_attribute("ans.cached", resolved.cached)
                            span.set_attribute("ans.latency_ms", resolved.latency_ms)
                            logger.info(
                                f"✅ ANS resolved {agent_id} → {resolved.endpoint_url} "
                                f"(cached={resolved.cached}, {resolved.latency_ms:.1f}ms)"
                            )
                            # Record trace for UI display
                            _local_ips = {"96.126.111.107","50.116.53.133","97.107.132.213","66.228.45.25","50.116.57.161"}
                            _ep_host = resolved.endpoint_url.replace("http://","").replace("https://","").split(":")[0].split("/")[0]
                            _is_foreign = _ep_host not in _local_ips
                            # Pull geo + candidate data from resolver metadata if available
                            _meta = getattr(resolved, "metadata", {}) or {}
                            _trace: Dict[str, Any] = {
                                "agent_id": agent_id,
                                "urn": urn,
                                "endpoint": resolved.endpoint_url,
                                "protocol": resolved.protocol,
                                "negotiated_by": getattr(resolved, "negotiated_by", "unknown"),
                                "protocol_metadata": getattr(resolved, "protocol_metadata", {}),
                                "fallback_protocol": getattr(resolved, "fallback_protocol", ""),
                                "cached": resolved.cached,
                                "latency_ms": round(resolved.latency_ms, 1),
                                "is_foreign": _is_foreign,
                                "selected_by": _meta.get("selected_by", "ans"),
                                "region": _meta.get("region", ""),
                                "region_label": _meta.get("region_label", ""),
                                "flag": _meta.get("flag", ""),
                                "candidates": _meta.get("all_candidates", []),
                            }
                            ans_traces.append(_trace)
                            ans_resolved = True

            # ── Registry / fallback path (original logic, unchanged) ──────
            if not ans_resolved:
                ainfo = next((a for a in catalog if a['agent_id'] == agent_id), None)
                if ainfo:
                    p = urlparse(ainfo['agent_url'])
                    scheme = p.scheme or 'http'
                    port = p.port if p.port else (443 if scheme == 'https' else 80)
                    agent_configs[agent_id] = AgentConfig(
                        name=ainfo['agent_id'],
                        url=f"{scheme}://{p.hostname}",
                        port=port,
                        description=ainfo.get('description', ''),
                        capabilities=ainfo.get('capabilities', []),
                        discovered_from_registry=True,
                        relevance_score=scores.get(agent_id, 0.0)
                    )
                else:
                    agent_configs[agent_id] = await get_agent_config_fallback(agent_id)

                # ── Add ANS trace for ALL agents (fallback path) so the UI panel
                #    is always populated.  Foreign agents get geo metadata. ──────
                _KNOWN_LOCAL_IPS = {
                    "96.126.111.107", "50.116.53.133",
                    "97.107.132.213", "66.228.45.25", "50.116.57.161",
                }
                _FOREIGN_GEO: Dict[str, Dict[str, str]] = {
                    "85.90.246.180": {
                        "region": "eu-central",
                        "region_label": "Frankfurt, DE",
                        "flag": "\U0001f1e9\U0001f1ea",
                        "reason": "Specialized fare & accessibility data · GDPR-compliant EU node",
                    },
                }
                cfg = agent_configs.get(agent_id)
                if cfg:
                    endpoint_url = f"{cfg.url}:{cfg.port}"
                    urn = get_urn_for_agent(agent_id) or f"urn:agents.dataworksai.com:mbta-transit-ci:{agent_id.replace('mbta-','')}"
                    host_ip = cfg.url.replace("http://", "").replace("https://", "").split(":")[0]
                    is_foreign = host_ip not in _KNOWN_LOCAL_IPS
                    geo = _FOREIGN_GEO.get(host_ip, {})
                    trace_entry: Dict[str, Any] = {
                        "agent_id": agent_id,
                        "urn": urn,
                        "endpoint": endpoint_url,
                        "protocol": "A2A",
                        "cached": False,
                        "latency_ms": 0.0,
                        "is_foreign": is_foreign,
                    }
                    if geo:
                        trace_entry.update(geo)
                    ans_traces.append(trace_entry)
        
        # SPECIAL CASE: stop_info — call StopFinder directly with full query, skip origin/dest logic
        if state.get("intent") == "stop_info":
            sf_id = next((a for a in matched if "stopfinder" in a or "stops" in a), None)
            if sf_id and sf_id in agent_configs:
                config = agent_configs[sf_id]
                logger.info(f"📍 stop_info: calling {sf_id} directly with full query")
                try:
                    _sf_proto = getattr(config, "resolved_protocol", "").lower()
                    _sf_slim = (
                        _sf_proto == "slim"
                        or (not _sf_proto and _current_orchestrator and _current_orchestrator.use_slim)
                    )
                    if _sf_slim and _current_orchestrator and _current_orchestrator.slim_client:
                        try:
                            result = await call_agent_slim(_current_orchestrator.slim_client, config, state["user_message"])
                        except:
                            result = await call_agent_http(config, state["user_message"], state["conversation_id"])
                    else:
                        result = await call_agent_http(config, state["user_message"], state["conversation_id"])
                    logger.info(f"✅ stop_info StopFinder succeeded")
                    return {
                        **state,
                        "agent_responses": [result],
                        "agents_called": [sf_id],
                        "resolved_origin": "",
                        "resolved_destination": "",
                        "has_disruptions": False,
                        "affected_routes": [],
                        "severity_level": "none",
                        "alerts_domain_analysis": {},
                        "ans_traces": ans_traces,   # ← was missing: ANS panel stayed blank for stop_info queries
                        "messages": [AIMessage(content=result.get("response", "")[:100], name=sf_id)]
                    }
                except Exception as e:
                    logger.error(f"❌ stop_info StopFinder failed: {e}")
            return {**state, "agent_responses": [], "agents_called": [], "resolved_origin": "",
                    "ans_traces": ans_traces,
                    "resolved_destination": "", "has_disruptions": False, "affected_routes": [],
                    "severity_level": "none", "alerts_domain_analysis": {}, "messages": []}

        responses = []
        agents_called = []

        origin = state.get("origin_text", "")
        destination = state.get("destination_text", "")
        
        logger.info(f"🔄 Execute: {' → '.join(matched)}")
        logger.info(f"   Origin: '{origin}', Dest: '{destination}'")
        
        origin_is_station = is_likely_station_name(origin)
        dest_is_station = is_likely_station_name(destination)
        
        logger.info(f"   Origin is station: {origin_is_station}, Dest is station: {dest_is_station}")
        
        resolved_origin = ""
        resolved_destination = ""
        
        # Find StopFinder
        stopfinder_id = None
        for aid in matched:
            if "stopfinder" in aid or "stops" in aid:
                stopfinder_id = aid
                break
        
        # Resolve with StopFinder if needed
        if stopfinder_id and stopfinder_id in agent_configs:
            if not origin_is_station or not dest_is_station:
                sf_config = agent_configs[stopfinder_id]
                
                logger.info(f"📍 Resolving landmarks with StopFinder...")
                
                if origin and not origin_is_station:
                    logger.info(f"   Resolving origin: '{origin}'")
                    resolved_origin = await call_stopfinder_for_location(origin, sf_config, state["conversation_id"])
                elif origin:
                    logger.info(f"   Skipping origin (already station): '{origin}'")
                    resolved_origin = origin
                
                if destination and not dest_is_station:
                    logger.info(f"   Resolving destination: '{destination}'")
                    resolved_destination = await call_stopfinder_for_location(destination, sf_config, state["conversation_id"])
                elif destination:
                    logger.info(f"   Skipping destination (already station): '{destination}'")
                    resolved_destination = destination
                
                logger.info(f"✓ Final: '{resolved_origin or origin}' → '{resolved_destination or destination}'")

                # Track StopFinder in agents_called (for visualization) with a preprocessing
                # marker so synthesis can skip it when building actual responses
                if (origin and not origin_is_station) or (destination and not dest_is_station):
                    agents_called.append(stopfinder_id)
                    responses.append({
                        "response": f"Resolved: {resolved_origin or origin} → {resolved_destination or destination}",
                        "agent_used": stopfinder_id,
                        "preprocessing": True
                    })
        else:
            resolved_origin = origin
            resolved_destination = destination
            logger.info(f"✓ Using as-is: '{origin}' → '{destination}'")
        
        # Execute remaining agents — alerts + planner run in PARALLEL via asyncio.gather().
        # The synthesize_node already receives all responses and combines them, so the
        # synthesizer applies disruption context at the end regardless of execution order.
        has_disruptions = False
        affected = []
        severity = "none"
        alerts_analysis = {}

        import re as _re

        # ── Build per-agent queries up-front (no cross-agent dependencies needed) ──
        agent_task_list = []  # [(agent_id, config, query)]

        for agent_id in matched:
            if agent_id == stopfinder_id:
                continue
            if agent_id not in agent_configs:
                logger.warning(f"No config for {agent_id}")
                continue

            config = agent_configs[agent_id]

            if agent_id == "mbta-alerts":
                if state.get("intent") == "trip_planning":
                    from_s = resolved_origin or origin
                    to_s = resolved_destination or destination
                    if from_s and to_s:
                        trip_ctx = (
                            f"\n\nTrip context: Planning a journey from '{from_s}' to '{to_s}'. "
                            "Should I wait for any delays to clear or take an alternative route? "
                            "Please include estimated delay duration using historical data."
                        )
                    else:
                        trip_ctx = (
                            "\n\nShould I wait for any current delays or take an alternative route? "
                            "Please include delay duration estimates using historical data."
                        )
                    agent_query = state["user_message"] + trip_ctx
                else:
                    agent_query = state["user_message"]

            elif agent_id in ["mbta-planner", "mbta-route-planner"]:
                from_station = resolved_origin if resolved_origin else origin
                to_station = resolved_destination if resolved_destination else destination

                user_msg_lower = state["user_message"].lower()
                wants_multiple = (
                    any(word in user_msg_lower for word in [
                        "two route", "multiple route", "give me two", "give me multiple",
                        "show me options", "give me options", "different routes",
                        "compare routes", "2 route", "3 route", "alternate route",
                        "alternative route", "options", "2 options", "3 options"
                    ])
                    or bool(_re.search(r"\b[2-5]\s*(route|option|way|path|alternative)", user_msg_lower))
                )

                if from_station and to_station:
                    if wants_multiple:
                        agent_query = f"""IMPORTANT: Plan route using these EXACT station names.

Origin: {from_station}
Destination: {to_station}

Provide TWO or MORE different route options. For each:
- Transfer stations
- Lines used
- Estimated time
- Number of stops

Rank by reliability if disruptions exist, or by speed if no disruptions."""
                    else:
                        agent_query = f"""IMPORTANT: Plan route using these EXACT station names.

Origin: {from_station}
Destination: {to_station}

Plan the route between these stations."""
                elif to_station:
                    agent_query = f"Find routes to {to_station}"
                else:
                    agent_query = state["user_message"]

            else:
                agent_query = state["user_message"]

            agent_task_list.append((agent_id, config, agent_query))

        # Firewall enforcement is handled by the DANS proxy layer.
        # When agent calls go through /dans/proxy/<label>, DANS checks firewall rules
        # and returns 403 if blocked. call_agent_http() handles 403 responses.

        # ── Run all agents concurrently ──────────────────────────────────────────
        async def _run_one(agent_id: str, config, agent_query: str):
            with tracer.start_as_current_span(f"agent_{agent_id}"):
                # Use protocol negotiated by DANS (stored in config.resolved_protocol).
                # Fall back to global use_slim flag for non-ANS paths.
                _resolved_proto = getattr(config, "resolved_protocol", "").lower()
                _use_slim = (
                    _resolved_proto == "slim"
                    or (
                        not _resolved_proto
                        and _current_orchestrator
                        and _current_orchestrator.use_slim
                    )
                )
                if _use_slim and _current_orchestrator and _current_orchestrator.slim_client:
                    try:
                        logger.info(f"🔀 {agent_id}: using SLIM (protocol={_resolved_proto or 'global_flag'})")
                        result = await call_agent_slim(_current_orchestrator.slim_client, config, agent_query)
                    except Exception:
                        logger.info(f"⬇️  {agent_id}: SLIM failed, falling back to HTTP")
                        result = await call_agent_http(config, agent_query, state["conversation_id"])
                        _resolved_proto = "http"  # reflect actual protocol used after fallback
                else:
                    logger.info(f"🔀 {agent_id}: using HTTP (protocol={_resolved_proto or 'http'})")
                    result = await call_agent_http(config, agent_query, state["conversation_id"])
                # Tag every result with the protocol that was actually used so the
                # synthesize/UI layers can surface it without digging into ANS traces.
                if isinstance(result, dict) and "protocol_used" not in result:
                    result["protocol_used"] = _resolved_proto or ("slim" if _use_slim else "http")
                return result

        logger.info(f"⚡ Running {len(agent_task_list)} agents in parallel: {[t[0] for t in agent_task_list]}")

        raw_results = await asyncio.gather(
            *[_run_one(aid, cfg, q) for aid, cfg, q in agent_task_list],
            return_exceptions=True,
        )

        # ── Post-process results (preserving original ordering) ─────────────────
        for (agent_id, _, _), result in zip(agent_task_list, raw_results):
            if isinstance(result, Exception):
                logger.error(f"❌ {agent_id}: {result}")
                responses.append({"response": f"Error: {result}", "error": True})
                agents_called.append(f"{agent_id}_error")
                continue

            # Firewall block from call_agent_http — propagate and stop processing
            if result.get("firewall_blocked"):
                logger.warning(f"🛡️ Agent {agent_id} blocked by firewall: {result.get('reason')}")
                responses.append(result)
                agents_called.append(f"{agent_id}_firewall_block")
                continue

            resp_text = result.get("response", "")

            if agent_id == "mbta-alerts":
                alerts_analysis = extract_alerts_domain_analysis(resp_text)
                if "🔴" in resp_text or "🟠" in resp_text:
                    has_disruptions = True
                    for route in ["Red Line", "Orange Line", "Blue Line", "Green Line"]:
                        if route in resp_text:
                            affected.append(route)
                    severity = "critical" if "🔴" in resp_text else "major"
                    logger.info(f"⚠️ Disruptions: {affected}, severity={severity}")
                else:
                    logger.info(f"✓ No major disruptions")

            responses.append(result)
            agents_called.append(agent_id)
        
        return {
            **state,
            "agent_responses": responses,
            "agents_called": agents_called,
            "resolved_origin": resolved_origin,
            "resolved_destination": resolved_destination,
            "has_disruptions": has_disruptions,
            "affected_routes": affected,
            "severity_level": severity,
            "alerts_domain_analysis": alerts_analysis,
            "ans_traces": ans_traces,
            "messages": [
                AIMessage(content=f"{r.get('agent_used', 'agent')}: {r.get('response', '')[:100]}",
                         name=r.get('agent_used', 'agent'))
                for r in responses if not r.get('error')
            ]
        }


async def synthesize_node(state: AgentState) -> AgentState:
    """Intelligent synthesis (COMPLETE v4.4 logic)"""
    with tracer.start_as_current_span("synthesize"):
        # Fast-path: firewall already set final_response (gate-zero block)
        if state.get("firewall_blocked") and state.get("final_response"):
            return state

        if not state.get("matched_agents"):
            msg = state["user_message"].lower()
            if any(w in msg for w in ["hi", "hello", "hey"]):
                return {**state, "final_response": "Hello! I help with MBTA routes, alerts, and stops. What do you need?", "should_end": True}
            return {**state, "final_response": "I specialize in MBTA transit. Ask about routes, alerts, or stops!", "should_end": True}
        
        # Build response map keyed by agent_used — skip preprocessing entries (StopFinder landmark resolution)
        resp_map = {}
        for r in state.get("agent_responses", []):
            # Firewall block — surface immediately, skip all other processing
            if r.get("firewall_blocked"):
                logger.warning(f"🛡️ Final response: request blocked by firewall ({r.get('reason')})")
                return {**state, "final_response": "🛡️ Request blocked by security policy.", "should_end": True}
            if not r.get("error") and not r.get("preprocessing") and r.get("response"):
                resp_map[r.get("agent_used", "")] = r.get("response", "")

        if not resp_map:
            return {**state, "final_response": "Agents unavailable.", "should_end": True}

        routing = state.get("routing_decision", "")

        alerts_text  = next((v for k, v in resp_map.items() if "alert" in k.lower()), "")
        planner_text = next((v for k, v in resp_map.items() if "planner" in k.lower()), "")
        stop_text    = next((v for k, v in resp_map.items() if "stopfinder" in k.lower() or "stops" in k.lower()), "")

        # Single agent — return directly
        if len(resp_map) == 1:
            only_text = list(resp_map.values())[0]
            only_key  = list(resp_map.keys())[0]
            if "planner" in only_key:
                logger.info("📍 Simple routing - returning planner response")
            elif "alert" in only_key:
                logger.info("⚠️ Simple alerts - returning alerts response")
            else:
                logger.info("📍 Simple stop query - returning stopfinder response")
            return {**state, "final_response": only_text, "should_end": True}

        # Alerts + planner (with or without stopfinder preprocessing)
        if alerts_text and planner_text:
            alerts_lower = alerts_text.lower()
            # Only treat as "real" disruptions if there are actual active problems —
            # scheduled weekend maintenance is common and not an emergency
            ACTIVE_DISRUPTION_WORDS = ["delay", "disruption", "problem", "issue",
                                       "warning", "suspended", "reduced", "cancelled",
                                       "stopped", "no service", "shuttle bus", "shuttle buses"]
            has_real_disruptions = any(w in alerts_lower for w in ACTIVE_DISRUPTION_WORDS)

            import re as _re
            user_msg_lower = state["user_message"].lower()
            user_wants_multiple = (
                any(w in user_msg_lower for w in ["two route", "multiple route", "2 route", "3 route",
                    "alternate route", "alternative route", "options", "different route"])
                or bool(_re.search(r"\b[2-5]\s*(route|option|way|path)", user_msg_lower))
            )
            if user_wants_multiple:
                if has_real_disruptions:
                    summary = alerts_text.split("\n")[0]
                    combined = f"{summary}\n\n{planner_text}"
                else:
                    combined = f"✅ No significant delays.\n\n{planner_text}"
                logger.info("✓ Multiple routes requested — returning planner output directly")
                return {**state, "final_response": combined, "should_end": True}

            # Fast-path synthesis: no active disruptions → skip LLM, use template
            if not has_real_disruptions:
                # Extract the first meaningful sentence from planner as the route
                route_sentence = planner_text.split(".")[0].strip() if planner_text else ""
                if route_sentence and len(route_sentence) < 20:
                    # Too short — use full planner text
                    route_sentence = planner_text
                no_disruption_intro = "No current delays."
                final_no_disruption = f"{no_disruption_intro} {planner_text}"
                logger.info("✨ Fast-path synthesis: no disruptions, returning template")
                return {**state, "final_response": final_no_disruption, "should_end": True}

            # Active disruptions present — use LLM to intelligently combine.
            # Trip queries: LEAD with the route (the direct answer), then mention ONLY
            # alerts that affect the lines/stations in that route. Unrelated system-wide
            # alerts (e.g. a bus detour across town) are noise for a point-to-point trip.
            logger.info(f"✓ Combining alerts + planner via LLM (disruptions=True)")
            prompt = (
                "A rider asked how to get from one place to another. Answer in 2-3 friendly sentences.\n\n"
                f"THEIR ROUTE (this is the main answer — lead with it):\n{planner_text[:400]}\n\n"
                f"CURRENT SYSTEM ALERTS (reference only):\n{alerts_text[:700]}\n\n"
                "Rules:\n"
                "1. Lead with the route — which line(s) to take and where.\n"
                "2. Then mention ONLY alerts that affect the specific line(s)/stations in their route. "
                "Give a wait estimate if one is stated.\n"
                "3. If no alert affects their route, end with a short reassurance that their route is running normally.\n"
                "4. Do NOT list unrelated alerts."
            )

            try:
                async with httpx.AsyncClient() as client:
                    r = await client.post(
                        "https://api.openai.com/v1/chat/completions",
                        headers={"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"},
                        json={
                            "model": "gpt-4o-mini",
                            "messages": [{"role": "user", "content": prompt}],
                            "temperature": 0.1,
                            "max_tokens": 150
                        },
                        timeout=15
                    )
                    r.raise_for_status()

                final = r.json()["choices"][0]["message"]["content"].strip()
                logger.info("✨ Synthesized alerts + planner")
                return {**state, "final_response": final, "should_end": True}

            except Exception as e:
                logger.error(f"Synthesis error: {e}")
                combined = f"{alerts_text}\n\n{planner_text}"
                return {**state, "final_response": combined, "should_end": True}

        # Default — join all real responses
        logger.info("📝 Returning combined responses")
        all_responses = list(resp_map.values())
        return {**state, "final_response": "\n\n".join(all_responses), "should_end": True}


# ============================================================================
# ROUTING
# ============================================================================

def route_after_discovery(state: AgentState) -> Literal["routing", "synthesize"]:
    return "routing" if state.get("matched_agents") else "synthesize"


def route_after_routing(state: AgentState) -> Literal["execute", "synthesize"]:
    return "execute" if state.get("matched_agents") else "synthesize"


def route_after_execute(state: AgentState) -> Literal["synthesize"]:
    return "synthesize"


# ============================================================================
# GRAPH
# ============================================================================

def build_graph() -> StateGraph:
    wf = StateGraph(AgentState)

    wf.add_node("discovery", discovery_node)
    wf.add_node("routing", routing_node)
    wf.add_node("execute", execute_agents_node)
    wf.add_node("synthesize", synthesize_node)

    # Discovery is the entry point — firewall enforcement happens at the DANS proxy layer
    wf.set_entry_point("discovery")

    wf.add_conditional_edges("discovery", route_after_discovery,
                            {"routing": "routing", "synthesize": "synthesize"})
    wf.add_conditional_edges("routing", route_after_routing,
                            {"execute": "execute", "synthesize": "synthesize"})
    wf.add_conditional_edges("execute", route_after_execute,
                            {"synthesize": "synthesize"})
    wf.add_edge("synthesize", END)

    return wf.compile()


# ============================================================================
# ORCHESTRATOR
# ============================================================================

class StateGraphOrchestrator:
    """
    Production Orchestrator v4.5 - Semantic Discovery + Domain Expertise
    - Registry-side semantic filtering (scales to 1000+ agents)
    - Fallback to LLM discovery if registry unavailable
    - Smart StopFinder skipping
    - Domain analysis extraction
    - Context passing between agents
    """
    
    def __init__(self):
        global _current_orchestrator
        
        logger.info("=" * 80)
        logger.info("🚀 StateGraph Orchestrator v4.5 - Semantic Discovery + Domain Expertise")
        logger.info("   ✅ Registry-side semantic filtering")
        logger.info("   ✅ Fallback to LLM discovery")
        logger.info("   ✅ Smart StopFinder skipping")
        logger.info("   ✅ Domain analysis extraction")
        logger.info("   ✅ Context passing")
        logger.info("   ✅ SLIM transport")
        logger.info("   ✅ Scales to 1000+ agents")
        logger.info("=" * 80)
        
        self.graph = build_graph()
        self.use_slim = os.getenv("USE_SLIM", "false").lower() == "true"
        self.slim_client = None
        
        if self.use_slim and SLIM_AVAILABLE:
            try:
                self.slim_client = SlimAgentClient()
                logger.info("✅ SLIM enabled")
            except Exception as e:
                logger.warning(f"SLIM failed: {e}")
                self.use_slim = False

        # ANS Dynamic Resolution
        self.use_ans = ANS_ENABLED and ANS_AVAILABLE
        self.resolver_client = None
        if self.use_ans:
            try:
                self.resolver_client = ResolverClient()
                logger.info("✅ ANS dynamic resolution enabled")
            except Exception as e:
                logger.warning(f"⚠️ ANS resolver client failed to init: {e}")
                self.use_ans = False
        else:
            if ANS_ENABLED and not ANS_AVAILABLE:
                logger.warning("⚠️ ANS_ENABLED=true but resolver_client not importable")
            else:
                logger.info("ℹ️  ANS resolution disabled (set ANS_ENABLED=true to enable)")

        _current_orchestrator = self
        logger.info("✅ Orchestrator v4.5 ready")
    
    async def startup_validation(self):
        """Validate registry connection"""
        logger.info("🔍 Validating...")
        
        if not await validate_registry():
            logger.warning("⚠️ Registry semantic search unavailable, will use LLM fallback")
        else:
            logger.info("✅ Registry semantic search validated")

        if self.use_ans and self.resolver_client:
            if await self.resolver_client.health_check():
                logger.info("✅ ANS recursive resolver reachable")
            else:
                logger.warning("⚠️ ANS resolver unreachable — falling back to static registry URLs")
                self.use_ans = False
        
        agents = await get_agent_catalog()
        logger.info(f"📚 {len(agents)} agents")
        
        if self.use_slim and self.slim_client:
            try:
                await self.slim_client.initialize()
                logger.info("✅ SLIM ready")
            except:
                self.use_slim = False
        
        logger.info("✅ Startup complete")
    
    async def process_message(self, user_message: str, conversation_id: str) -> Dict[str, Any]:
        """Process message through semantic discovery + domain expertise"""
        with tracer.start_as_current_span("stategraph_v45"):
            initial = {
                "user_message": user_message,
                "conversation_id": conversation_id,
                "intent": "",
                "confidence": 0.0,
                "matched_agents": [],
                "agent_queries": {},
                "llm_matching_decision": {},
                "messages": [],
                "agents_called": [],
                "agent_responses": [],
                "origin_text": "",
                "destination_text": "",
                "resolved_origin": "",
                "resolved_destination": "",
                "has_disruptions": False,
                "affected_routes": [],
                "severity_level": "none",
                "alerts_domain_analysis": {},
                "final_response": "",
                "should_end": False,
                "routing_decision": "",
                "semantic_scores": {},
                "discovery_method": "",
                "ans_traces": [],
                "firewall_blocked": False,
            }
            
            final = await self.graph.ainvoke(initial)
            
            # Build per-agent protocol_used map from agent_responses + ans_traces
            _agent_responses = final.get("agent_responses", [])
            _protocol_used_map: Dict[str, str] = {
                r["agent_used"]: r["protocol_used"]
                for r in _agent_responses
                if isinstance(r, dict) and r.get("agent_used") and r.get("protocol_used")
            }

            return {
                "response": final["final_response"],
                "intent": final["intent"],
                "confidence": final["confidence"],
                "matched_agents": final.get("matched_agents", []),
                "agents_called": final["agents_called"],
                "metadata": {
                    "conversation_id": conversation_id,
                    "discovery": final.get("discovery_method", "semantic_v45"),
                    "transport": "dans_negotiated" if self.use_ans else ("slim" if self.use_slim else "http"),
                    "protocol_used": _protocol_used_map,  # per-agent protocol DANS negotiated
                    "semantic_scores": final.get("semantic_scores", {}),
                    "optimization": {
                        "stopfinder_skipped": not final.get("resolved_origin") and not final.get("resolved_destination"),
                    },
                    "domain_expertise": {
                        "alerts_analysis_available": bool(final.get("alerts_domain_analysis")),
                        "context_passed_to_planner": bool(final.get("alerts_domain_analysis"))
                    },
                    "context": {
                        "origin": final.get("origin_text", ""),
                        "destination": final.get("destination_text", ""),
                        "resolved_origin": final.get("resolved_origin", ""),
                        "resolved_dest": final.get("resolved_destination", ""),
                        "disruptions": final.get("has_disruptions", False),
                        "affected": final.get("affected_routes", []),
                        "severity": final.get("severity_level", "none")
                    },
                    "registry_url": REGISTRY_URL,
                    "ans_enabled": self.use_ans,
                    "ans_traces": final.get("ans_traces", []),
                }
            }