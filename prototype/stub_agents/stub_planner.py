"""
Stub Planner Agent — minimal FastAPI stand-in for the real planner agent.
Exposes /health and /a2a/message on port 8002.
"""
from fastapi import FastAPI
import uvicorn

app = FastAPI(title="stub-planner-agent")

AGENT_ID = "mbta-planner"


@app.get("/health")
def health():
    return {
        "status": "ok",
        "service": AGENT_ID,
        "version": "stub",
        "load_percent": 15.0
    }


@app.post("/a2a/message")
def handle_message(body: dict):
    parts = body.get("params", {}).get("message", {}).get("parts", [])
    user_msg = parts[0].get("text", "") if parts else ""
    return {
        "result": {
            "parts": [{
                "text": (
                    f"[STUB PLANNER] Sample route: Take the Red Line from Park Street "
                    f"to Harvard (2 stops, ~8 minutes). No disruptions on your route. "
                    f"(Query received: '{user_msg[:60]}')"
                )
            }]
        }
    }


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8002, log_level="info")
