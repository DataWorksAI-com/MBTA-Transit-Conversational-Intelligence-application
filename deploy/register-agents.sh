#!/usr/bin/env bash
# ============================================================================
# Register the MBTA agents (alerts / stopfinder / planner) into the registry
# with their semantic descriptions + capabilities, then verify.
#
#   bash deploy/register-agents.sh
#
# Requires REGISTRY_IP + AGENTS_IP in state.env (deploy 10-registry and
# 20-agents first). No host of its own — pure curl calls into the registry.
# All IPs come from state.env; nothing is hardcoded.
# ============================================================================
. "$(dirname "${BASH_SOURCE[0]}")/_lib.sh"
load_config
require_state REGISTRY_IP AGENTS_IP

REGISTRY_URL="http://${REGISTRY_IP}:6900"

log "registering MBTA agents into ${REGISTRY_URL} (agents @ ${AGENTS_IP})"

# ── Agent 1: mbta-alerts ─────────────────────────────────────────────────────
log "[1/3] registering mbta-alerts"
curl -X POST "$REGISTRY_URL/register" \
  -H "Content-Type: application/json" \
  -d "{
    \"agent_id\": \"mbta-alerts\",
    \"agent_url\": \"http://${AGENTS_IP}:8001\"
  }" 2>/dev/null
echo

curl -X PUT "$REGISTRY_URL/agents/mbta-alerts/status" \
  -H "Content-Type: application/json" \
  -d '{
    "alive": true,
    "description": "Provides real-time service alerts, delays, and disruptions for Boston MBTA trains and buses. Monitors all subway lines (Red, Orange, Blue, Green) and commuter rail for issues, maintenance, and schedule changes. Reports both current problems and planned service modifications.",
    "capabilities": ["alerts", "service-status", "disruptions", "real-time"]
  }'
ok "mbta-alerts registered"
echo

# ── Agent 2: mbta-stopfinder ─────────────────────────────────────────────────
log "[2/3] registering mbta-stopfinder"
curl -X POST "$REGISTRY_URL/register" \
  -H "Content-Type: application/json" \
  -d "{
    \"agent_id\": \"mbta-stopfinder\",
    \"agent_url\": \"http://${AGENTS_IP}:8003\"
  }" 2>/dev/null
echo

curl -X PUT "$REGISTRY_URL/agents/mbta-stopfinder/status" \
  -H "Content-Type: application/json" \
  -d '{
    "alive": true,
    "description": "Finds MBTA stations and stops by name, location, or proximity. Provides detailed stop information including accessible facilities, parking availability, bike racks, and connecting routes. Can search by address, GPS coordinates, or landmark names. Covers all MBTA subway, bus, and commuter rail stops.",
    "capabilities": ["stops", "stations", "location-search", "find-stops", "nearby"]
  }'
ok "mbta-stopfinder registered"
echo

# ── Agent 3: mbta-planner ────────────────────────────────────────────────────
log "[3/3] registering mbta-planner"
curl -X POST "$REGISTRY_URL/register" \
  -H "Content-Type: application/json" \
  -d "{
    \"agent_id\": \"mbta-planner\",
    \"agent_url\": \"http://${AGENTS_IP}:8002\"
  }" 2>/dev/null
echo

curl -X PUT "$REGISTRY_URL/agents/mbta-planner/status" \
  -H "Content-Type: application/json" \
  -d '{
    "alive": true,
    "description": "Plans optimal routes and trips on Boston MBTA transit network. Provides step-by-step directions including train/bus lines, transfers, walking instructions, and estimated travel times. Considers multiple route options, suggests fastest routes, and accounts for real-time conditions. Handles complex multi-leg journeys across subway, bus, and commuter rail.",
    "capabilities": ["trip-planning", "routing", "directions", "navigation", "route-planning"]
  }'
ok "mbta-planner registered"
echo

# ── Verification ─────────────────────────────────────────────────────────────
log "verifying registrations"
for a in mbta-alerts mbta-stopfinder mbta-planner; do
  echo "Checking $a:"
  curl -s "$REGISTRY_URL/agents/$a" | python3 -m json.tool | grep -E "agent_id|description|alive"
  echo
done

ok "all agents registered with semantic descriptions"
echo "   test: curl -X POST http://\${EXCHANGE_IP}:8100/chat -d '{\"query\": \"Red Line delays?\"}'"
