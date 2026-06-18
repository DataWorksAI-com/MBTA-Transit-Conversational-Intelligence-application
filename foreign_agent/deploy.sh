#!/bin/bash
# One-command deploy for MBTA Foreign Agent
# Run this on the Linode server as root:
#   bash deploy.sh YOUR_OPENAI_KEY

set -e

OPENAI_KEY="${1:-}"
if [ -z "$OPENAI_KEY" ]; then
  echo "Usage: bash deploy.sh YOUR_OPENAI_API_KEY"
  exit 1
fi

echo "=== Installing system deps ==="
apt-get update -qq
apt-get install -y python3 python3-pip python3-venv supervisor curl

echo "=== Setting up agent ==="
mkdir -p /opt/mbta-fares
cd /opt/mbta-fares

# Copy files (assumes you've scp'd slim_wrapper.py + requirements.txt here)
python3 -m venv venv
./venv/bin/pip install -q -r requirements.txt

echo "=== Detecting public IP ==="
PUBLIC_IP=$(curl -s https://api.ipify.org)
echo "Public IP: $PUBLIC_IP"

echo "=== Creating supervisor config ==="
cat > /etc/supervisor/conf.d/mbta-fares.conf << EOF
[program:mbta-fares]
command=/opt/mbta-fares/venv/bin/python /opt/mbta-fares/slim_wrapper.py
directory=/opt/mbta-fares
autostart=true
autorestart=true
stderr_logfile=/var/log/mbta-fares.err.log
stdout_logfile=/var/log/mbta-fares.out.log
environment=OPENAI_API_KEY="${OPENAI_KEY}",
            PUBLIC_IP="${PUBLIC_IP}",
            AGENT_HOST="0.0.0.0",
            AGENT_PORT="50054",
            AGENT_ID="mbta-fares",
            ANS_LABEL="fares",
            ANS_TLD="agents.dataworksai.com",
            ANS_APP="mbta-transit-ci",
            REGISTRY_URL="http://97.107.132.213:6900",
            AUTH_NS_URL="http://96.126.111.107:8300"
EOF

echo "=== Starting agent ==="
supervisorctl reread
supervisorctl update
supervisorctl start mbta-fares
sleep 4
supervisorctl status mbta-fares

echo ""
echo "=== DONE ==="
echo "Agent running at http://${PUBLIC_IP}:50054"
echo "Test: curl http://${PUBLIC_IP}:50054/.well-known/agent.json"
