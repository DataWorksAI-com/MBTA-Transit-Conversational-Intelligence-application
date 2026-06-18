"""
Insert the Prompt Firewall nginx location blocks after the /dans/ block.

Splits /firewall/ into two locations so the firewall ADMIN routes
(/firewall/rules, /firewall/stats, /firewall/test) are reachable as well as
the DATA plane (/firewall/proxy/<label>). nginx matches the longest prefix
first, so /firewall/proxy/... hits the data-plane location and everything
else hits the admin location.

Canonical copy of these blocks lives in the agent-registry repo:
  deploy/nginx-dans-firewall.conf

Usage (on the DANS host):  python3 nginx_patch_firewall.py && nginx -t && systemctl reload nginx
"""
import re, sys

p = "/etc/nginx/sites-enabled/registry"
s = open(p).read()

if "location /firewall/proxy/" in s:
    print("already split — no change")
    sys.exit(0)

# Remove any pre-existing single-location /firewall/ block (older deploys).
s = re.sub(r"\n[ \t]*location /firewall/ \{.*?\n[ \t]*\}\n", "\n", s, flags=re.S)

block = """    location /firewall/proxy/ {
        proxy_pass         http://127.0.0.1:8300/proxy/;
        proxy_set_header   Host $host;
        proxy_set_header   X-Real-IP $remote_addr;
        proxy_read_timeout 60;
        add_header         Access-Control-Allow-Origin * always;
        add_header         Access-Control-Allow-Methods "GET, POST, PUT, DELETE, OPTIONS" always;
        add_header         Access-Control-Allow-Headers "Content-Type, X-API-Key" always;
    }

    location /firewall/ {
        proxy_pass         http://127.0.0.1:8300/firewall/;
        proxy_set_header   Host $host;
        proxy_set_header   X-Real-IP $remote_addr;
        proxy_read_timeout 60;
        add_header         Access-Control-Allow-Origin * always;
        add_header         Access-Control-Allow-Methods "GET, POST, PUT, DELETE, OPTIONS" always;
        add_header         Access-Control-Allow-Headers "Content-Type, X-API-Key" always;
    }
"""

m = re.search(r"location /dans/ \{.*?\n    \}", s, re.S)
if not m:
    print("ERROR: /dans block not found"); sys.exit(1)
idx = m.end()
open(p + ".bak", "w").write(s)          # backup
s = s[:idx] + "\n\n" + block + s[idx:]
open(p, "w").write(s)
print("inserted /firewall/proxy/ + /firewall/ blocks (backup at registry.bak)")
