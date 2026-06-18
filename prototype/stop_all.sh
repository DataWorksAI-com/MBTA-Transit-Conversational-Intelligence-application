#!/bin/bash
# ============================================================================
# stop_all.sh — Stop all ANS prototype services
#
# Usage: bash prototype/stop_all.sh
# ============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PIDS_FILE="$SCRIPT_DIR/.pids"

if [ ! -f "$PIDS_FILE" ]; then
    echo "No .pids file found. Services may not be running (started with run_all.sh)."
    echo "Attempting port-based cleanup anyway..."
else
    echo "Stopping services by PID..."
    while IFS= read -r pid; do
        if kill "$pid" 2>/dev/null; then
            echo "  Killed PID $pid"
        fi
    done < "$PIDS_FILE"
    rm -f "$PIDS_FILE"
fi

# Port-based cleanup as fallback (works on both Linux and Git Bash on Windows)
for port in 8001 8002 8003 8300 8301 8302 6900 8200; do
    # Try to find and kill process on this port (Linux/Mac)
    pid=$(lsof -ti :"$port" 2>/dev/null)
    if [ -n "$pid" ]; then
        kill "$pid" 2>/dev/null && echo "  Killed process on :$port (PID $pid)"
    fi
done

echo "Done. All prototype services stopped."
