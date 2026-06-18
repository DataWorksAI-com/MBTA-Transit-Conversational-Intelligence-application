#!/bin/bash
# register_agents_with_descriptions_test.sh
# Registers MBTA TEST agents in NANDA Registry TEST with semantic descriptions

REGISTRY_URL="$1"

if [ -z "$REGISTRY_URL" ]; then
    echo "❌ Usage: $0 <REGISTRY_TEST_URL>"
    echo ""
    echo "Example:"
    echo "  bash register_agents_with_descriptions_test.sh \"http://172.104.25.25:6900\""
    exit 1
fi

echo "🗄️ Registering MBTA TEST Agents with Semantic Descriptions"
echo "============================================================"
echo "Registry: $REGISTRY_URL"
echo "Environment: TEST"
echo ""

# ============================================================================
# Agent 1: mbta-alerts-test
# ============================================================================
echo "[1/3] Registering mbta-alerts-test..."

curl -X POST $REGISTRY_URL/register \
  -H "Content-Type: application/json" \
  -d '{
    "agent_id": "mbta-alerts-test",
    "agent_url": "http://AGENTS_TEST_IP:8001"
  }' 2>/dev/null

echo ""

curl -X PUT $REGISTRY_URL/agents/mbta-alerts-test/status \
  -H "Content-Type: application/json" \
  -d '{
    "alive": true,
    "description": "[TEST] Provides real-time service alerts, delays, and disruptions for Boston MBTA trains and buses. Monitors all subway lines (Red, Orange, Blue, Green) and commuter rail for issues, maintenance, and schedule changes. Reports both current problems and planned service modifications.",
    "capabilities": ["alerts", "service-status", "disruptions", "real-time"],
    "tags": ["test", "mbta", "development"]
  }'

echo "✅ mbta-alerts-test registered"
echo ""

# ============================================================================
# Agent 2: mbta-stopfinder-test
# ============================================================================
echo "[2/3] Registering mbta-stopfinder-test..."

curl -X POST $REGISTRY_URL/register \
  -H "Content-Type: application/json" \
  -d '{
    "agent_id": "mbta-stopfinder-test",
    "agent_url": "http://AGENTS_TEST_IP:8003"
  }' 2>/dev/null

echo ""

curl -X PUT $REGISTRY_URL/agents/mbta-stopfinder-test/status \
  -H "Content-Type: application/json" \
  -d '{
    "alive": true,
    "description": "[TEST] Finds MBTA stations and stops by name, location, or proximity. Provides detailed stop information including accessible facilities, parking availability, bike racks, and connecting routes. Can search by address, GPS coordinates, or landmark names. Covers all MBTA subway, bus, and commuter rail stops.",
    "capabilities": ["stops", "stations", "location-search", "find-stops", "nearby"],
    "tags": ["test", "mbta", "development"]
  }'

echo "✅ mbta-stopfinder-test registered"
echo ""

# ============================================================================
# Agent 3: mbta-planner-test
# ============================================================================
echo "[3/3] Registering mbta-planner-test..."

curl -X POST $REGISTRY_URL/register \
  -H "Content-Type: application/json" \
  -d '{
    "agent_id": "mbta-planner-test",
    "agent_url": "http://AGENTS_TEST_IP:8002"
  }' 2>/dev/null

echo ""

curl -X PUT $REGISTRY_URL/agents/mbta-planner-test/status \
  -H "Content-Type: application/json" \
  -d '{
    "alive": true,
    "description": "[TEST] Plans optimal routes and trips on Boston MBTA transit network. Provides step-by-step directions including train/bus lines, transfers, walking instructions, and estimated travel times. Considers multiple route options, suggests fastest routes, and accounts for real-time conditions. Handles complex multi-leg journeys across subway, bus, and commuter rail.",
    "capabilities": ["trip-planning", "routing", "directions", "navigation", "route-planning"],
    "tags": ["test", "mbta", "development"]
  }'

echo "✅ mbta-planner-test registered"
echo ""

# ============================================================================
# Verification
# ============================================================================
echo "======================================================"
echo "🔍 Verifying TEST Registrations..."
echo ""

echo "Checking mbta-alerts-test:"
curl -s "$REGISTRY_URL/agents/mbta-alerts-test" | python3 -m json.tool | grep -E "agent_id|description|alive"

echo ""
echo "Checking mbta-stopfinder-test:"
curl -s "$REGISTRY_URL/agents/mbta-stopfinder-test" | python3 -m json.tool | grep -E "agent_id|description|alive"

echo ""
echo "Checking mbta-planner-test:"
curl -s "$REGISTRY_URL/agents/mbta-planner-test" | python3 -m json.tool | grep -E "agent_id|description|alive"

echo ""
echo "======================================================"
echo "✅ All TEST agents registered with semantic descriptions!"
echo ""
echo "📝 IMPORTANT: Update agent URLs with actual TEST IP:"
echo "   Replace 'AGENTS_TEST_IP' with your test agents server IP"
echo ""
echo "   Example:"
echo "   curl -X PUT $REGISTRY_URL/agents/mbta-alerts-test/status \\"
echo "     -H 'Content-Type: application/json' \\"
echo "     -d '{\"alive\": true, \"agent_url\": \"http://172.104.25.25:8001\"}'"
echo ""
echo "🧪 Test semantic discovery on TEST Exchange:"
echo "  curl -X POST http://EXCHANGE_TEST_IP:8100/chat -d '{\"query\": \"Red Line delays?\"}'"
echo ""
