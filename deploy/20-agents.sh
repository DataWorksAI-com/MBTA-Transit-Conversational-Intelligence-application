#!/usr/bin/env bash
# ============================================================================
# Deploy the MBTA agents host: alerts (8001), planner (8002), stopfinder (8003)
# + auth-ns (8300). Idempotent — re-running reuses the same Linode (by label).
#
#   bash deploy/20-agents.sh
#
# Requires REGISTRY_IP in state.env (deploy 10-registry.sh first).
# Captures AGENTS_IP into state.env for the exchange + fares to consume.
# ============================================================================
. "$(dirname "${BASH_SOURCE[0]}")/_lib.sh"
load_config
require_state REGISTRY_IP

KEY="$(ensure_ssh_key "$LABEL_AGENTS")"
FW="$(ensure_firewall "${LABEL_AGENTS}-fw" "8001,8002,8003,8300,50051,50052,50053,46357")"
read -r ID IP < <(ensure_linode "$LABEL_AGENTS" "$TYPE_AGENTS" "$REGION_US" "$FW" "${KEY}.pub")
state_set AGENTS_IP "$IP"
wait_ssh "$IP" "$KEY"

# OTEL endpoint only if observability is up (else empty → no tracing, no crash)
export OTEL_ENDPOINT="${OBS_IP:+http://$OBS_IP:4317}"

log "packaging agents/ + ans/"
TARBALL="/tmp/${LABEL_AGENTS}.tar.gz"
pack "$TARBALL" agents ans
scp_to "$IP" "$KEY" "$TARBALL" "/tmp/agents.tar.gz"

log "provisioning $IP (packages + venv + code)"
ssh_run "$IP" "$KEY" <<'REMOTE'
set -e
export DEBIAN_FRONTEND=noninteractive
apt-get update -y >/dev/null 2>&1
apt-get install -y software-properties-common >/dev/null 2>&1
add-apt-repository -y ppa:deadsnakes/ppa >/dev/null 2>&1
apt-get update -y >/dev/null 2>&1
apt-get install -y python3.11 python3.11-venv python3.11-dev python3-pip supervisor >/dev/null 2>&1
mkdir -p /opt/mbta-agents && cd /opt/mbta-agents
tar -xzf /tmp/agents.tar.gz && rm /tmp/agents.tar.gz
python3.11 -m venv venv
. venv/bin/activate
pip install --upgrade pip >/dev/null 2>&1
pip install fastapi uvicorn httpx openai pydantic python-dotenv requests \
    opentelemetry-api opentelemetry-sdk opentelemetry-exporter-otlp \
    opentelemetry-instrumentation-fastapi >/dev/null 2>&1
echo "✓ code + deps installed"
REMOTE

log "rendering + installing supervisor configs (wiring -> REGISTRY_IP=$REGISTRY_IP)"
TMP="$(mktemp -d)"
for f in mbta-alerts mbta-planner mbta-stopfinder mbta-auth-ns; do
  render "$DEPLOY_DIR/templates/agents/$f.conf" > "$TMP/$f.conf"
done
scp_to "$IP" "$KEY" "$TMP/." "/etc/supervisor/conf.d/"
rm -rf "$TMP"

ssh_run "$IP" "$KEY" <<'REMOTE'
set -e
supervisorctl reread
supervisorctl update
supervisorctl restart all || true
sleep 8
supervisorctl status
REMOTE

ok "agents deployed @ $IP"
echo "   alerts http://$IP:8001  planner http://$IP:8002  stopfinder http://$IP:8003  auth-ns :8300"
echo "   test:  curl http://$IP:8001/health"
