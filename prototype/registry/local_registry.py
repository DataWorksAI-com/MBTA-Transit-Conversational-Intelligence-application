"""
Local Registry — minimal Flask stand-in for the production NANDA registry.

No MongoDB. Pre-loaded in-memory agent catalog.
Exposes the same API surface the exchange's semantic discovery expects:
  GET  /health
  GET  /list
  GET  /lookup/<agent_id>
  POST /search/semantic   ← used by stategraph_orchestrator.py

Also hosts the TLD and App namespace blueprints via Flask blueprints:
  GET  /resolve/tld?urn=...
  GET  /resolve/mbta-transit-ci?urn=...
  GET  /resolve/mbta-transit-ci/list

Port: 6900
"""
import os
import sys
from flask import Flask, jsonify, request

# ── Flask app ────────────────────────────────────────────────────────────────
app = Flask(__name__)

# ── Pre-loaded agent catalog ─────────────────────────────────────────────────
AGENTS = {
    "mbta-alerts": {
        "agent_id":   "mbta-alerts",
        "agent_url":  "http://localhost:8001",
        "api_url":    "http://localhost:8001",
        "agent_name": "urn:agents.local:mbta-transit-ci:alerts",
        "description": "MBTA service alerts and disruption analysis agent",
        "capabilities": ["get_alerts", "check_disruptions", "service_status",
                         "historical_incidents"],
        "tags": ["alerts", "disruptions", "service", "delays", "mbta"],
        "alive": True,
    },
    "mbta-planner": {
        "agent_id":   "mbta-planner",
        "agent_url":  "http://localhost:8002",
        "api_url":    "http://localhost:8002",
        "agent_name": "urn:agents.local:mbta-transit-ci:planner",
        "description": "MBTA trip planning and route optimization agent",
        "capabilities": ["plan_trip", "get_route_options", "calculate_travel_time",
                         "disruption_aware_routing"],
        "tags": ["trip", "route", "planning", "navigate", "directions", "mbta"],
        "alive": True,
    },
    "mbta-stopfinder": {
        "agent_id":   "mbta-stopfinder",
        "agent_url":  "http://localhost:8003",
        "api_url":    "http://localhost:8003",
        "agent_name": "urn:agents.local:mbta-transit-ci:stopfinder",
        "description": "MBTA stop and station finder agent",
        "capabilities": ["find_stops", "get_stop_details", "search_nearby_stops",
                         "resolve_landmark"],
        "tags": ["stops", "stations", "find", "location", "mbta"],
        "alive": True,
    },
}


# ── Core endpoints ────────────────────────────────────────────────────────────

@app.route("/health")
def health():
    return jsonify({"status": "ok", "version": "prototype", "agents": len(AGENTS)})


@app.route("/list")
def list_agents():
    return jsonify({k: v["agent_url"] for k, v in AGENTS.items()})


@app.route("/lookup/<agent_id>")
def lookup(agent_id):
    agent = AGENTS.get(agent_id)
    if not agent:
        return jsonify({"error": f"Agent '{agent_id}' not found"}), 404
    return jsonify(agent)


@app.route("/search/semantic", methods=["POST"])
def semantic_search():
    """
    Simple keyword-based semantic search.
    Returns agents in the same format the production registry returns,
    so the exchange orchestrator works without modification.
    """
    data = request.json or {}
    query = data.get("query", "").lower().strip()
    max_results = int(data.get("max_results", 5))

    results = []
    for agent in AGENTS.values():
        score = 0.0
        searchable = " ".join([
            agent["description"],
            " ".join(agent["capabilities"]),
            " ".join(agent["tags"]),
            agent["agent_id"],
        ]).lower()

        for word in query.split():
            if word in searchable:
                # Weight capabilities and description more heavily
                if word in " ".join(agent["capabilities"]).lower():
                    score += 3.0
                elif word in agent["description"].lower():
                    score += 2.0
                elif word in " ".join(agent["tags"]).lower():
                    score += 1.5
                else:
                    score += 1.0

        if score > 0:
            results.append({
                **agent,
                "relevance_score": score,
                "match_reason": f"keyword match (score={score:.1f})",
            })

    results.sort(key=lambda x: x["relevance_score"], reverse=True)

    return jsonify({
        "query": query,
        "total_candidates": len(AGENTS),
        "filtered_count": len(results),
        "returned_count": min(len(results), max_results),
        "results": results[:max_results],
    })


@app.route("/stats")
def stats():
    return jsonify({
        "total_agents": len(AGENTS),
        "alive_agents": sum(1 for a in AGENTS.values() if a["alive"]),
        "mongodb_enabled": False,
        "semantic_search_enabled": True,
    })


# ── Namespace blueprints ──────────────────────────────────────────────────────
# Must be imported after app is defined and from the same directory

sys.path.insert(0, os.path.dirname(__file__))
from top_level_namespace import tld_ns_bp
from app_namespace import app_ns_bp

app.register_blueprint(tld_ns_bp)
app.register_blueprint(app_ns_bp)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 6900))
    print(f"🚀 Local Prototype Registry on port {port}")
    print("   Agents:   /list  /lookup/<id>  /search/semantic")
    print("   TLD NS:   /resolve/tld?urn=...")
    print("   App NS:   /resolve/mbta-transit-ci?urn=...")
    app.run(host="0.0.0.0", port=port, debug=False)
