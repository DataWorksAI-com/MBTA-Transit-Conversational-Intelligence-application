"""E2E test: send a chat query and verify Protocol Intelligence metadata in response."""
import urllib.request, json, sys

BASE = "http://50.116.53.133:8100"
QUERY = "are there any delays on the red line today?"

body = json.dumps({"query": QUERY}).encode()
req = urllib.request.Request(
    BASE + "/chat", data=body, method="POST",
    headers={"Content-Type": "application/json"}
)

print(f"POST {BASE}/chat")
print(f"query: {QUERY!r}\n")

try:
    with urllib.request.urlopen(req, timeout=30) as r:
        d = json.loads(r.read())
except Exception as e:
    print(f"ERROR: {e}")
    sys.exit(1)

print("=== RESPONSE (first 200 chars) ===")
print(d.get("response", "")[:200])
print()

meta = d.get("metadata", {})
print("=== PROTOCOL INTELLIGENCE ===")
print(f"  transport:      {meta.get('transport')}")
print(f"  ans_enabled:    {meta.get('ans_enabled')}")
print(f"  protocol_used:  {json.dumps(meta.get('protocol_used', {}))}")
print()

traces = meta.get("ans_traces", [])
print(f"=== ANS TRACES ({len(traces)}) ===")
for t in traces:
    agent = t.get("agent_id", "?")
    proto = t.get("protocol", "?")
    by    = t.get("negotiated_by", "?")
    cached = t.get("cached", False)
    lat   = t.get("latency_ms", 0)
    print(f"  {agent:16s}  protocol={proto:6s}  negotiated_by={by:14s}  cached={cached}  lat={lat}ms")
