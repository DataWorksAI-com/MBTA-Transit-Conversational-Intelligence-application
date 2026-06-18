"""
Stub Alerts Agent — minimal FastAPI stand-in for the real alerts agent.
Exposes /health and /a2a/message on port 8001.
"""
from fastapi import FastAPI
import uvicorn

app = FastAPI(title="stub-alerts-agent")

AGENT_ID = "mbta-alerts"


@app.get("/health")
def health():
    return {
        "status": "ok",
        "service": AGENT_ID,
        "version": "stub",
        "load_percent": 20.0
    }


@app.post("/a2a/message")
def handle_message(body: dict):
    parts = body.get("params", {}).get("message", {}).get("parts", [])
    user_msg = parts[0].get("text", "") if parts else ""
    return {
        "result": {
            "parts": [{
                "text": (
                    f"[STUB ALERTS] No active service disruptions on the MBTA network. "
                    f"All lines operating normally. "
                    f"(Query received: '{user_msg[:60]}')"
                )
            }]
        }
    }


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8001, log_level="info")
