"""
Server selection logic for Authoritative Nameservers.
Ranks candidate servers by health, protocol compatibility, geographic proximity, and load.
"""
import math
from typing import Dict, List, Optional


# City → (lat, lon) lookup for common US cities used in requester context
CITY_COORDS: Dict[str, tuple] = {
    "boston":        (42.3601, -71.0589),
    "new york":      (40.7128, -74.0060),
    "new york city": (40.7128, -74.0060),
    "nyc":           (40.7128, -74.0060),
    "fremont":       (37.5485, -121.9886),
    "san francisco": (37.7749, -122.4194),
    "los angeles":   (34.0522, -118.2437),
    "chicago":       (41.8781, -87.6298),
    "dallas":        (32.7767, -96.7970),
    "seattle":       (47.6062, -122.3321),
    "miami":         (25.7617, -80.1918),
    "atlanta":       (33.7490, -84.3880),
}


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Return great-circle distance in km between two lat/lon points."""
    R = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def calculate_geographic_score(
    server_location: Dict,
    requester_location: Optional[Dict],
) -> float:
    """
    Return distance in km from server to requester (lower = better).
    Returns float('inf') if either location is unknown.
    """
    if not requester_location:
        return float("inf")

    try:
        s_lat = float(server_location["latitude"])
        s_lon = float(server_location["longitude"])
    except (KeyError, TypeError, ValueError):
        return float("inf")

    try:
        r_lat = float(requester_location.get("latitude", ""))
        r_lon = float(requester_location.get("longitude", ""))
    except (ValueError, TypeError):
        city = requester_location.get("city", "").lower()
        coords = CITY_COORDS.get(city)
        if not coords:
            return float("inf")
        r_lat, r_lon = coords

    return haversine_km(s_lat, s_lon, r_lat, r_lon)


def select_protocol(available: List[str], preferred: List[str]) -> str:
    """
    Return the best protocol: first preferred protocol that is available,
    falling back to the first available protocol.
    """
    for p in preferred:
        if p in available:
            return p
    return available[0] if available else "A2A"


def rank_servers(
    servers: List[Dict],
    health_map: Dict[str, Dict],
    requester_context: Dict,
) -> List[Dict]:
    """
    Rank servers by suitability (best first).

    Priority order:
      1. Health status  (healthy > degraded; unhealthy excluded)
      2. Protocol compatibility (has at least one preferred protocol)
      3. Geographic proximity (Haversine distance, lower = better)
      4. Current load (lower = better)
    """
    preferred_protocols = requester_context.get("protocols", ["A2A"])
    requester_location = requester_context.get("location")

    ranked = []
    for server in servers:
        sid = server["server_id"]
        health = health_map.get(sid, {"status": "unhealthy", "load": 100.0})

        if health["status"] == "unhealthy":
            continue

        status_score = 0 if health["status"] == "healthy" else 1

        has_protocol = any(p in server.get("protocols", []) for p in preferred_protocols)
        protocol_score = 0 if has_protocol else 1

        geo_score = calculate_geographic_score(
            server.get("location", {}), requester_location
        )

        load = health.get("load", server.get("capacity", {}).get("current_load", 50.0))

        ranked.append({
            "server": server,
            "health": health,
            "sort_key": (status_score, protocol_score, geo_score, load),
        })

    ranked.sort(key=lambda x: x["sort_key"])
    return [(r["server"], r["health"]) for r in ranked]


def calculate_ttl(health: Dict) -> int:
    """
    Calculate cache TTL based on server health and load.

    Rules:
      healthy + load < 50%  → 600s
      healthy + load 50-75% → 300s
      healthy + load > 75%  → 60s
      degraded              → 30s
    """
    if health.get("status") == "degraded":
        return 30

    load = health.get("load", 50.0)
    if load < 50:
        return 600
    elif load <= 75:
        return 300
    else:
        return 60
