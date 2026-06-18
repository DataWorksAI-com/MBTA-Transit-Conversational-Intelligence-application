#!/usr/bin/env bash
# ============================================================================
# Deploy the EU-Central fares node: MBTA fare & accessibility A2A agent
# (50054), in Frankfurt. Idempotent — re-running reuses the Linode (by label).
#
#   bash deploy/60-fares-frankfurt.sh
#
# Requires REGISTRY_IP in state.env (deploy 10-registry first). AGENTS_IP is
# used for the optional auth-ns update if present. Captures FARES_FFM_IP.
# ============================================================================
. "$(dirname "${BASH_SOURCE[0]}")/_lib.sh"
load_config
require_state REGISTRY_IP

KEY="$(ensure_ssh_key "$LABEL_FARES_FFM")"
FW="$(ensure_firewall "${LABEL_FARES_FFM}-fw" "50054")"
read -r ID IP < <(ensure_linode "$LABEL_FARES_FFM" "$TYPE_FARES" "$REGION_EU" "$FW" "${KEY}.pub")
state_set FARES_FFM_IP "$IP"
wait_ssh "$IP" "$KEY"

log "packaging fares agent"
TARBALL="/tmp/${LABEL_FARES_FFM}.tar.gz"
pack "$TARBALL" deploy/apps/fares
scp_to "$IP" "$KEY" "$TARBALL" "/tmp/fares.tar.gz"

log "provisioning $IP (python + venv + code)"
ssh_run "$IP" "$KEY" <<'REMOTE'
set -e
export DEBIAN_FRONTEND=noninteractive
apt-get update -y >/dev/null 2>&1
apt-get install -y python3 python3-venv python3-pip supervisor curl >/dev/null 2>&1
rm -rf /tmp/fares-extract && mkdir -p /tmp/fares-extract
tar -xzf /tmp/fares.tar.gz -C /tmp/fares-extract && rm /tmp/fares.tar.gz
mkdir -p /opt/mbta-fares
cp -r /tmp/fares-extract/deploy/apps/fares/. /opt/mbta-fares/
rm -rf /tmp/fares-extract
cd /opt/mbta-fares
python3 -m venv venv
venv/bin/pip install --upgrade pip >/dev/null 2>&1
venv/bin/pip install -r requirements.txt >/dev/null 2>&1
echo "✓ code + deps installed"
REMOTE

# Per-node identity / wiring consumed by the supervisor template (no secrets,
# no hardcoded IPs — REGISTRY_IP/AGENTS_IP come from state.env via the lib).
export FARES_PUBLIC_IP="$IP"
export FARES_AGENT_ID="mbta-fares-frankfurt"
export FARES_REGION="eu-central"
export FARES_REGION_LABEL="Frankfurt, DE"
export FARES_FLAG="\U0001f1e9\U0001f1ea"
export FARES_DESCRIPTION="MBTA Fare & Accessibility specialist — EU-Central node"
export FARES_AUTH_NS_URL="${AGENTS_IP:+http://$AGENTS_IP:8300}"

log "rendering + installing supervisor config (registry=$REGISTRY_IP)"
TMP="$(mktemp -d)"
render "$DEPLOY_DIR/templates/fares/mbta-fares.conf" > "$TMP/mbta-fares.conf"
scp_to "$IP" "$KEY" "$TMP/." "/etc/supervisor/conf.d/"
rm -rf "$TMP"

ssh_run "$IP" "$KEY" <<'REMOTE'
set -e
supervisorctl reread
supervisorctl update
supervisorctl restart mbta-fares || supervisorctl start mbta-fares || true
sleep 5
supervisorctl status mbta-fares
REMOTE

ok "fares (EU-Central / Frankfurt) deployed @ $IP"
echo "   agent http://$IP:50054"
echo "   test:  curl http://$IP:50054/.well-known/agent.json"
