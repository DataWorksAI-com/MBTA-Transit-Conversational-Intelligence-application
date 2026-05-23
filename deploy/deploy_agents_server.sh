#!/bin/bash
# ============================================================================
# deploy_agents_server.sh  —  Agents server (96.126.111.107)
#
# Run from the mbta/ project root on your local machine:
#   bash deploy/deploy_agents_server.sh
#
# What this does:
#   1. Copies ans/ package to /opt/mbta-agents/ans/
#   2. Copies updated agents/alerts/main.py (adds load_percent to /health)
#   3. Copies updated agents/common/registry_client.py (adds agent_name URN)
#   4. Installs the new mbta-auth-ns supervisor conf
#   5. Starts the Auth NS on :8300
#   NOTE: Does NOT overwrite existing slim/agent supervisor confs
# ============================================================================

set -euo pipefail

SERVER="root@96.126.111.107"
KEY="$(dirname "$0")/../mbta-agents-key"
SSH="ssh -i $KEY -o StrictHostKeyChecking=no"
SCP="scp -i $KEY -o StrictHostKeyChecking=no"
REMOTE="/opt/mbta-agents"

echo ""
echo "═══════════════════════════════════════════════════════════"
echo "  Deploying ANS → Agents server (96.126.111.107)"
echo "═══════════════════════════════════════════════════════════"
echo ""

# ── Step 1: Create ans/ directory and copy package ────────────────────────────
echo "▶ Deploying ans/ package..."
$SSH $SERVER "mkdir -p ${REMOTE}/ans"
rsync -avz -e "ssh -i $KEY -o StrictHostKeyChecking=no" --progress \
    ans/ "${SERVER}:${REMOTE}/ans/"

# ── Step 2: Update alerts main.py (adds load_percent to /health) ──────────────
echo ""
echo "▶ Updating agents/alerts/main.py..."
$SCP agents/alerts/main.py "${SERVER}:${REMOTE}/agents/alerts/main.py"

# ── Step 3: Update registry_client.py (adds agent_name URN to registration) ──
echo ""
echo "▶ Updating agents/common/registry_client.py..."
$SCP agents/common/registry_client.py "${SERVER}:${REMOTE}/agents/common/registry_client.py"

# ── Step 4: Install Auth NS supervisor conf (new — doesn't touch existing) ───
echo ""
echo "▶ Installing mbta-auth-ns supervisor config..."
$SCP deploy/supervisor/agents-server/mbta-auth-ns.conf \
    "${SERVER}:/etc/supervisor/conf.d/mbta-auth-ns.conf"

# ── Step 5: Reload supervisord and start Auth NS ──────────────────────────────
echo ""
echo "▶ Starting Auth NS on :8300..."
$SSH $SERVER "
    supervisorctl reread
    supervisorctl update
    supervisorctl start mbta-auth-ns 2>/dev/null || supervisorctl restart mbta-auth-ns
    sleep 3
    supervisorctl status
"

# ── Step 6: Smoke tests ───────────────────────────────────────────────────────
echo ""
echo "▶ Smoke tests..."
sleep 2

echo -n "  alerts slim /.well-known/agent.json: "
curl -s --max-time 3 http://96.126.111.107:50051/.well-known/agent.json \
  | python3 -c "import sys,json; d=json.load(sys.stdin); print('✅ name=' + d.get('name','MISSING'))"

echo -n "  planner slim /.well-known/agent.json: "
curl -s --max-time 3 http://96.126.111.107:50052/.well-known/agent.json \
  | python3 -c "import sys,json; d=json.load(sys.stdin); print('✅ name=' + d.get('name','MISSING'))"

echo -n "  stopfinder slim /.well-known/agent.json: "
curl -s --max-time 3 http://96.126.111.107:50053/.well-known/agent.json \
  | python3 -c "import sys,json; d=json.load(sys.stdin); print('✅ name=' + d.get('name','MISSING'))"

echo -n "  auth-ns /health: "
curl -s --max-time 5 http://96.126.111.107:8300/health \
  | python3 -c "import sys,json; d=json.load(sys.stdin); print('✅ status=' + str(d.get('status','MISSING')))"

echo -n "  auth-ns POST /resolve (alerts): "
curl -s --max-time 5 -X POST http://96.126.111.107:8300/resolve \
  -H "Content-Type: application/json" \
  -d '{"agent":"alerts","requester_context":{"protocols":["A2A"]}}' \
  | python3 -c "import sys,json; d=json.load(sys.stdin); print('✅ endpoint=' + str(d.get('endpoint','ERROR: ' + str(d))))"

echo ""
echo "═══════════════════════════════════════════════════════════"
echo "  ✅ Agents server deployment complete"
echo "═══════════════════════════════════════════════════════════"
echo ""
