#!/bin/bash
# ============================================================================
# deploy_registry_server.sh  —  Registry server (97.107.132.213)
#
# Run from the mbta/ project root AFTER deploy_agents_server.sh:
#   bash deploy/deploy_registry_server.sh
#
# What this does:
#   1. Copies updated registry.py (adds ANS TLD NS + App NS endpoints +
#      agent_name field) to /home/ubuntu/Northeastern-registry/registry.py
#   2. Backs up the original first
#   3. Updates supervisor conf to add AUTH_NS_URL + ANS env vars
#   4. Restarts the registry
#   5. Updates MongoDB agent documents with ANS URN field
# ============================================================================

set -euo pipefail

SERVER="root@97.107.132.213"
KEY="$(dirname "$0")/../../Northeastern-registry-v3-key"
SSH="ssh -i $KEY -o StrictHostKeyChecking=no"
SCP="scp -i $KEY -o StrictHostKeyChecking=no"
REMOTE_DIR="/home/ubuntu/Northeastern-registry"
REMOTE_FILE="${REMOTE_DIR}/registry.py"

echo ""
echo "═══════════════════════════════════════════════════════════"
echo "  Deploying ANS → Registry server (97.107.132.213)"
echo "═══════════════════════════════════════════════════════════"
echo ""

# ── Step 1: Backup original registry.py ──────────────────────────────────────
echo "▶ Backing up original registry.py..."
$SSH $SERVER "cp ${REMOTE_FILE} ${REMOTE_FILE}.backup_pre_ans_$(date +%Y%m%d_%H%M%S)"

# ── Step 2: Copy updated registry.py ─────────────────────────────────────────
echo ""
echo "▶ Deploying updated registry.py..."
$SCP src/registry_semantic.py "${SERVER}:${REMOTE_FILE}"

# ── Step 3: Update supervisor conf with ANS env vars ─────────────────────────
echo ""
echo "▶ Updating supervisor conf with ANS env vars..."
$SCP deploy/supervisor/registry-server/northeastern-registry.conf \
    "${SERVER}:/etc/supervisor/conf.d/registry.conf"

# ── Step 4: Restart registry ──────────────────────────────────────────────────
echo ""
echo "▶ Restarting registry..."
$SSH $SERVER "
    supervisorctl reread
    supervisorctl update
    supervisorctl restart registry
    sleep 3
    supervisorctl status registry
"

# ── Step 5: Update MongoDB agent documents with ANS URN field ─────────────────
echo ""
echo "▶ Updating MongoDB with ANS URN field..."
$SCP deploy/mongodb_update_urns.js "${SERVER}:/tmp/mongodb_update_urns.js"
$SSH $SERVER "
    MONGO_URI='mongodb+srv://nanda_admin:nanda_pass@cluster0.auzlobs.mongodb.net/?appName=Cluster0'
    mongosh \"\$MONGO_URI\" /tmp/mongodb_update_urns.js
"

# ── Step 6: Smoke tests ───────────────────────────────────────────────────────
echo ""
echo "▶ Smoke tests..."
sleep 2

echo -n "  registry /health: "
curl -s --max-time 5 http://97.107.132.213:6900/health \
  | python3 -c "import sys,json; d=json.load(sys.stdin); print('✅ status=' + d.get('status','MISSING'))"

echo -n "  POST /resolve (TLD NS → alerts): "
curl -s --max-time 8 -X POST http://97.107.132.213:6900/resolve \
  -H "Content-Type: application/json" \
  -d '{"agent_path":"mbta-transit-ci:alerts","requester_context":{"protocols":["A2A"]}}' \
  | python3 -c "import sys,json; d=json.load(sys.stdin); print('✅ endpoint=' + str(d.get('endpoint','ERROR: ' + str(d))))"

echo -n "  POST /resolve/mbta-transit-ci (App NS → planner): "
curl -s --max-time 8 -X POST http://97.107.132.213:6900/resolve/mbta-transit-ci \
  -H "Content-Type: application/json" \
  -d '{"agent":"planner","requester_context":{}}' \
  | python3 -c "import sys,json; d=json.load(sys.stdin); print('✅ endpoint=' + str(d.get('endpoint','ERROR: ' + str(d))))"

echo ""
echo "═══════════════════════════════════════════════════════════"
echo "  ✅ Registry server deployment complete"
echo "═══════════════════════════════════════════════════════════"
echo ""
