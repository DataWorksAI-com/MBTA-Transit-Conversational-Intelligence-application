"""
Pydantic models for the ANS Recursive Resolver.
Includes both the new ResolutionRequest/Response spec and the legacy ResolveRequest/ResolveResult.
"""
from typing import Dict, List, Optional

from pydantic import BaseModel


# ── New spec models ───────────────────────────────────────────────────────────

class RequesterContext(BaseModel):
    location: Optional[Dict[str, str]] = None  # {city, state, country}
    device: str = "unknown"
    network: str = "public"
    protocols: List[str] = ["A2A"]
    security_level: str = "standard"


class ResolutionRequest(BaseModel):
    agent_name: str          # full URN, e.g. "urn:agents.local:mbta-transit-ci:alerts"
    requester_context: RequesterContext = RequesterContext()
    cache_enabled: bool = True


class ResolutionResponse(BaseModel):
    endpoint: str
    protocol: str
    ttl: int
    metadata: Dict
    cached: bool = False
    resolution_time_ms: float


# ── Legacy models (kept for backward compat with old GET /resolve endpoint) ───

class ResolveRequest(BaseModel):
    urn: str
    force_refresh: bool = False


class ResolveResult(BaseModel):
    urn: str
    endpoint_url: str
    agent_id: str
    resolved_by: str = "recursive-resolver"
    ttl: int
    cached: bool
    resolution_path: List[str]
    latency_ms: float
