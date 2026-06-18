#!/bin/bash
# ============================================================================
# run_all.sh — Start all ANS prototype services
#
# Usage: bash prototype/run_all.sh
# Run from the repo root (Desktop/mbta/)
# ============================================================================

set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
PIDS_FILE="$SCRIPT_DIR/.pids"

# Clear old PIDs file
> "$PIDS_FILE"

log() { echo "  $1"; }

# ── Activate virtualenv ──────────────────────────────────────────────────────
if [ -f "$REPO_ROOT/venv/Scripts/activate" ]; then
    source "$REPO_ROOT/venv/Scripts/activate"
elif [ -f "$REPO_ROOT/venv/bin/activate" ]; then
    source "$REPO_ROOT/venv/bin/activate"
else
    echo "⚠️  No venv found at $REPO_ROOT/venv — using system Python"
fi

echo ""
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║         MBTA ANS Prototype — Starting all services           ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""

# ── Stub agents (:8001-8003) ─────────────────────────────────────────────────
echo "▶ Starting stub agents..."
python "$SCRIPT_DIR/stub_agents/stub_alerts.py" &
echo $! >> "$PIDS_FILE"
log "alerts stub    → :8001 (PID $!)"

python "$SCRIPT_DIR/stub_agents/stub_planner.py" &
echo $! >> "$PIDS_FILE"
log "planner stub   → :8002 (PID $!)"

python "$SCRIPT_DIR/stub_agents/stub_stopfinder.py" &
echo $! >> "$PIDS_FILE"
log "stopfinder stub→ :8003 (PID $!)"

sleep 1

# ── Authoritative Nameservers (:8300-8302) ───────────────────────────────────
echo ""
echo "▶ Starting Authoritative Nameservers..."
python "$SCRIPT_DIR/authoritative_ns/alerts_auth_ns.py" &
echo $! >> "$PIDS_FILE"
log "alerts   auth-ns → :8300 (PID $!)"

python "$SCRIPT_DIR/authoritative_ns/planner_auth_ns.py" &
echo $! >> "$PIDS_FILE"
log "planner  auth-ns → :8301 (PID $!)"

python "$SCRIPT_DIR/authoritative_ns/stopfinder_auth_ns.py" &
echo $! >> "$PIDS_FILE"
log "stopfinder auth-ns → :8302 (PID $!)"

sleep 1

# ── Local Registry + Namespace Servers (:6900) ──────────────────────────────
echo ""
echo "▶ Starting Local Registry (with TLD + App namespace endpoints)..."
cd "$SCRIPT_DIR/registry"
python local_registry.py &
echo $! >> "$PIDS_FILE"
log "registry + namespaces → :6900 (PID $!)"
cd "$REPO_ROOT"

sleep 1

# ── Recursive Resolver (:8200) ───────────────────────────────────────────────
echo ""
echo "▶ Starting Recursive Resolver..."
cd "$SCRIPT_DIR"
python -m uvicorn recursive_resolver.resolver:app --host 0.0.0.0 --port 8200 --log-level info &
echo $! >> "$PIDS_FILE"
log "recursive resolver → :8200 (PID $!)"
cd "$REPO_ROOT"

sleep 2

# ── Summary ──────────────────────────────────────────────────────────────────
echo ""
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║                  All services running!                       ║"
echo "╠══════════════════════════════════════════════════════════════╣"
echo "║  Stub agents      :8001  :8002  :8003                        ║"
echo "║  Auth NS          :8300  :8301  :8302                        ║"
echo "║  Registry         :6900                                      ║"
echo "║  Recursive Resolver :8200                                    ║"
echo "╠══════════════════════════════════════════════════════════════╣"
echo "║  Test the chain:  bash prototype/test_resolution.sh          ║"
echo "╠══════════════════════════════════════════════════════════════╣"
echo "║  Start Exchange with ANS:                                    ║"
echo "║    ANS_ENABLED=true \\                                         ║"
echo "║    REGISTRY_URL=http://localhost:6900 \\                       ║"
echo "║    python src/exchange_agent/exchange_server.py              ║"
echo "╠══════════════════════════════════════════════════════════════╣"
echo "║  Stop all:  bash prototype/stop_all.sh                       ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""
