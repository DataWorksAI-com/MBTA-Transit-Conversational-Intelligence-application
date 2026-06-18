"""
Run this on the Frankfurt server (85.90.246.180) as root:
  cd /root/foreign_agent && python3 setup_supervisor.py
"""
import os, subprocess, sys

OPENAI_KEY = os.getenv("OPENAI_API_KEY", "")  # set via env / config.env — never hardcode

CONF = f"""[program:mbta-fares]
command=/root/foreign_agent/venv/bin/python /root/foreign_agent/slim_wrapper.py
directory=/root/foreign_agent
autostart=true
autorestart=true
stderr_logfile=/var/log/mbta-fares.err.log
stdout_logfile=/var/log/mbta-fares.out.log
environment=OPENAI_API_KEY="{OPENAI_KEY}",PUBLIC_IP="85.90.246.180",AGENT_HOST="0.0.0.0",AGENT_PORT="50054",AGENT_ID="mbta-fares",ANS_LABEL="fares",ANS_TLD="agents.dataworksai.com",ANS_APP="mbta-transit-ci",REGISTRY_URL="http://97.107.132.213:6900",AUTH_NS_URL="http://96.126.111.107:8300"
"""

with open("/etc/supervisor/conf.d/mbta-fares.conf", "w") as f:
    f.write(CONF)
print("Wrote supervisor config")

subprocess.run(["supervisorctl", "reread"], check=True)
subprocess.run(["supervisorctl", "update"], check=True)
try:
    subprocess.run(["supervisorctl", "stop", "mbta-fares"], check=False)
except: pass
subprocess.run(["supervisorctl", "start", "mbta-fares"], check=True)

import time; time.sleep(3)
result = subprocess.run(["supervisorctl", "status", "mbta-fares"], capture_output=True, text=True)
print(result.stdout)
