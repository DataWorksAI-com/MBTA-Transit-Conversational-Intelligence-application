"""
Top-Level Namespace Server for 'agents.local'.

Routes by app_namespace component of the URN to an Application NS endpoint.
Mounted as a Flask blueprint on the local registry at port 6900.

Endpoints:
  GET  /resolve/tld?urn=<urn>   — legacy GET (backward compat with old resolver)
  POST /resolve                  — new POST API used by the upgraded recursive resolver
  GET  /namespaces               — list managed namespaces
"""
import re

import requests
from flask import Blueprint, jsonify, request

tld_ns_bp = Blueprint("tld_ns", __name__)

URN_PATTERN = re.compile(r"^urn:([^:]+):([^:]+):([^:]+)$")

OWNED_TLD = "agents.local"

# Map: app_namespace → App NS URL (hosted on same registry process)
APP_NAMESPACE_MAP = {
    "mbta-transit-ci": "http://localhost:6900/resolve/mbta-transit-ci"
}


def _parse_urn(urn: str):
    """Return (tld, app_ns, label) or None if malformed."""
    m = URN_PATTERN.match(urn)
    return (m.group(1), m.group(2), m.group(3)) if m else None


# ── Legacy GET (backward compat) ─────────────────────────────────────────────

@tld_ns_bp.route("/resolve/tld")
def resolve_tld_get():
    """GET /resolve/tld?urn=<urn>"""
    urn = request.args.get("urn", "").strip()
    parsed = _parse_urn(urn)
    if not parsed:
        return jsonify({"error": "malformed_urn", "urn": urn}), 400

    tld, app_ns, _label = parsed

    if tld != OWNED_TLD:
        return jsonify({"error": "unknown_tld", "tld": tld, "owned": OWNED_TLD}), 404

    delegate = APP_NAMESPACE_MAP.get(app_ns)
    if not delegate:
        return jsonify({"error": "unknown_namespace", "app_namespace": app_ns}), 404

    return jsonify({
        "urn": urn,
        "app_namespace": app_ns,
        "delegate_to": delegate,
        "ns_type": "app_namespace",
    })


# ── New POST endpoint (used by upgraded recursive resolver) ───────────────────

@tld_ns_bp.route("/resolve", methods=["POST"])
def resolve_post():
    """
    POST /resolve
    Body: {"agent_path": "mbta-transit-ci:alerts", "requester_context": {...}}

    Extracts app_namespace from agent_path, forwards the full request to the
    Application Namespace Server, and returns the Auth NS resolution response.
    """
    body = request.get_json(force=True, silent=True) or {}
    agent_path = body.get("agent_path", "").strip()
    requester_context = body.get("requester_context", {})

    if not agent_path:
        return jsonify({"error": "missing agent_path"}), 400

    # "mbta-transit-ci:alerts" → app_ns = "mbta-transit-ci"
    app_ns = agent_path.split(":")[0]

    app_ns_url = APP_NAMESPACE_MAP.get(app_ns)
    if not app_ns_url:
        return jsonify({"error": "unknown_namespace", "app_namespace": app_ns}), 404

    # Forward to Application NS
    try:
        resp = requests.post(
            app_ns_url,
            json={"agent_path": agent_path, "requester_context": requester_context},
            timeout=5,
        )
        return jsonify(resp.json()), resp.status_code
    except requests.exceptions.Timeout:
        return jsonify({"error": "app_ns_timeout"}), 503
    except Exception as e:
        return jsonify({"error": f"app_ns_unavailable: {e}"}), 503


@tld_ns_bp.route("/namespaces", methods=["GET"])
def list_namespaces():
    return jsonify({
        "namespace_id": OWNED_TLD,
        "applications": list(APP_NAMESPACE_MAP.keys()),
        "details": APP_NAMESPACE_MAP,
    })
