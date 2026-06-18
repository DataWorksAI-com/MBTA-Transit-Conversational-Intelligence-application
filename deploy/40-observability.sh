#!/usr/bin/env bash
# ============================================================================
# Deploy the observability host: Jaeger (16686), Grafana (3001),
# ClickHouse (8123/9000), OTEL Collector (4317 gRPC / 4318 HTTP), via docker.
# Idempotent — re-running reuses the same Linode (by label).
#
#   bash deploy/40-observability.sh
#
# No upstream deps. Captures OBS_IP into state.env so agents/exchange can
# point their OTEL exporter at it (OTEL_ENDPOINT=http://$OBS_IP:4317).
# ============================================================================
. "$(dirname "${BASH_SOURCE[0]}")/_lib.sh"
load_config

KEY="$(ensure_ssh_key "$LABEL_OBS")"
FW="$(ensure_firewall "${LABEL_OBS}-fw" "16686,3001,8123,9000,4317,4318")"
read -r ID IP < <(ensure_linode "$LABEL_OBS" "$TYPE_OBS" "$REGION_US" "$FW" "${KEY}.pub")
state_set OBS_IP "$IP"
wait_ssh "$IP" "$KEY"

log "packaging observability stack (docker-compose + otel config)"
TARBALL="/tmp/${LABEL_OBS}.tar.gz"
pack "$TARBALL" deploy/apps/observability
scp_to "$IP" "$KEY" "$TARBALL" "/tmp/observability.tar.gz"

log "provisioning $IP (docker + compose, then up -d)"
ssh_run "$IP" "$KEY" <<'REMOTE'
set -e
export DEBIAN_FRONTEND=noninteractive
apt-get update -y >/dev/null 2>&1

# Install Docker (engine + compose plugin)
if ! command -v docker >/dev/null 2>&1; then
  curl -fsSL https://get.docker.com | sh >/dev/null 2>&1
fi
curl -SL https://github.com/docker/compose/releases/download/v2.24.0/docker-compose-linux-x86_64 \
    -o /usr/local/bin/docker-compose >/dev/null 2>&1
chmod +x /usr/local/bin/docker-compose
systemctl enable docker >/dev/null 2>&1
systemctl start docker >/dev/null 2>&1

# Unpack stack into /opt/observability
rm -rf /tmp/obs-extract && mkdir -p /tmp/obs-extract
tar -xzf /tmp/observability.tar.gz -C /tmp/obs-extract && rm /tmp/observability.tar.gz
mkdir -p /opt/observability
cp -r /tmp/obs-extract/deploy/apps/observability/. /opt/observability/
rm -rf /tmp/obs-extract

cd /opt/observability
docker compose up -d 2>/dev/null || docker-compose up -d
echo "   waiting for containers..."
sleep 15
docker ps --format "table {{.Names}}\t{{.Status}}"
echo "✓ observability stack up"
REMOTE

ok "observability deployed @ $IP"
echo "   Jaeger http://$IP:16686  Grafana http://$IP:3001 (admin/admin)  ClickHouse :8123"
echo "   OTLP   gRPC http://$IP:4317   HTTP http://$IP:4318"
echo "   test:  curl http://$IP:16686"
