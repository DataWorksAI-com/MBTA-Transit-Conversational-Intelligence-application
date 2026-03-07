# src/exchange_agent/exchange_server.py

"""
Exchange Agent - Hybrid A2A + MCP Orchestrator
Version 4.0 - Intelligent Expertise-Based Routing

Routes queries based on domain expertise needs:
- Simple fact lookups → MCP (fast API wrappers)
- Queries needing predictions/analysis/recommendations → A2A (domain experts)
"""

import sys
import os

# Load environment variables FIRST (before any other imports)
from dotenv import load_dotenv
load_dotenv()  # This loads .env from current directory or parent directories

# Initialize OpenTelemetry BEFORE other imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

try:
    from src.observability.otel_config import setup_otel
    from src.observability.clickhouse_logger import get_clickhouse_logger
    setup_otel("exchange-agent")
    print("✅ OpenTelemetry configured for exchange-agent")
except Exception as e:
    print(f"⚠️  Could not setup observability: {e}")
    import traceback
    traceback.print_exc()
    print("Continuing without telemetry...")

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from pydantic import BaseModel
from typing import Optional, Dict, Any, List, Literal
import logging
import time
import uuid
import json
import asyncio
import random
import re

# Add parent directory to Python path for imports
if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

# Try relative imports first, fall back to absolute
try:
    from .mcp_client import MCPClient
    from .stategraph_orchestrator import StateGraphOrchestrator  
except ImportError:
    from mcp_client import MCPClient
    from stategraph_orchestrator import StateGraphOrchestrator  

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Verify API key is loaded
api_key = os.getenv("OPENAI_API_KEY")
if not api_key:
    logger.error("=" * 60)
    logger.error("❌ OPENAI_API_KEY not found in environment!")
    logger.error("=" * 60)
    logger.error("Please ensure .env file exists in project root with:")
    logger.error("  OPENAI_API_KEY=sk-...")
    logger.error("=" * 60)
    sys.exit(1)
else:
    logger.info(f"✓ OpenAI API key loaded (ends with: ...{api_key[-4:]})")

# Initialize OpenAI client
from openai import OpenAI
openai_client = OpenAI(api_key=api_key)

# Global instances
mcp_client: Optional[MCPClient] = None
stategraph_orchestrator: Optional[StateGraphOrchestrator] = None
clickhouse_logger = None

# Tracer for OpenTelemetry
try:
    from opentelemetry import trace
    tracer = trace.get_tracer(__name__)
    logger.info("✅ OpenTelemetry tracer initialized")
except ImportError:
    # Fallback no-op tracer
    class NoOpTracer:
        def start_as_current_span(self, name):
            from contextlib import contextmanager
            @contextmanager
            def _span():
                yield type('obj', (object,), {'set_attribute': lambda *args: None, 'set_status': lambda *args: None, 'record_exception': lambda *args: None})()
            return _span()
    tracer = NoOpTracer()
    logger.warning("⚠️  OpenTelemetry not available, using no-op tracer")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Manage application lifecycle
    Startup: Initialize MCP client, StateGraph orchestrator, and ClickHouse logger
    Shutdown: Cleanup resources
    """
    global mcp_client, stategraph_orchestrator, clickhouse_logger
    
    # Startup
    logger.info("=" * 60)
    logger.info("Starting Exchange Agent v4.0 - Intelligent Expertise Router")
    logger.info("=" * 60)
    
    # Initialize ClickHouse Logger
    try:
        clickhouse_logger = get_clickhouse_logger()
        logger.info("✅ ClickHouse logger initialized")
    except Exception as e:
        logger.warning(f"⚠️  ClickHouse logger initialization failed: {e}")
        clickhouse_logger = None
    
    # Initialize StateGraph Orchestrator (for A2A path)
    try:
        stategraph_orchestrator = StateGraphOrchestrator()
        logger.info("✅ StateGraph Orchestrator initialized")
        
        # Validate registry connectivity and agent discovery
        logger.info("🔍 Validating registry connectivity...")
        await stategraph_orchestrator.startup_validation()
        logger.info("✅ Registry validation passed - A2A path ready")
        
    except RuntimeError as e:
        logger.error(f"❌ Registry validation failed: {e}")
        logger.error("A2A path unavailable - agents not discoverable")
        stategraph_orchestrator = None
    except Exception as e:
        logger.error(f"❌ StateGraph Orchestrator initialization failed: {e}")
        logger.exception(e)
        stategraph_orchestrator = None
    
    # Initialize MCP Client (for fast path)
    try:
        mcp_client = MCPClient()
        await mcp_client.initialize()
        logger.info("✅ MCP Client initialized - Fast path available")
    except Exception as e:
        logger.warning(f"⚠️  MCP Client initialization failed: {e}")
        logger.warning("Falling back to A2A agents only")
        mcp_client = None
    
    logger.info("=" * 60)
    
    yield
    
    # Shutdown
    logger.info("Shutting down Exchange Agent...")
    if mcp_client:
        await mcp_client.cleanup()
    logger.info("✓ Shutdown complete")


# Create FastAPI app with lifespan
app = FastAPI(
    title="MBTA Exchange Agent",
    description="Hybrid A2A + MCP with LLM-Based Intelligent Routing",
    version="5.0.0",
    lifespan=lifespan
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============================================================================
# AUTO-INSTRUMENTATION - Automatically trace HTTP requests/responses
# ============================================================================
try:
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
    from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
    
    # Auto-instrument FastAPI (all endpoints)
    FastAPIInstrumentor.instrument_app(app)
    logger.info("✅ FastAPI auto-instrumentation enabled")
    
    # Auto-instrument HTTPX (HTTP client for A2A calls)
    HTTPXClientInstrumentor().instrument()
    logger.info("✅ HTTPX auto-instrumentation enabled")
except Exception as e:
    logger.warning(f"⚠️  Auto-instrumentation failed: {e}")


# Request/Response models
class ChatRequest(BaseModel):
    query: str
    user_id: Optional[str] = "default_user"
    conversation_id: Optional[str] = None
    routing_mode: Optional[Literal["auto", "mcp", "a2a"]] = "auto"


class ChatResponse(BaseModel):
    response: str
    path: str  # Now supports: "mcp", "a2a", or "shortcut"
    latency_ms: int
    intent: str
    confidence: float
    metadata: Optional[Dict[str, Any]] = None


@app.get("/")
async def root():
    """Health check endpoint"""
    return {
        "service": "MBTA Exchange Agent",
        "version": "5.0.0",
        "architecture": "Hybrid A2A + MCP with LLM-Based Intelligent Routing",
        "routing_logic": "GPT-4o-mini semantic classification (replaces keyword matching)",
        "features": ["llm_routing", "domain_analysis", "multi_agent_orchestration"],
        "optimization": "Semantic understanding of query intent",
        "mcp_available": mcp_client is not None and mcp_client._initialized,
        "stategraph_available": stategraph_orchestrator is not None,
        "clickhouse_available": clickhouse_logger is not None,
        "status": "healthy"
    }


# ============================================================
# STEP 0: SHORTCUT PATH DETECTION (NO LLM CALL)
# ============================================================

def is_greeting_or_simple_query(query: str) -> bool:
    """Fast pattern matching to detect greetings and simple queries"""
    query_lower = query.lower().strip()
    
    # Very short queries only (less than 10 words)
    word_count = len(query_lower.split())
    if word_count > 10:
        return False
    
    # Only match pure greetings
    greeting_patterns = [
        'hi', 'hello', 'hey', 'greetings', 'good morning',
        'good afternoon', 'good evening', 'howdy', 'sup', 'yo'
    ]
    
    if any(query_lower == greeting or query_lower.startswith(greeting + " ") 
           for greeting in greeting_patterns):
        return True
    
    return False


def get_shortcut_response(query: str) -> str:
    """Generate response for shortcut path queries (NO LLM NEEDED)"""
    query_lower = query.lower().strip()
    
    greeting_keywords = ['hi', 'hello', 'hey', 'greetings']
    if any(keyword in query_lower for keyword in greeting_keywords):
        responses = [
            "Hello! I'm MBTA Agentcy. Ask about service alerts, routes, or stations!",
            "Hi! I can help with Boston MBTA transit info.",
        ]
        return random.choice(responses)
    
    return "I'm specialized in Boston MBTA transit..."


# ============================================================
# NEW: INTELLIGENT EXPERTISE-BASED ROUTING
# ============================================================

def needs_domain_expertise(query: str) -> tuple[bool, str, List[str]]:
    """
    Detect if query needs domain expertise beyond API data.
    
    UPDATED v5.1: Added crowding detection
    
    Returns:
        (needs_expertise: bool, reasoning: str, detected_patterns: List[str])
    """
    
    query_lower = query.lower()
    detected_patterns = []
    
    # CROWDING keywords (NEW in v5.1!)
    CROWDING = [
        "crowded", "crowd", "busy", "full", "packed", "space",
        "capacity", "occupancy", "how full", "standing room",
        "seats available", "room on"
    ]
    if any(kw in query_lower for kw in CROWDING):
        detected_patterns.append("crowding_analysis")
        return True, "Query requires crowding analysis with domain expertise", detected_patterns
    
    # PREDICTIVE keywords
    PREDICTIVE = ["should i wait", "worth waiting", "how long will", "when will"]
    if any(kw in query_lower for kw in PREDICTIVE):
        detected_patterns.append("predictive")
        return True, "Query requires predictive analysis", detected_patterns
    
    # DECISION SUPPORT keywords
    DECISION = ["should i", "recommend", "suggest", "better to", "what should i do"]
    if any(kw in query_lower for kw in DECISION):
        detected_patterns.append("decision_support")
        return True, "Query needs decision support", detected_patterns
    
    # CONDITIONAL keywords
    CONDITIONAL = ["if there are", "considering", "depending on"]
    if any(kw in query_lower for kw in CONDITIONAL):
        detected_patterns.append("conditional")
        return True, "Query has conditional logic", detected_patterns
    
    # ANALYTICAL keywords
    ANALYTICAL = ["why", "explain", "what caused", "how serious"]
    if any(kw in query_lower for kw in ANALYTICAL):
        detected_patterns.append("analytical")
        return True, "Query needs analytical interpretation", detected_patterns
    
    # ROUTING pattern
    if re.search(r"from .+ to .+", query_lower):
        detected_patterns.append("routing")
        return True, "Query requires multi-agent coordination", detected_patterns
    
    # DEFAULT: Simple fact lookup
    return False, "Simple fact lookup - MCP can handle", detected_patterns

# ============================================================================
# UNIFIED CLASSIFICATION + ROUTING + TOOL SELECTION (WITH SHORTCUT PATH)
# ============================================================================

async def classify_route_and_select_tool(query: str, available_tools: List[Dict]) -> Dict:
    """
    OPTIMIZED ROUTING with early shortcut detection:
    
    STEP 0: Check for shortcut path (greetings, simple queries)
            -> If matched, return immediately (no LLM call needed)
    
    STEP 1-3: Single LLM call for complex queries:
        1. Intent classification
        2. Path selection (MCP vs A2A)
        3. Tool selection with parameters (if MCP chosen)
    
    Returns:
        {
            "path": "shortcut|mcp|a2a",
            "intent": "greeting|alerts|stops|trip_planning|general",
            "confidence": 0.95,
            "reasoning": "Explanation of decision",
            "complexity": 0.0,
            
            # Only if path="shortcut":
            "shortcut_response": "Hello! I'm MBTA Agentcy...",
            "llm_calls": 0,
            
            # Only if path="mcp":
            "mcp_tool": "mbta_get_alerts",
            "mcp_parameters": {"route_id": "Red"}
        }
    """
    
    with tracer.start_as_current_span("classify_route_and_select_tool") as span:
        span.set_attribute("query", query)
        span.set_attribute("query_length", len(query))
        span.set_attribute("available_tools_count", len(available_tools))
        
        # ================================================================
        # STEP 0: SHORTCUT PATH DETECTION (NO LLM CALL)
        # ================================================================
        if is_greeting_or_simple_query(query):
            with tracer.start_as_current_span("shortcut_path_detection") as shortcut_span:
                shortcut_span.set_attribute("matched", True)
                
                shortcut_response = get_shortcut_response(query)
                
                decision = {
                    "path": "shortcut",
                    "intent": "greeting",
                    "confidence": 1.0,
                    "reasoning": "Simple greeting detected via pattern matching",
                    "complexity": 0.0,
                    "shortcut_response": shortcut_response,
                    "llm_calls": 0
                }
                
                span.set_attribute("routing.path", "shortcut")
                span.set_attribute("llm.calls", 0)
                
                logger.info(f"⚡ SHORTCUT PATH: {decision['reasoning']}")
                
                return decision
        
        # ================================================================
        # NOT A SHORTCUT - Proceed with full LLM routing
        # ================================================================
        
        # Format available tools for the LLM
        tools_list = "\n".join([
            f"  • {tool['name']}: {tool['description']}"
            for tool in available_tools
        ]) if available_tools else "  (No MCP tools available - must use A2A)"
        
        system_prompt = f"""You are an intelligent MBTA query routing system.

**YOUR TASK:** Analyze the query and make ALL routing decisions in one response.

═══════════════════════════════════════════════════════════
STEP 1: CLASSIFY INTENT
═══════════════════════════════════════════════════════════

CRITICAL: Understand what counts as MBTA-related!

**"alerts"** - Anything about MBTA service, delays, or disruptions (CURRENT OR HISTORICAL):
  ✅ Current status: "Red Line delays?", "Any issues now?", "Current service disruptions?"
  ✅ Historical patterns: "How long do medical delays take?", "Typical delay duration?", "Usually how long?"
  ✅ Pattern questions: "Based on past data...", "On average...", "Generally how long...", "Typically..."
  ✅ Crowding: "How crowded?", "Is it busy?", "Room on trains?", "Packed?", "Full trains?"
  ✅ Predictions: "Should I wait?", "Worth waiting?", "How long will this last?", "When will it clear?"
  ✅ Analysis: "How serious?", "Why delays?", "What's causing this?"
  
  PRINCIPLE: If asking about MBTA delays, duration, crowding, patterns, or service status → "alerts"
  
**"stops"** - Station/stop information, finding stations:
  ✅ "Where is Copley?", "Find Harvard station", "Stops on Green Line"
  ✅ "What station is nearest to X?", "List all stations", "Show me Orange Line stops"
  
**"trip_planning"** - Route planning, directions, how to get somewhere:
  ✅ "Route from X to Y", "How do I get to X?", "Best route to Y?"
  ✅ "Park St to Harvard?", "Get me from X to Y", "Directions to MIT?"
  
**"general"** - NOT about MBTA/transit at all (completely off-topic):
  ❌ "What's the weather in Boston?" - Not transit
  ❌ "Who won the Red Sox game?" - Not transit (even though it says "Red")
  ❌ "Boston history facts?" - Not transit
  ❌ "What's 2+2?" - Not transit
  ❌ "Tell me a joke" - Not transit

PRINCIPLE: If query mentions MBTA, trains, T, subway, delays, crowding, stations, routes, or ANY transit topic → NOT "general"!

Only classify as "general" if the query has NOTHING to do with Boston public transit.

═══════════════════════════════════════════════════════════
STEP 2: CHOOSE PATH & SELECT TOOL
═══════════════════════════════════════════════════════════

**Decision Tree:**

Is it MBTA-related?
  ├─ NO → path="a2a", intent="general"
  └─ YES → Does it need analysis/prediction/historical data/expertise?
            ├─ YES → path="a2a" (Domain experts needed)
            │         Examples: "How long do delays take?", "Should I wait?", "How crowded?", "Route from X to Y"
            └─ NO → Can MCP tool provide the answer?
                      ├─ YES → path="mcp" + select tool
                      │         Examples: "Red Line delays RIGHT NOW?", "Next train at Park?"
                      └─ NO → path="a2a"

**MCP Path (Fast, ~400ms):**
- Best for: Current real-time data lookup with single API call
- Examples: "Red Line delays right now?", "Next train at Park St?", "Where are Orange Line trains?"
- NO analysis, NO historical, NO predictions - just current facts

**A2A Path (Domain Experts, ~1500ms):**
- Best for: Requires analysis, expertise, historical data, predictions, or multi-agent coordination
- Examples:
  * "How long do delays usually take?" → Needs historical data from domain expert
  * "Should I wait?" → Needs decision support analysis
  * "How crowded is it?" → Needs crowding analysis
  * "Route from X to Y" → Needs multi-agent coordination
  * "Best route considering delays?" → Needs expert reasoning

PRINCIPLE: 
- Current fact → MCP
- Analysis/Prediction/Historical/Expertise → A2A

═══════════════════════════════════════════════════════════
STEP 3: SELECT MCP TOOL (ONLY IF path="mcp")
═══════════════════════════════════════════════════════════

Available MCP Tools:
{tools_list}

**PARAMETER NAMING (CRITICAL):**
- Use "route_id" NOT "route" (e.g., route_id="Red")
- Use "stop_id" NOT "stop"
- Red Line = "Red", Orange = "Orange", Blue = "Blue", Green = "Green-B"

═══════════════════════════════════════════════════════════
OUTPUT FORMAT
═══════════════════════════════════════════════════════════

Return ONLY valid JSON (no markdown, no code blocks):

**For A2A path:**
{{
  "intent": "alerts",
  "confidence": 0.95,
  "path": "a2a",
  "reasoning": "Historical MBTA delay pattern question requires domain expertise with historical data",
  "complexity": 0.6
}}

**For MCP path:**
{{
  "intent": "alerts",
  "confidence": 0.95,
  "path": "mcp",
  "reasoning": "Current alert lookup can be answered with direct API call",
  "complexity": 0.2,
  "mcp_tool": "mbta_get_alerts",
  "mcp_parameters": {{"route_id": "Red"}}
}}"""

        user_message = f"""Query: "{query}"

Analyze and provide routing decision."""

        try:
            with tracer.start_as_current_span("llm_unified_routing") as llm_span:
                llm_span.set_attribute("model", "gpt-4o-mini")
                
                response = await asyncio.to_thread(
                    openai_client.chat.completions.create,
                    model="gpt-4o-mini",
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_message}
                    ],
                    temperature=0.3,
                    max_tokens=300
                )
                
                decision_text = response.choices[0].message.content.strip()
                
                # Remove markdown formatting
                if decision_text.startswith("```json"):
                    decision_text = decision_text.replace("```json", "").replace("```", "").strip()
                elif decision_text.startswith("```"):
                    decision_text = decision_text.replace("```", "").strip()
                
                decision = json.loads(decision_text)
                
                # Validate and set defaults
                decision.setdefault("complexity", 0.5)
                decision.setdefault("confidence", 0.5)
                decision.setdefault("reasoning", "No reasoning provided")
                decision["llm_calls"] = 1
                
                # Validate MCP path
                if decision["path"] == "mcp":
                    if "mcp_tool" not in decision:
                        logger.warning("MCP selected but no tool - fallback to A2A")
                        decision["path"] = "a2a"
                    elif "mcp_parameters" not in decision:
                        decision["mcp_parameters"] = {}
                
                span.set_attribute("intent", decision['intent'])
                span.set_attribute("confidence", decision['confidence'])
                span.set_attribute("path", decision['path'])
                
                logger.info(f"🧠 LLM Decision:")
                logger.info(f"   Intent: {decision['intent']} ({decision['confidence']:.2f})")
                logger.info(f"   Path: {decision['path']} (complexity: {decision['complexity']:.2f})")
                logger.info(f"   Reasoning: {decision['reasoning']}")
                
                return decision
                
        except json.JSONDecodeError as e:
            logger.error(f"JSON parse error: {e}")
            return {
                "intent": "general",
                "confidence": 0.3,
                "path": "a2a",
                "reasoning": f"JSON error: {str(e)}",
                "complexity": 0.5,
                "llm_calls": 1
            }
        except Exception as e:
            logger.error(f"Routing failed: {e}", exc_info=True)
            return {
                "intent": "general",
                "confidence": 0.3,
                "path": "a2a",
                "reasoning": f"Error: {str(e)}",
                "complexity": 0.5,
                "llm_calls": 1
            }


async def select_mcp_tool_forced(query: str, available_tools: List[Dict]) -> Dict[str, Any]:
    """Best-effort MCP tool selection for forced MCP mode."""
    if not available_tools:
        return {}

    tools_list = "\n".join([f"- {t['name']}: {t.get('description', '')}" for t in available_tools])
    prompt = f"""Select the single best MCP tool for this user query.

Query: "{query}"

Available MCP tools:
{tools_list}

Return ONLY JSON:
{{
  "mcp_tool": "tool_name",
  "mcp_parameters": {{}}
}}"""

    try:
        response = await asyncio.to_thread(
            openai_client.chat.completions.create,
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0,
            max_tokens=180
        )
        text = response.choices[0].message.content.strip()
        if text.startswith("```json"):
            text = text.replace("```json", "").replace("```", "").strip()
        elif text.startswith("```"):
            text = text.replace("```", "").strip()

        parsed = json.loads(text)
        tool_name = parsed.get("mcp_tool")
        tool_params = parsed.get("mcp_parameters", {})
        valid_tool_names = {t["name"] for t in available_tools}
        if tool_name in valid_tool_names and isinstance(tool_params, dict):
            return {"mcp_tool": tool_name, "mcp_parameters": tool_params}
    except Exception as e:
        logger.warning(f"Forced MCP tool selection failed: {e}")

    return {}


# ============================================================================
# MAIN CHAT ENDPOINT
# ============================================================================

@app.post("/chat", response_model=ChatResponse)
async def chat_endpoint(request: ChatRequest):
    """
    Main chat endpoint with intelligent expertise-based routing
    
    THREE PATHS:
    1. SHORTCUT (~10ms) - Greetings (pattern matching)
    2. MCP (~400ms) - Simple fact lookups
    3. A2A (~1500ms) - Queries needing domain expertise
    """
    
    with tracer.start_as_current_span("chat_endpoint") as root_span:
        start_time = time.time()
        query = request.query
        conversation_id = request.conversation_id or str(uuid.uuid4())
        routing_mode = (request.routing_mode or "auto").strip().lower()
        if routing_mode not in {"auto", "mcp", "a2a"}:
            routing_mode = "auto"
        
        root_span.set_attribute("query", query)
        root_span.set_attribute("conversation_id", conversation_id)
        root_span.set_attribute("user_id", request.user_id)
        root_span.set_attribute("routing_mode", routing_mode)
        
        if not query or not query.strip():
            raise HTTPException(status_code=400, detail="Query cannot be empty")
        
        logger.info("=" * 80)
        logger.info(f"📨 Received query: {query}")
        logger.info(f"   Conversation ID: {conversation_id}")
        
        # Get available MCP tools
        available_tools = []
        if mcp_client and mcp_client._initialized:
            if hasattr(mcp_client, '_available_tools') and mcp_client._available_tools:
                for tool in mcp_client._available_tools:
                    available_tools.append({
                        "name": tool.name,
                        "description": tool.description or ""
                    })
                logger.info(f"📋 {len(available_tools)} MCP tools available")
        
        # ====================================================================
        # STEP 1: INTELLIGENT EXPERTISE-BASED ROUTING (NEW in v4.0)
        # ====================================================================
        
        with tracer.start_as_current_span("expertise_based_routing") as routing_span:
            # Analyze if query needs domain expertise (keyword-based)
            needs_expertise, expertise_reasoning, detected_patterns = needs_domain_expertise(query)
            
            routing_span.set_attribute("needs_expertise", needs_expertise)
            routing_span.set_attribute("reasoning", expertise_reasoning)
            routing_span.set_attribute("detected_patterns", str(detected_patterns))
            
            logger.info(f"🧠 EXPERTISE ANALYSIS:")
            logger.info(f"   Needs expertise: {needs_expertise}")
            logger.info(f"   Reasoning: {expertise_reasoning}")
            logger.info(f"   Patterns detected: {detected_patterns}")
            
            # Still use unified LLM for intent classification and tool selection
            decision = await classify_route_and_select_tool(query, available_tools)

            if routing_mode == "mcp":
                decision["path"] = "mcp"
                decision["reasoning"] = "Forced via UI routing_mode=mcp"
                decision["confidence"] = 1.0
                if "mcp_tool" not in decision or "mcp_parameters" not in decision:
                    forced_tool = await select_mcp_tool_forced(query, available_tools)
                    if forced_tool:
                        decision.update(forced_tool)
            elif routing_mode == "a2a":
                decision["path"] = "a2a"
                decision["reasoning"] = "Forced via UI routing_mode=a2a"
                decision["confidence"] = 1.0
            else:
                # OVERRIDE path based on expertise analysis (auto mode only)
                if needs_expertise:
                    original_path = decision["path"]
                    decision["path"] = "a2a"
                    decision["reasoning"] = f"EXPERTISE REQUIRED: {expertise_reasoning}"
                    
                    if original_path != "a2a":
                        logger.info(f"   ✓ OVERRIDE: {original_path} → a2a (expertise needed)")
                    else:
                        logger.info(f"   ✓ Confirmed A2A (expertise needed)")
                else:
                    # No expertise needed - MCP is fine if available
                    if decision["path"] == "mcp":
                        logger.info(f"   ✓ Confirmed MCP - {expertise_reasoning}")
                    else:
                        logger.info(f"   ✓ A2A path (LLM decision, no override)")
            
            intent = decision["intent"]
            confidence = decision["confidence"]
            chosen_path = decision["path"]
        
        # Log to ClickHouse: User message
        if clickhouse_logger:
            try:
                clickhouse_logger.log_conversation(
                    conversation_id=conversation_id,
                    user_id=request.user_id,
                    role="user",
                    content=query,
                    intent=intent,
                    routed_to_orchestrator=(chosen_path == "a2a"),
                    metadata={
                        "confidence": confidence,
                        "complexity": decision.get('complexity', 0.5),
                        "reasoning": decision['reasoning'],
                        "path": chosen_path,
                        "needs_expertise": needs_expertise,
                        "expertise_reasoning": expertise_reasoning,
                        "detected_patterns": detected_patterns
                    }
                )
            except Exception as e:
                logger.warning(f"ClickHouse logging failed: {e}")
        
        # ====================================================================
        # STEP 2: EXECUTE CHOSEN PATH
        # ====================================================================
        
        response_text = ""
        path_taken = ""
        metadata = {
            "unified_decision": {
                "intent": intent,
                "confidence": confidence,
                "path": chosen_path,
                "reasoning": decision["reasoning"],
                "complexity": decision.get("complexity", 0.5),
                "llm_calls": decision.get("llm_calls", 0),
                "routing_mode": routing_mode
            },
            "expertise_analysis": {
                "needs_expertise": needs_expertise,
                "reasoning": expertise_reasoning,
                "detected_patterns": detected_patterns
            }
        }
        
        if chosen_path == "shortcut":
            # SHORTCUT PATH
            with tracer.start_as_current_span("handle_shortcut_path"):
                response_text = decision["shortcut_response"]
                path_taken = "shortcut"
                
                metadata["shortcut_execution"] = {
                    "method": "pattern_matching",
                    "llm_calls": 0,
                    "cost_usd": 0.0
                }
                
                logger.info(f"⚡ SHORTCUT PATH executed")
        
        elif chosen_path == "mcp" and mcp_client and mcp_client._initialized:
            # MCP FAST PATH
            if "mcp_tool" not in decision or "mcp_parameters" not in decision:
                forced_tool = await select_mcp_tool_forced(query, available_tools)
                if forced_tool:
                    decision.update(forced_tool)
                else:
                    logger.warning("MCP selected but no tool selected - fallback to A2A")
                    response_text, a2a_metadata = await handle_a2a_path(query, conversation_id)
                    path_taken = "a2a_fallback"
                    metadata.update(a2a_metadata)
                    metadata["fallback_reason"] = "No MCP tool selected"
                    metadata["mcp_error"] = "No MCP tool selected"
                    tool_name = None
                    tool_params = None
            
            if "mcp_tool" in decision and "mcp_parameters" in decision:
                tool_name = decision['mcp_tool']
                tool_params = decision['mcp_parameters']
            else:
                tool_name = None
                tool_params = None
            
            if tool_name is not None:
                logger.info(f"🚀 MCP Fast Path:")
                logger.info(f"   Tool: {tool_name}")
                logger.info(f"   Parameters: {tool_params}")
            
                try:
                    tool_result = await call_mcp_tool_dynamic(tool_name, tool_params)
                
                    metadata["mcp_execution"] = {
                        "tool": tool_name,
                        "parameters": tool_params,
                        "success": True
                    }
                
                    response_text = await synthesize_mcp_response_with_llm(query, tool_name, tool_result)
                
                    path_taken = "mcp"
                    logger.info(f"✅ MCP execution successful")
                
                except Exception as e:
                    logger.error(f"❌ MCP execution failed: {e}")
                    root_span.record_exception(e)
                
                    logger.info("↪️  Falling back to A2A path")
                    response_text, a2a_metadata = await handle_a2a_path(query, conversation_id)
                    path_taken = "a2a_fallback"
                    metadata.update(a2a_metadata)
                    metadata["mcp_error"] = str(e)
        
        elif chosen_path == "a2a":
            # A2A MULTI AGENT PATH
            logger.info(f"🔄 A2A Path: {decision['reasoning']}")
            
            if needs_expertise:
                logger.info(f"   🧠 Domain expertise will be used")
            
            response_text, a2a_metadata = await handle_a2a_path(query, conversation_id)
            path_taken = "a2a"
            metadata.update(a2a_metadata)
            metadata["domain_expertise_used"] = needs_expertise
        
        else:
            # MCP selected but not available - fallback
            logger.warning("MCP selected but unavailable - fallback to A2A")
            response_text, a2a_metadata = await handle_a2a_path(query, conversation_id)
            path_taken = "a2a_fallback"
            metadata.update(a2a_metadata)
            metadata["fallback_reason"] = "MCP unavailable"
        
        # Calculate latency
        latency_ms = int((time.time() - start_time) * 1000)
        
        root_span.set_attribute("path_taken", path_taken)
        root_span.set_attribute("latency_ms", latency_ms)
        root_span.set_attribute("needs_expertise", needs_expertise)
        
        logger.info(f"✅ Response via {path_taken} in {latency_ms}ms")
        logger.info("=" * 80)
        
        # Log to ClickHouse: Assistant response
        if clickhouse_logger:
            try:
                clickhouse_logger.log_conversation(
                    conversation_id=conversation_id,
                    user_id=request.user_id,
                    role="assistant",
                    content=response_text[:1000],
                    intent=intent,
                    routed_to_orchestrator=(path_taken in ["a2a", "a2a_fallback"]),
                    metadata={
                        "path": path_taken,
                        "latency_ms": latency_ms,
                        "confidence": confidence,
                        "needs_expertise": needs_expertise
                    }
                )
            except Exception as e:
                logger.warning(f"ClickHouse logging failed: {e}")
        
        return ChatResponse(
            response=response_text,
            path=path_taken,
            latency_ms=latency_ms,
            intent=intent,
            confidence=confidence,
            metadata=metadata
        )


# ============================================================================
# MCP TOOL EXECUTION (DYNAMIC DISPATCH)
# ============================================================================

async def call_mcp_tool_dynamic(tool_name: str, parameters: Dict) -> Dict[str, Any]:
    """Dynamically call any MCP tool"""
    
    with tracer.start_as_current_span("call_mcp_tool_dynamic") as span:
        span.set_attribute("tool_name", tool_name)
        span.set_attribute("parameters", json.dumps(parameters))

        logger.info(f"🔧 Calling {tool_name} with params: {parameters}")

        # Preferred path: generic MCP dispatch from current MCPClient implementation.
        if hasattr(mcp_client, "call_tool"):
            result = await mcp_client.call_tool(tool_name, parameters or {})
        else:
            # Backward-compatible fallback for older MCPClient implementations.
            tool_method_map = {
                "mbta_get_alerts": "get_alerts",
                "mbta_get_routes": "get_routes",
                "mbta_get_stops": "get_stops",
                "mbta_search_stops": "search_stops",
                "mbta_get_predictions": "get_predictions",
                "mbta_get_predictions_for_stop": "get_predictions_for_stop",
                "mbta_get_schedules": "get_schedules",
                "mbta_get_trips": "get_trips",
                "mbta_get_vehicles": "get_vehicles",
                "mbta_get_nearby_stops": "get_nearby_stops",
                "mbta_plan_trip": "plan_trip",
                "mbta_list_all_routes": "list_all_routes",
                "mbta_list_all_stops": "list_all_stops",
                "mbta_list_all_alerts": "list_all_alerts",
            }

            method_name = tool_method_map.get(tool_name)
            if not method_name or not hasattr(mcp_client, method_name):
                raise ValueError(f"Unknown MCP tool or unsupported MCP client method: {tool_name}")

            method = getattr(mcp_client, method_name)
            result = await method(**(parameters or {}))

        span.set_attribute("success", True)
        logger.info(f"✓ Tool execution successful")
        
        return result


# ============================================================================
# RESPONSE SYNTHESIS
# ============================================================================

async def synthesize_mcp_response_with_llm(query: str, tool_name: str, tool_result: Dict) -> str:
    """Convert MCP JSON response into natural language"""
    
    system_prompt = """You are a helpful MBTA transit assistant.

Convert the technical API response into a natural, conversational answer.

Be concise but informative. Use natural language, not technical jargon."""

    tool_result_str = json.dumps(tool_result, indent=2)
    if len(tool_result_str) > 4000:
        tool_result_str = tool_result_str[:4000] + "\n... (truncated)"
    
    user_message = f"""User Query: "{query}"

Tool Used: {tool_name}

API Response:
{tool_result_str}

Convert to natural answer."""

    try:
        with tracer.start_as_current_span("synthesize_response"):
            response = await asyncio.to_thread(
                openai_client.chat.completions.create,
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message}
                ],
                temperature=0.7,
                max_tokens=500
            )
            
            return response.choices[0].message.content.strip()
    
    except Exception as e:
        logger.error(f"Synthesis failed: {e}")
        return f"I found information but had trouble formatting it: {str(tool_result)[:200]}..."


# ============================================================================
# A2A PATH HANDLER
# ============================================================================

async def handle_a2a_path(query: str, conversation_id: str) -> tuple[str, Dict[str, Any]]:
    """Handle query using A2A agents with domain expertise"""
    
    with tracer.start_as_current_span("handle_a2a_path") as span:
        span.set_attribute("query", query)
        span.set_attribute("conversation_id", conversation_id)
        
        if not stategraph_orchestrator:
            logger.error("StateGraph unavailable")
            return (
                "I'm having trouble processing your request. Please try again.",
                {"error": "StateGraph unavailable"}
            )
        
        try:
            logger.info(f"🔄 Running StateGraph orchestration")
            
            result = await stategraph_orchestrator.process_message(query, conversation_id)
            
            response_text = result.get("response", "")
            
            metadata = {
                "stategraph_intent": result.get("intent"),
                "stategraph_confidence": result.get("confidence"),
                "agents_called": result.get("agents_called", []),
                "graph_execution": result.get("metadata", {}).get("graph_execution", "completed")
            }
            
            span.set_attribute("agents_called", json.dumps(metadata['agents_called']))
            span.set_attribute("agents_count", len(metadata['agents_called']))
            
            logger.info(f"✓ StateGraph completed")
            logger.info(f"   Agents: {', '.join(metadata['agents_called'])}")
            
            return response_text, metadata
        
        except Exception as e:
            logger.error(f"A2A error: {e}", exc_info=True)
            span.record_exception(e)
            return (f"Error: {str(e)}", {"error": str(e)})


# ============================================================================
# HEALTH & METRICS
# ============================================================================

@app.get("/health")
async def health_check():
    """Detailed health check"""
    return {
        "status": "healthy",
        "timestamp": time.time(),
        "components": {
            "mcp_client": {
                "available": mcp_client is not None,
                "initialized": mcp_client._initialized if mcp_client else False,
                "tools_count": len(mcp_client._available_tools) if mcp_client and hasattr(mcp_client, '_available_tools') else 0
            },
            "stategraph": {
                "available": stategraph_orchestrator is not None
            },
            "clickhouse": {
                "available": clickhouse_logger is not None
            },
            "routing": {
                "method": "expertise_based",
                "version": "4.0"
            }
        }
    }


@app.get("/metrics")
async def get_metrics():
    """Metrics endpoint"""
    tools_available = []
    if mcp_client and hasattr(mcp_client, '_available_tools'):
        tools_available = [tool.name for tool in mcp_client._available_tools]
    
    return {
        "mcp_tools_available": len(tools_available),
        "mcp_tools": tools_available,
        "stategraph_available": stategraph_orchestrator is not None,
        "version": "4.0.0",
        "routing_method": "expertise_based",
        "routing_criteria": {
            "mcp": "Simple fact lookups (API wrappers sufficient)",
            "a2a": "Queries needing domain expertise (predictions, recommendations, analysis)"
        },
        "expertise_detection": {
            "predictive": ["should i wait", "how long will", "when will"],
            "decision_support": ["should i", "recommend", "suggest", "better to"],
            "conditional": ["if", "considering", "depending on"],
            "analytical": ["why", "explain", "what caused", "how serious"],
            "multi_step": ["from X to Y", "route considering", "check then"]
        },
        "llm_calls_per_request": {
            "shortcut_path": 0,
            "mcp_path": 2,  # 1 unified + 1 synthesis
            "a2a_path": 1,  # 1 unified only
        }
    }


if __name__ == "__main__":
    import uvicorn
    
    logger.info("=" * 80)
    logger.info("🚀 Starting MBTA Exchange Agent Server")
    logger.info("   Version: 4.0.0")
    logger.info("   Routing: Intelligent Expertise-Based")
    logger.info("   Logic: Routes based on domain expertise needs")
    logger.info("=" * 80)
    
    uvicorn.run(app, host="0.0.0.0", port=8100)
