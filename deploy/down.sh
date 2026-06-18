#!/usr/bin/env bash
# ============================================================================
# Tear the stack down: delete every MBTA Linode by label, then clear state.env.
#   bash deploy/down.sh              # delete ALL (prompts once)
#   bash deploy/down.sh agents       # delete just one
#   FORCE=1 bash deploy/down.sh      # no prompt
# Firewalls and SSH keys are left in place (reused on next up.sh).
# ============================================================================
set -euo pipefail
. "$(dirname "${BASH_SOURCE[0]}")/_lib.sh"
load_config

ALL_LABELS=("$LABEL_REGISTRY" "$LABEL_AGENTS" "$LABEL_EXCHANGE" "$LABEL_OBS" "$LABEL_FARES_NJ" "$LABEL_FARES_FFM")
declare -A ONE=(
  [registry]="$LABEL_REGISTRY" [agents]="$LABEL_AGENTS" [exchange]="$LABEL_EXCHANGE"
  [observability]="$LABEL_OBS" [fares-nj]="$LABEL_FARES_NJ" [fares-frankfurt]="$LABEL_FARES_FFM"
)

if [ $# -gt 0 ]; then
  [ -n "${ONE[$1]:-}" ] || { echo "unknown service '$1'"; exit 1; }
  LABELS=("${ONE[$1]}")
else
  LABELS=("${ALL_LABELS[@]}")
fi

if [ "${FORCE:-0}" != "1" ]; then
  echo "About to DELETE Linodes: ${LABELS[*]}"
  read -r -p "Type 'delete' to confirm: " ans
  [ "$ans" = "delete" ] || { echo "aborted."; exit 1; }
fi

for label in "${LABELS[@]}"; do
  id="$(linode-cli linodes list --text --no-headers --format='id,label' 2>/dev/null | awk -v l="$label" '$2==l{print $1}')"
  if [ -n "$id" ]; then
    linode-cli linodes delete "$id" && ok "deleted $label (id $id)"
  else
    warn "$label not found (already gone)"
  fi
done

# clear captured IPs so next up.sh starts clean
: > "$STATE_FILE"
ok "state.env cleared"
