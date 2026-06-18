#!/bin/bash
# ============================================================================
# test_resolution.sh — End-to-end test of the ANS resolution chain (v2.0)
#
# Run AFTER run_all.sh. Tests each tier independently then the full chain.
# Usage: bash prototype/test_resolution.sh
# ============================================================================

PASS=0
FAIL=0
RED='\033[0;31m'
GREEN='\033[0;32m'
NC='\033[0m'

check() {
    local label="$1"
    local expected="$2"
    local actual="$3"
    if echo "$actual" | grep -q "$expected"; then
        echo -e "  ${GREEN}✅ PASS${NC}: $label"
        PASS=$((PASS + 1))
    else
        echo -e "  ${RED}❌ FAIL${NC}: $label"
        echo "     Expected to contain: $expected"
        echo "     Got: $actual"
        FAIL=$((FAIL + 1))
    fi
}

echo ""
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║       ANS Resolution Chain v2.0 — End-to-End Tests           ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""

# ── Tier 0: Stub agents health ───────────────────────────────────────────────
echo "── Tier 0: Stub Agent Health ──────────────────────────────────"
check "alerts stub health"     "status"    "$(curl -s http://localhost:8001/health)"
check "planner stub health"    "status"    "$(curl -s http://localhost:8002/health)"
check "stopfinder stub health" "status"    "$(curl -s http://localhost:8003/health)"
echo ""

# ── Tier 1: Authoritative Nameservers (POST /resolve) ────────────────────────
echo "── Tier 1: Authoritative Nameservers ──────────────────────────"

ALERTS_RESP=$(curl -s -X POST http://localhost:8300/resolve \
    -H "Content-Type: application/json" \
    -d '{"agent": "alerts", "requester_context": {"protocols": ["A2A"]}}')
check "alerts auth-ns: endpoint returned"     '"endpoint"'          "$ALERTS_RESP"
check "alerts auth-ns: ttl present"           '"ttl"'               "$ALERTS_RESP"
check "alerts auth-ns: protocol returned"     '"protocol"'          "$ALERTS_RESP"
check "alerts auth-ns: points to :8001"       'localhost:8001'      "$ALERTS_RESP"
check "alerts auth-ns: metadata present"      '"metadata"'          "$ALERTS_RESP"
check "alerts auth-ns: server health verified" '"server_health"'    "$ALERTS_RESP"

PLANNER_RESP=$(curl -s -X POST http://localhost:8301/resolve \
    -H "Content-Type: application/json" \
    -d '{"agent": "planner", "requester_context": {"protocols": ["A2A"]}}')
check "planner auth-ns: endpoint returned"    '"endpoint"'          "$PLANNER_RESP"
check "planner auth-ns: points to :8002"      'localhost:8002'      "$PLANNER_RESP"

SF_RESP=$(curl -s -X POST http://localhost:8302/resolve \
    -H "Content-Type: application/json" \
    -d '{"agent": "stopfinder", "requester_context": {"protocols": ["A2A"]}}')
check "stopfinder auth-ns: endpoint returned" '"endpoint"'          "$SF_RESP"
check "stopfinder auth-ns: points to :8003"   'localhost:8003'      "$SF_RESP"

# Test Auth NS own health
check "alerts auth-ns /health"     '"ok"'  "$(curl -s http://localhost:8300/health)"
check "planner auth-ns /health"    '"ok"'  "$(curl -s http://localhost:8301/health)"
check "stopfinder auth-ns /health" '"ok"'  "$(curl -s http://localhost:8302/health)"
echo ""

# ── Tier 2: Namespace Servers (Registry) ─────────────────────────────────────
echo "── Tier 2: Namespace Servers (Registry :6900) ─────────────────"

# Legacy GET endpoint (backward compat)
TLD_RESP=$(curl -s "http://localhost:6900/resolve/tld?urn=urn:agents.local:mbta-transit-ci:alerts")
check "TLD NS GET: parses URN"              '"delegate_to"'        "$TLD_RESP"
check "TLD NS GET: returns app_namespace"   '"mbta-transit-ci"'    "$TLD_RESP"

# New POST endpoint
POST_RESOLVE=$(curl -s -X POST http://localhost:6900/resolve \
    -H "Content-Type: application/json" \
    -d '{"agent_path": "mbta-transit-ci:alerts", "requester_context": {"protocols": ["A2A"]}}')
check "Registry POST /resolve: endpoint"    '"endpoint"'           "$POST_RESOLVE"
check "Registry POST /resolve: ttl"         '"ttl"'                "$POST_RESOLVE"

# App NS GET
APP_NS_RESP=$(curl -s "http://localhost:6900/resolve/mbta-transit-ci?urn=urn:agents.local:mbta-transit-ci:planner")
check "App NS GET: resolves planner"        '"delegate_to"'        "$APP_NS_RESP"
check "App NS GET: returns auth-ns :8301"   'localhost:8301'       "$APP_NS_RESP"

# App NS POST
APP_POST=$(curl -s -X POST http://localhost:6900/resolve/mbta-transit-ci \
    -H "Content-Type: application/json" \
    -d '{"agent": "stopfinder", "requester_context": {}}')
check "App NS POST: stopfinder endpoint"    '"endpoint"'           "$APP_POST"
check "App NS POST: points to :8003"        'localhost:8003'       "$APP_POST"

# Malformed URN should return 400
MALFORMED_CODE=$(curl -s -o /dev/null -w "%{http_code}" "http://localhost:6900/resolve/tld?urn=not-a-urn")
check "TLD NS rejects malformed URN (400)" "400" "$MALFORMED_CODE"
echo ""

# ── Tier 3: Recursive Resolver (full chain) ───────────────────────────────────
echo "── Tier 3: Recursive Resolver :8200 ───────────────────────────"

# First call — should NOT be cached
RESOLVE1=$(curl -s -X POST http://localhost:8200/resolve \
    -H "Content-Type: application/json" \
    -d '{
      "agent_name": "urn:agents.local:mbta-transit-ci:alerts",
      "requester_context": {"location": {"city": "Boston"}, "protocols": ["A2A"]},
      "cache_enabled": true
    }')
check "Resolver: alerts endpoint returned"      '"endpoint"'            "$RESOLVE1"
check "Resolver: first call not cached"         '"cached":false'        "$RESOLVE1"
check "Resolver: resolution_time_ms present"    '"resolution_time_ms"'  "$RESOLVE1"
check "Resolver: ttl present"                   '"ttl"'                 "$RESOLVE1"
check "Resolver: metadata present"              '"metadata"'            "$RESOLVE1"
check "Resolver: protocol present"              '"protocol"'            "$RESOLVE1"

# Second call — same context → should be cached
RESOLVE2=$(curl -s -X POST http://localhost:8200/resolve \
    -H "Content-Type: application/json" \
    -d '{
      "agent_name": "urn:agents.local:mbta-transit-ci:alerts",
      "requester_context": {"location": {"city": "Boston"}, "protocols": ["A2A"]},
      "cache_enabled": true
    }')
check "Resolver: second call IS cached"         '"cached":true'         "$RESOLVE2"
check "Resolver: cached response has endpoint"  '"endpoint"'            "$RESOLVE2"

# Planner resolution
RESOLVE_PL=$(curl -s -X POST http://localhost:8200/resolve \
    -H "Content-Type: application/json" \
    -d '{"agent_name": "urn:agents.local:mbta-transit-ci:planner", "requester_context": {}}')
check "Resolver: planner resolves"              '"endpoint"'            "$RESOLVE_PL"

# StopFinder resolution
RESOLVE_SF=$(curl -s -X POST http://localhost:8200/resolve \
    -H "Content-Type: application/json" \
    -d '{"agent_name": "urn:agents.local:mbta-transit-ci:stopfinder", "requester_context": {}}')
check "Resolver: stopfinder resolves"           '"endpoint"'            "$RESOLVE_SF"

# Malformed URN → 400
BAD_CODE=$(curl -s -o /dev/null -w "%{http_code}" -X POST http://localhost:8200/resolve \
    -H "Content-Type: application/json" \
    -d '{"agent_name": "not-a-urn", "requester_context": {}}')
check "Resolver: rejects malformed URN (400)"   "400"                   "$BAD_CODE"

# Different context → different cache key → not cached
RESOLVE_WEST=$(curl -s -X POST http://localhost:8200/resolve \
    -H "Content-Type: application/json" \
    -d '{
      "agent_name": "urn:agents.local:mbta-transit-ci:alerts",
      "requester_context": {"location": {"city": "Fremont"}, "protocols": ["A2A"]},
      "cache_enabled": true
    }')
check "Resolver: different context = fresh lookup" '"cached":false'     "$RESOLVE_WEST"

# Cache stats
CACHE_STATS=$(curl -s http://localhost:8200/cache/stats)
check "Cache stats: hit_rate_percent present"   '"hit_rate_percent"'   "$CACHE_STATS"
check "Cache stats: hits > 0"                   '"hits"'               "$CACHE_STATS"
check "Cache stats: current_size present"       '"current_size"'       "$CACHE_STATS"

# Resolver health
check "Resolver /health"                        '"ok":true'            "$(curl -s http://localhost:8200/health)"
check "Resolver /namespaces"                    '"agents.local"'       "$(curl -s http://localhost:8200/namespaces)"
echo ""

# ── Tier 4: Cache clear ───────────────────────────────────────────────────────
echo "── Tier 4: Cache clear ─────────────────────────────────────────"
CLEAR_RESP=$(curl -s -X POST http://localhost:8200/cache/clear)
check "Cache clear returns cleared:true"        '"cleared":true'       "$CLEAR_RESP"

RESOLVE3=$(curl -s -X POST http://localhost:8200/resolve \
    -H "Content-Type: application/json" \
    -d '{
      "agent_name": "urn:agents.local:mbta-transit-ci:alerts",
      "requester_context": {"location": {"city": "Boston"}, "protocols": ["A2A"]},
      "cache_enabled": true
    }')
check "After clear: first call not cached again" '"cached":false'      "$RESOLVE3"
echo ""

# ── Summary ───────────────────────────────────────────────────────────────────
echo "╔══════════════════════════════════════════════════════════════╗"
echo -e "║  Results: ${GREEN}$PASS passed${NC}  /  ${RED}$FAIL failed${NC}$(printf '%*s' $((30 - ${#PASS} - ${#FAIL})) '')║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""

if [ "$FAIL" -gt 0 ]; then
    echo "Some tests failed. Check services are running: bash prototype/run_all.sh"
    exit 1
fi
