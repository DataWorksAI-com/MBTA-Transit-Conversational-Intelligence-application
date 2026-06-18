#!/usr/bin/env bash
# ============================================================================
# Bring the whole MBTA stack up, in dependency order, auto-wiring IPs as it goes.
#   bash deploy/up.sh            # all services
#   bash deploy/up.sh agents     # one service (must already have its deps in state.env)
#
# Order matters: each step captures its IP into state.env so later steps wire to it.
#   registry -> observability -> agents -> fares(nj,ffm) -> exchange -> register
# Re-running is safe: every step reuses its Linode by label (no duplicates).
# ============================================================================
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

run() { echo; echo "==================== $1 ===================="; bash "$1"; }

declare -A STEP=(
  [registry]=10-registry.sh
  [observability]=40-observability.sh
  [agents]=20-agents.sh
  [fares-nj]=50-fares-nj.sh
  [fares-frankfurt]=60-fares-frankfurt.sh
  [exchange]=30-exchange.sh
)
ORDER=(registry observability agents fares-nj fares-frankfurt exchange)

if [ $# -gt 0 ]; then
  [ -n "${STEP[$1]:-}" ] || { echo "unknown service '$1'. one of: ${ORDER[*]}"; exit 1; }
  run "${STEP[$1]}"; exit 0
fi

for s in "${ORDER[@]}"; do
  if [ -f "${STEP[$s]}" ]; then run "${STEP[$s]}"; else echo "(skip $s — ${STEP[$s]} not present yet)"; fi
done

if [ -f register-agents.sh ]; then run register-agents.sh; fi
echo; echo "✓ stack up. state:"; cat state.env
