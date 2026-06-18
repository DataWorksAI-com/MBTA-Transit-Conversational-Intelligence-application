"""
Application Namespace Server for 'mbta-transit-ci'.

Routes by label (last URN component) to the appropriate Authoritative NS.
Mounted as a Flask blueprint on the local registry at port 6900.

Endpoints:
  GET  /resolve/mbta-transit-ci?urn=<urn>   — legacy GET (backward compat)
  POST /resolve/mbta-transit-ci              — new POST API, forwards to Auth NS
  GET  /resolve/mbta-transit-ci/list        — list registered agents
"""
import re

import requests
from flask import Blueprint, jsonify, request

app_ns_bp = Blueprint("app_ns", __name__)

URN_PATTERN = re.compile(r"^urn:([^:]+):([^:]+):([^:]+)$")

# Auth NS base URLs per agent label
AUTH_NS_MAP = {
    "alerts":     "http://localhost:8300",
    "planner":    "http://localhost:8301",
    "stopfinder": "http://localhost:8302",
}

# Aliases
AUTH_NS_ALIASES = {
    "route-planner": "planner",
    "stop-finder":   "stopfinder",
    "stops":         "stopfinder",
}

AGENT_ID_MAP = {
    "alerts":     "mbta-alerts",
    "planner":    "mbta-planner",
    "stopfinder": "mbta-stopfinder",
}

APP_NAMESPACE = "mbta-transit-ci"


def _resolve_label(raw_label: str):
    """Normalize label via alias map; return (canonical_label, auth_ns_url) or (None, None)."""
    label = AUTH_NS_ALIASES.get(raw_label, raw_label)
    url = AUTH_NS_MAP.get(label)
    return (label, url) if url else (None, None)


# ── Legacy GET ────────────────────────────────────────────────────────────────

@app_ns_bp.route("/resolve/mbta-transit-ci")
def resolve_app_ns_get():
    """GET /resolve/mbta-transit-ci?urn=<urn>"""
    urn = request.args.get("urn", "").strip()
    m = URN_PATTERN.match(urn)
    if not m:
        return jsonify({"error": "malformed_urn", "urn": urn}), 400

    raw_label = m.group(3)
    label, auth_ns_url = _resolve_label(raw_label)
    if not label:
        return jsonify({
            "error": "unknown_agent_label",
            "label": raw_label,
            "known_labels": list(AUTH_NS_MAP.keys()),
        }), 404

    return jsonify({
        "urn": urn,
        "label": label,
        "delegate_to": auth_ns_url,
        "ns_type": "authoritative",
        "agent_id": AGENT_ID_MAP[label],
    })


# ── New POST endpoint ─────────────────────────────────────────────────────────

@app_ns_bp.route("/resolve/mbta-transit-ci", methods=["POST"])
def resolve_app_ns_post():
    """
    POST /resolve/mbta-transit-ci
    Body: {"agent_path": "mbta-transit-ci:alerts", "requester_context": {...}}
       OR {"agent": "alerts", "requester_context": {...}}

    Extracts the agent label, looks up the Auth NS URL, forwards the request
    to the Auth NS /resolve endpoint, and returns its response.
    """
    body = request.get_json(force=True, silent=True) or {}
    requester_context = body.get("requester_context", {})

    # Support both "agent_path" (from TLD NS forwarding) and "agent" (direct call)
    raw_label = body.get("agent", "").strip()
    if not raw_label:
        agent_path = body.get("agent_path", "").strip()
        # "mbta-transit-ci:alerts" → "alerts" OR just "alerts"
        raw_label = agent_path.split(":")[-1] if agent_path else ""

    if not raw_label:
        return jsonify({"error": "missing agent label (provide 'agent' or 'agent_path')"}), 400

    label, auth_ns_url = _resolve_label(raw_label)
    if not label:
        return jsonify({
            "error": "unknown_agent_label",
            "label": raw_label,
            "known_labels": list(AUTH_NS_MAP.keys()),
        }), 404

    # Forward to Authoritative NS
    try:
        resp = requests.post(
            f"{auth_ns_url}/resolve",
            json={"agent": label, "requester_context": requester_context},
            timeout=5,
        )
        return jsonify(resp.json()), resp.status_code
    except requests.exceptions.Timeout:
        return jsonify({"error": "auth_ns_timeout", "agent": label}), 503
    except Exception as e:
        return jsonify({"error": f"auth_ns_unavailable: {e}"}), 503


@app_ns_bp.route("/resolve/mbta-transit-ci/list")
def list_ns():
    return jsonify({
        "application": APP_NAMESPACE,
        "labels": {
            label: {"auth_ns": url, "agent_id": AGENT_ID_MAP[label]}
            for label, url in AUTH_NS_MAP.items()
        },
    })
