#!/usr/bin/env bash
# ============================================================================
# Deploy the exchange host: exchange agent (8100) + recursive ANS resolver
# (8200) + chat frontend (3000). Idempotent — re-running reuses the Linode.
#
#   bash deploy/30-exchange.sh
#
# Requires REGISTRY_IP + AGENTS_IP in state.env (deploy 10-registry and
# 20-agents first). OBS_IP is optional — if present, OTEL tracing is enabled.
# Captures EXCHANGE_IP into state.env (the resolver wires to itself at :8200).
# ============================================================================
. "$(dirname "${BASH_SOURCE[0]}")/_lib.sh"
load_config
require_state REGISTRY_IP AGENTS_IP

KEY="$(ensure_ssh_key "$LABEL_EXCHANGE")"
FW="$(ensure_firewall "${LABEL_EXCHANGE}-fw" "3000,8100,8200")"
read -r ID IP < <(ensure_linode "$LABEL_EXCHANGE" "$TYPE_EXCHANGE" "$REGION_US" "$FW" "${KEY}.pub")
state_set EXCHANGE_IP "$IP"
wait_ssh "$IP" "$KEY"

# OTEL endpoint only if observability is up (else empty → no tracing, no crash)
export OTEL_ENDPOINT="${OBS_IP:+http://$OBS_IP:4317}"

log "packaging src/ + ans/ + docker/"
TARBALL="/tmp/${LABEL_EXCHANGE}.tar.gz"
pack "$TARBALL" src ans docker
scp_to "$IP" "$KEY" "$TARBALL" "/tmp/exchange.tar.gz"

log "provisioning $IP (packages + venv + code)"
ssh_run "$IP" "$KEY" <<'REMOTE'
set -e
export DEBIAN_FRONTEND=noninteractive
apt-get update -y >/dev/null 2>&1
apt-get install -y software-properties-common >/dev/null 2>&1
add-apt-repository -y ppa:deadsnakes/ppa >/dev/null 2>&1
apt-get update -y >/dev/null 2>&1
apt-get install -y python3.11 python3.11-venv python3.11-dev python3-pip git supervisor >/dev/null 2>&1
mkdir -p /opt/mbta-agentcy && cd /opt/mbta-agentcy
tar -xzf /tmp/exchange.tar.gz && rm /tmp/exchange.tar.gz
python3.11 -m venv venv
. venv/bin/activate
pip install --upgrade pip >/dev/null 2>&1
pip install fastapi uvicorn httpx openai scikit-learn numpy pydantic \
    python-dotenv websockets requests langgraph langchain-core \
    opentelemetry-api opentelemetry-sdk opentelemetry-exporter-otlp \
    opentelemetry-instrumentation-fastapi >/dev/null 2>&1
pip install git+https://github.com/cubismod/mbta-mcp.git >/dev/null 2>&1
echo "✓ code + deps installed"
REMOTE

log "rendering + installing supervisor configs (registry=$REGISTRY_IP agents=$AGENTS_IP exchange=$IP)"
TMP="$(mktemp -d)"
for f in mbta-exchange mbta-resolver mbta-frontend; do
  render "$DEPLOY_DIR/templates/exchange/$f.conf" > "$TMP/$f.conf"
done
scp_to "$IP" "$KEY" "$TMP/." "/etc/supervisor/conf.d/"
rm -rf "$TMP"

ssh_run "$IP" "$KEY" <<'REMOTE'
set -e
supervisorctl reread
supervisorctl update
supervisorctl restart all || true
sleep 10
supervisorctl status
REMOTE

ok "exchange deployed @ $IP"
echo "   exchange http://$IP:8100  resolver :8200  frontend http://$IP:3000"
echo "   test:  curl http://$IP:8100/"
