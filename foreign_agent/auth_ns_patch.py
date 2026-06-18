"""
Patch script — appends /register_agent endpoint to generic_auth_ns.py
Run on the agents server: python3 auth_ns_patch.py
"""
PATCH = '''

# ── Dynamic agent registration (for foreign/remote agents) ────────────────────
@app.post("/register_agent", status_code=200)
async def register_agent(body: dict):
    """Allow a remote agent to register itself dynamically with this Auth NS."""
    import logging as _log
    label    = body.get("label", "")
    endpoint = body.get("endpoint", "")
    health   = body.get("health_url", endpoint + "/.well-known/agent.json")
    protos   = body.get("protocols", ["A2A"])

    if not label or not endpoint:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="label and endpoint required")

    AGENTS[label] = {
        "http_endpoint":    endpoint,
        "health_check_url": health,
        "protocols":        protos,
        "dynamic":          True,
    }
    _log.getLogger("auth-ns").info(f"✅ Dynamic agent registered: {label} -> {endpoint}")
    return {"status": "registered", "label": label, "endpoint": endpoint}
'''

target = "/opt/mbta-agents/ans/generic_auth_ns.py"
with open(target) as f:
    content = f.read()

if "/register_agent" in content:
    print("Already patched — nothing to do.")
else:
    # Insert before the if __name__ == '__main__' block
    idx = content.rfind('\nif __name__')
    if idx == -1:
        content += PATCH
    else:
        content = content[:idx] + PATCH + content[idx:]
    with open(target, "w") as f:
        f.write(content)
    print(f"Patched {target}")
