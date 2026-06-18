#!/usr/bin/env bash
# ============================================================================
# Deploy the Northeastern registry host: registry API (6900) + agent-facts
# (8000) behind an nginx :80 proxy that also serves the dashboard UI.
# Idempotent — re-running reuses the same Linode (by label).
#
#   bash deploy/10-registry.sh
#
# No upstream deps (needs MONGODB_URI from config.env).
# Captures REGISTRY_IP into state.env for every other host to consume.
# AUTH_NS_URL points at the agents host (AGENTS_IP) — may be empty on the
# first deploy (registry comes up before agents); that's fine.
# ============================================================================
. "$(dirname "${BASH_SOURCE[0]}")/_lib.sh"
load_config

[ -n "${MONGODB_URI:-}" ] || die "MONGODB_URI not set in config.env"

KEY="$(ensure_ssh_key "$LABEL_REGISTRY")"
FW="$(ensure_firewall "${LABEL_REGISTRY}-fw" "80,6900,8000")"
read -r ID IP < <(ensure_linode "$LABEL_REGISTRY" "$TYPE_REGISTRY" "$REGION_US" "$FW" "${KEY}.pub")
state_set REGISTRY_IP "$IP"
wait_ssh "$IP" "$KEY"

log "packaging registry app"
TARBALL="/tmp/${LABEL_REGISTRY}.tar.gz"
pack "$TARBALL" deploy/apps/registry
scp_to "$IP" "$KEY" "$TARBALL" "/tmp/registry.tar.gz"

log "provisioning $IP (python + venv + nginx + supervisor)"
ssh_run "$IP" "$KEY" <<'REMOTE'
set -e
export DEBIAN_FRONTEND=noninteractive
apt-get update -y >/dev/null 2>&1
apt-get install -y python3 python3-venv python3-pip supervisor nginx >/dev/null 2>&1

# dedicated unprivileged user the registry runs as
if ! id -u ubuntu >/dev/null 2>&1; then
  useradd -m -s /bin/bash ubuntu
  mkdir -p /home/ubuntu/.ssh
  cp /root/.ssh/authorized_keys /home/ubuntu/.ssh/authorized_keys 2>/dev/null || true
  chown -R ubuntu:ubuntu /home/ubuntu/.ssh
  chmod 700 /home/ubuntu/.ssh
  chmod 600 /home/ubuntu/.ssh/authorized_keys 2>/dev/null || true
fi

# unpack app into /home/ubuntu/Northeastern-registry
rm -rf /tmp/registry-extract && mkdir -p /tmp/registry-extract
tar -xzf /tmp/registry.tar.gz -C /tmp/registry-extract && rm /tmp/registry.tar.gz
mkdir -p /home/ubuntu/Northeastern-registry
cp -r /tmp/registry-extract/deploy/apps/registry/. /home/ubuntu/Northeastern-registry/
rm -rf /tmp/registry-extract

cd /home/ubuntu/Northeastern-registry
python3 -m venv .venv
.venv/bin/pip install --upgrade pip >/dev/null 2>&1
.venv/bin/pip install flask flask-cors pymongo >/dev/null 2>&1
chown -R ubuntu:ubuntu /home/ubuntu/Northeastern-registry

# nginx :80 -> :6900 proxy + dashboard
cp /home/ubuntu/Northeastern-registry/nginx.conf /etc/nginx/sites-available/registry
ln -sf /etc/nginx/sites-available/registry /etc/nginx/sites-enabled/
rm -f /etc/nginx/sites-enabled/default
chmod 755 /home/ubuntu
chmod 755 /home/ubuntu/Northeastern-registry
chmod 644 /home/ubuntu/Northeastern-registry/registry-ui.html

systemctl enable supervisor nginx >/dev/null 2>&1
systemctl start supervisor nginx >/dev/null 2>&1
echo "✓ code + deps installed"
REMOTE

log "rendering + installing supervisor config (MONGODB_URI / AUTH_NS_URL=http://${AGENTS_IP:-}:8300)"
TMP="$(mktemp -d)"
render "$DEPLOY_DIR/templates/registry/northeastern-registry.conf" > "$TMP/northeastern-registry.conf"
scp_to "$IP" "$KEY" "$TMP/." "/etc/supervisor/conf.d/"
rm -rf "$TMP"

ssh_run "$IP" "$KEY" <<'REMOTE'
set -e
supervisorctl reread
supervisorctl update
supervisorctl restart all || true
nginx -t && systemctl restart nginx
sleep 8
supervisorctl status
REMOTE

ok "registry deployed @ $IP"
echo "   dashboard http://$IP    registry http://$IP:6900    facts :8000"
echo "   test:  curl http://$IP:6900/health"
