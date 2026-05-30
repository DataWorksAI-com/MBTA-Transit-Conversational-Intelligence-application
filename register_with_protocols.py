"""
Re-register MBTA agents with full protocol metadata for Protocol Intelligence.
This makes DANS properly negotiate protocols for each agent.

Run: python register_with_protocols.py
"""
import urllib.request, json, sys

DANS = "http://97.107.132.213/dans"
AGENT_HOST = "96.126.111.107"
FARES_HOST = "50.116.57.161"

AGENTS = [
    {
        "label": "alerts",
        "endpoint": f"http://{AGENT_HOST}:8001",
        "protocols": ["a2a", "slim", "http"],
        "protocol_metadata": {
            "a2a":  {"version": "0.2.1", "path": "/a2a/message"},
            "slim": {"identity": "mbta-transit-ci/alerts"},
            "http": {"path": "/chat"},
        },
        "region": "us-east",
        "region_label": "Boston, MA",
        "flag": "🇺🇸",
    },
    {
        # Planner is a real Google A2A agent — serves JSON-RPC message/send on / (port 50052).
        # It does NOT have a /a2a/message custom endpoint, so path must be "/" + google_a2a format.
        "label": "planner",
        "endpoint": f"http://{AGENT_HOST}:50052",
        "protocols": ["a2a", "http"],
        "protocol_metadata": {
            "a2a":  {"version": "0.3.0", "path": "/", "format": "google_a2a"},
            "http": {"path": "/"},
        },
        "region": "us-east",
        "region_label": "Boston, MA",
        "flag": "🇺🇸",
    },
    {
        "label": "stopfinder",
        "endpoint": f"http://{AGENT_HOST}:8003",
        "protocols": ["a2a", "slim", "http"],
        "protocol_metadata": {
            "a2a":  {"version": "0.2.1", "path": "/a2a/message"},
            "slim": {"identity": "mbta-transit-ci/stopfinder"},
            "http": {"path": "/chat"},
        },
        "region": "us-east",
        "region_label": "Boston, MA",
        "flag": "🇺🇸",
    },
    {
        "label": "fares",
        "endpoint": f"http://{FARES_HOST}:50054",
        "protocols": ["a2a", "http"],
        "protocol_metadata": {
            # Fares is a real Google A2A agent — listens on / with JSON-RPC message/send
            "a2a":  {"version": "0.2.1", "path": "/", "format": "google_a2a"},
            "http": {"path": "/"},
        },
        "region": "us-east",
        "region_label": "Boston, MA",
        "flag": "US",
    },
    {
        # Frankfurt replica — same agent, same protocol, different region for failover
        "label": "fares",
        "endpoint": "http://85.90.246.180:50054",
        "protocols": ["a2a", "http"],
        "protocol_metadata": {
            "a2a":  {"version": "0.2.1", "path": "/", "format": "google_a2a"},
            "http": {"path": "/"},
        },
        "region": "eu-central",
        "region_label": "Frankfurt, DE",
        "flag": "DE",
    },
]

print(f"Re-registering {len(AGENTS)} MBTA agents with protocol metadata...\n")
for agent in AGENTS:
    req = urllib.request.Request(
        DANS + "/register",
        data=json.dumps(agent).encode(),
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            d = json.loads(r.read())
        print(f"  ✅ {agent['label']:12s} → {d['status']:10s} protocols={d.get('protocols')}")
    except Exception as e:
        print(f"  ❌ {agent['label']}: {e}")

print("\nDone. Verify with:")
print(f"  python check_resolve.py {DANS}")
