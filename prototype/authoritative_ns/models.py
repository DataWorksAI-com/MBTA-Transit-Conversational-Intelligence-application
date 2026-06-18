"""
Shared Pydantic models for Authoritative Nameservers.
"""
from pydantic import BaseModel
from typing import Dict, List, Optional


class RequesterContext(BaseModel):
    location: Optional[Dict[str, str]] = None  # {city, state, country}
    device: str = "unknown"
    network: str = "public"
    protocols: List[str] = ["A2A"]
    security_level: str = "standard"


class AuthResolutionRequest(BaseModel):
    agent: str  # e.g. "alerts"
    requester_context: RequesterContext = RequesterContext()


class AuthResolutionResponse(BaseModel):
    endpoint: str
    protocol: str
    ttl: int
    metadata: Dict
