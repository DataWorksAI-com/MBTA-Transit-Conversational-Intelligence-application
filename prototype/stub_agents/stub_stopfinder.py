"""
Stub StopFinder Agent — minimal FastAPI stand-in for the real stopfinder agent.
Exposes /health and /a2a/message on port 8003.
"""
from fastapi import FastAPI
import uvicorn

app = FastAPI(title="stub-stopfinder-agent")

AGENT_ID = "mbta-stopfinder"


@app.get("/health")
def health():
    return {
        "status": "ok",
        "service": AGENT_ID,
        "version": "stub",
        "load_percent": 10.0
    }


@app.post("/a2a/message")
def handle_message(body: dict):
    parts = body.get("params", {}).get("message", {}).get("parts", [])
    user_msg = parts[0].get("text", "") if parts else ""
    return {
        "result": {
            "parts": [{
                "text": (
                    f"[STUB STOPFINDER] Park Street station is located at the intersection "
                    f"of the Red and Green Lines in downtown Boston. "
                    f"Accessible via elevator. "
                    f"(Query received: '{user_msg[:60]}')"
                )
            }]
        }
    }


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8003, log_level="info")
