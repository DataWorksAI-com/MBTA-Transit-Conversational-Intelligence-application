#!/bin/bash
# ============================================================================
# deploy_exchange_server.sh  —  Exchange server (50.116.53.133)
#
# Run from the mbta/ project root AFTER the other two deploy scripts:
#   bash deploy/deploy_exchange_server.sh
#
# What this does:
#   1. Copies ans/ package to /opt/mbta-agentcy/ans/
#   2. Copies production resolver_client.py to exchange agent
#   3. Installs ONLY the new mbta-resolver supervisor conf (does NOT
#      overwrite mbta-exchange.conf — you must patch it manually, see below)
#   4. Starts the Recursive Resolver on :8200
# ============================================================================

set -euo pipefail

SERVER="root@50.116.53.133"
KEY="$(dirname "$0")/../../mbta-exchange-key"
SSH="ssh -i $KEY -o StrictHostKeyChecking=no"
SCP="scp -i $KEY -o StrictHostKeyChecking=no"
REMOTE="/opt/mbta-agentcy"

echo ""
echo "═══════════════════════════════════════════════════════════"
echo "  Deploying ANS → Exchange server (50.116.53.133)"
echo "═══════════════════════════════════════════════════════════"
echo ""

# ── Step 1: Copy ans/ package ─────────────────────────────────────────────────
echo "▶ Deploying ans/ package..."
$SSH $SERVER "mkdir -p ${REMOTE}/ans"
rsync -avz -e "ssh -i $KEY -o StrictHostKeyChecking=no" --progress \
    ans/ "${SERVER}:${REMOTE}/ans/"

# ── Step 2: Copy resolver_client.py ──────────────────────────────────────────
echo ""
echo "▶ Deploying production resolver_client.py..."
$SCP src/exchange_agent/resolver_client.py \
    "${SERVER}:${REMOTE}/src/exchange_agent/resolver_client.py"

# ── Step 3: Install ONLY the resolver supervisor conf ─────────────────────────
echo ""
echo "▶ Installing mbta-resolver supervisor config..."
$SCP deploy/supervisor/exchange-server/mbta-resolver.conf \
    "${SERVER}:/etc/supervisor/conf.d/mbta-resolver.conf"

# ── Step 4: Start the Recursive Resolver ──────────────────────────────────────
echo ""
echo "▶ Starting Recursive Resolver on :8200..."
$SSH $SERVER "
    supervisorctl reread
    supervisorctl update
    supervisorctl start mbta-resolver 2>/dev/null || supervisorctl restart mbta-resolver
    sleep 3
    supervisorctl status
"

# ── Step 5: Smoke tests ───────────────────────────────────────────────────────
echo ""
echo "▶ Smoke tests..."
sleep 2

echo -n "  resolver /health: "
curl -s --max-time 5 http://50.116.53.133:8200/health \
  | python3 -c "import sys,json; d=json.load(sys.stdin); print('✅ ok=' + str(d.get('ok','MISSING')))"

echo -n "  POST /resolve (alerts, first call): "
RESP=$(curl -s --max-time 10 -X POST http://50.116.53.133:8200/resolve \
  -H "Content-Type: application/json" \
  -d '{"agent_name":"urn:agents.dataworksai.com:mbta-transit-ci:alerts","requester_context":{"location":{"city":"Boston"},"protocols":["A2A"]},"cache_enabled":true}')
echo "$RESP" | python3 -c "import sys,json; d=json.load(sys.stdin); print('✅ endpoint=' + str(d.get('endpoint','ERROR')) + '  cached=' + str(d.get('cached','?')))"

echo -n "  POST /resolve (alerts, cached): "
curl -s --max-time 10 -X POST http://50.116.53.133:8200/resolve \
  -H "Content-Type: application/json" \
  -d '{"agent_name":"urn:agents.dataworksai.com:mbta-transit-ci:alerts","requester_context":{"location":{"city":"Boston"},"protocols":["A2A"]},"cache_enabled":true}' \
  | python3 -c "import sys,json; d=json.load(sys.stdin); print('✅ cached=' + str(d.get('cached','?')) + ' (should be true)')"

echo -n "  POST /resolve (planner): "
curl -s --max-time 10 -X POST http://50.116.53.133:8200/resolve \
  -H "Content-Type: application/json" \
  -d '{"agent_name":"urn:agents.dataworksai.com:mbta-transit-ci:planner","requester_context":{}}' \
  | python3 -c "import sys,json; d=json.load(sys.stdin); print('✅ endpoint=' + str(d.get('endpoint','ERROR: ' + str(d))))"

echo -n "  POST /resolve (stopfinder): "
curl -s --max-time 10 -X POST http://50.116.53.133:8200/resolve \
  -H "Content-Type: application/json" \
  -d '{"agent_name":"urn:agents.dataworksai.com:mbta-transit-ci:stopfinder","requester_context":{}}' \
  | python3 -c "import sys,json; d=json.load(sys.stdin); print('✅ endpoint=' + str(d.get('endpoint','ERROR: ' + str(d))))"

echo ""
echo "═══════════════════════════════════════════════════════════"
echo "  ✅ Recursive Resolver running on :8200"
echo ""
echo "  ⚠️  MANUAL STEP — patch the exchange supervisor conf:"
echo ""
echo "  ssh -i mbta-exchange-key root@50.116.53.133"
echo "  nano /etc/supervisor/conf.d/mbta-exchange.conf"
echo ""
echo "  Change the environment= line to add (keep existing vars):"
echo "    ANS_ENABLED=\"true\","
echo "    ANS_RESOLVER_URL=\"http://50.116.53.133:8200\","
echo "    ANS_RESOLVER_TIMEOUT=\"5.0\","
echo "    ANS_TLD=\"agents.dataworksai.com\","
echo "    ANS_APP=\"mbta-transit-ci\""
echo ""
echo "  Then:"
echo "    supervisorctl reread && supervisorctl update"
echo "    supervisorctl restart mbta-exchange"
echo ""
echo "  Verify ANS is live:"
echo "    tail -f /var/log/mbta-exchange.out.log | grep -E '(ANS|resolved)'"
echo "═══════════════════════════════════════════════════════════"
echo ""
