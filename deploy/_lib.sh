#!/usr/bin/env bash
# ============================================================================
# Shared deploy library for the MBTA stack.
# Sourced by every service script (10-registry.sh, 20-agents.sh, ...).
#
# Responsibilities:
#   - load central config (config.env) + captured-IP state (state.env)
#   - idempotent Linode create-or-reuse (by label) + firewall + ssh key
#   - wait for boot / ssh, capture the public IP, write it back to state.env
#   - scp code + run remote bash
#   - render supervisor templates with the current IPs (envsubst)
#
# Nothing here is service-specific. Each service script supplies its own
# packaging, packages, supervisor templates, and cross-host wiring.
# ============================================================================
set -euo pipefail

DEPLOY_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$DEPLOY_DIR/.." && pwd)"
CONFIG_FILE="$DEPLOY_DIR/config.env"
STATE_FILE="$DEPLOY_DIR/state.env"

# ── pretty logging ──────────────────────────────────────────────────────────
log()  { printf '\033[36m▸ %s\033[0m\n' "$*"; }
ok()   { printf '\033[32m✓ %s\033[0m\n' "$*"; }
warn() { printf '\033[33m! %s\033[0m\n' "$*"; }
die()  { printf '\033[31m✗ %s\033[0m\n' "$*" >&2; exit 1; }

# ── config + state ────────────────────────────────────────────────────────-
load_config() {
  [ -f "$CONFIG_FILE" ] || die "Missing $CONFIG_FILE — copy config.env.example to config.env and fill it in."
  # shellcheck disable=SC1090
  set -a; . "$CONFIG_FILE"; set +a
  command -v linode-cli >/dev/null 2>&1 || die "linode-cli not found. Install it and run: linode-cli configure"
  command -v envsubst   >/dev/null 2>&1 || die "envsubst not found (install gettext)."
  [ -f "$STATE_FILE" ] || : > "$STATE_FILE"
  # shellcheck disable=SC1090
  set -a; . "$STATE_FILE"; set +a
}

# state_set KEY VALUE — persist a captured IP (or any value) to state.env and export it
state_set() {
  local key="$1" val="$2"
  touch "$STATE_FILE"
  grep -v -E "^${key}=" "$STATE_FILE" > "${STATE_FILE}.tmp" 2>/dev/null || true
  echo "${key}=\"${val}\"" >> "${STATE_FILE}.tmp"
  mv "${STATE_FILE}.tmp" "$STATE_FILE"
  export "${key}=${val}"
  ok "state: ${key}=${val}"
}

# require_state KEY [KEY...] — fail if a needed upstream IP isn't captured yet
require_state() {
  local k
  for k in "$@"; do
    [ -n "${!k:-}" ] || die "Required value '$k' not in state.env yet. Deploy its host first (see up.sh order)."
  done
}

# ── ssh key (one per service label) ─────────────────────────────────────────
ensure_ssh_key() {            # ensure_ssh_key <label>  -> echoes private-key path
  local label="$1" path="$DEPLOY_DIR/keys/$1"
  mkdir -p "$DEPLOY_DIR/keys"
  if [ ! -f "${path}.pub" ]; then
    ssh-keygen -t ed25519 -f "$path" -N "" -C "$label" >/dev/null 2>&1
  fi
  echo "$path"
}

# ── firewall (create-or-reuse by label) ─────────────────────────────────────
ensure_firewall() {           # ensure_firewall <label> <ports-csv>  -> echoes firewall id
  local label="$1" ports="$2" fid rules rule
  fid="$(linode-cli firewalls list --text --no-headers --format='id,label' 2>/dev/null | awk -v l="$label" '$2==l{print $1}')"
  if [ -n "$fid" ]; then echo "$fid"; return; fi
  rules='[{"protocol":"TCP","ports":"22","addresses":{"ipv4":["0.0.0.0/0"]},"action":"ACCEPT"}'
  local IFS=','; for rule in $ports; do
    rules="$rules,{\"protocol\":\"TCP\",\"ports\":\"$rule\",\"addresses\":{\"ipv4\":[\"0.0.0.0/0\"]},\"action\":\"ACCEPT\"}"
  done
  rules="$rules]"
  linode-cli firewalls create --label "$label" \
    --rules.inbound_policy DROP --rules.outbound_policy ACCEPT \
    --rules.inbound "$rules" >/dev/null
  linode-cli firewalls list --text --no-headers --format='id,label' | awk -v l="$label" '$2==l{print $1}'
}

# ── linode create-or-reuse (idempotent by label) ────────────────────────────
# Echoes "<instance_id> <public_ip>". Reuses an existing instance with the same
# label (so redeploy never duplicates); otherwise creates a fresh one.
ensure_linode() {             # ensure_linode <label> <type> <region> <fw_id> <ssh_pub_path>
  local label="$1" type="$2" region="$3" fid="$4" pub="$5" id ip
  id="$(linode-cli linodes list --text --no-headers --format='id,label' 2>/dev/null | awk -v l="$label" '$2==l{print $1}')"
  if [ -n "$id" ]; then
    warn "reusing existing Linode '$label' (id $id)"
  else
    log "creating Linode '$label' ($type / $region)"
    id="$(linode-cli linodes create \
      --type "$type" --region "$region" --image "$LINODE_IMAGE" \
      --label "$label" --tags MBTA \
      --root_pass "$(openssl rand -base64 32 | tr -d '=+/' | cut -c1-25)" \
      --authorized_keys "$(cat "$pub")" \
      --firewall_id "$fid" \
      --text --no-headers --format='id')"
  fi
  while [ "$(linode-cli linodes view "$id" --text --no-headers --format='status')" != "running" ]; do sleep 5; done
  ip="$(linode-cli linodes view "$id" --text --no-headers --format='ipv4' | awk '{print $1}')"
  echo "$id $ip"
}

# ── remote helpers ──────────────────────────────────────────────────────────
wait_ssh() {                  # wait_ssh <ip> <key>
  local ip="$1" key="$2" i
  for i in $(seq 1 60); do
    ssh -i "$key" -o StrictHostKeyChecking=no -o ConnectTimeout=5 "root@$ip" "echo ok" >/dev/null 2>&1 && { ok "ssh ready ($ip)"; return; }
    sleep 5
  done
  die "ssh timeout for $ip"
}
scp_to()  { scp -i "$2" -o StrictHostKeyChecking=no -o ServerAliveInterval=30 -r "$3" "root@$1:$4"; }   # scp_to <ip> <key> <src> <dst>
ssh_run() { ssh -i "$2" -o StrictHostKeyChecking=no "root@$1" "bash -s"; }                              # ssh_run <ip> <key>  (script on stdin)

# ── supervisor template rendering ───────────────────────────────────────────
# Renders deploy/templates/<name> with the current config+state env vars
# substituted (${REGISTRY_IP} etc.). Secrets stay as %(ENV_*)s for supervisor.
render() {                    # render <template-path>  -> stdout
  envsubst < "$1"
}

# ── packaging ───────────────────────────────────────────────────────────────
pack() {                      # pack <tarball> <path...>  (from REPO_DIR, excludes junk)
  local out="$1"; shift
  tar -czf "$out" -C "$REPO_DIR" \
    --exclude='__pycache__' --exclude='*.pyc' --exclude='.pytest_cache' --exclude='.git' \
    "$@"
}
