"""
URN parser for the ANS resolution chain.

Expected formats:
1. URN:   urn:<tld>:<app_namespace>:<label>
2. Email: <label>.<app_namespace>#<tld>
3. DNS:   _<label>._<app_namespace>.agent.<tld>
Example:         urn:agents.local:mbta-transit-ci:alerts
"""
import re
from dataclasses import dataclass

# Regex patterns for different representations
URN_PATTERN = re.compile(r"^urn:([^:]+):([^:]+):([^:]+)$")
EMAIL_PATTERN = re.compile(r"^([^.]+)\.([^#]+)#(.+)$")
DNS_PATTERN = re.compile(r"^_([^_.]+)\._([^_.]+)\.agent\.(.+)$")


@dataclass
class ParsedURN:
    tld: str           # e.g. "agents.local"
    app_namespace: str # e.g. "mbta-transit-ci"
    label: str         # e.g. "alerts"
    raw: str           # original string


def parse_urn(urn: str) -> ParsedURN:
    """
    Parse and validate an identity string (URN, Email-like, or DNS-like).

    Raises ValueError("malformed_urn: <urn>") if no patterns match.
    """
    # 1. Try URN-like: urn:agents.local:mbta-transit-ci:alerts
    if urn.startswith("urn:"):
        if m := URN_PATTERN.match(urn):
            return ParsedURN(tld=m.group(1), app_namespace=m.group(2), label=m.group(3), raw=urn)

    # 2. Try DNS-like: _alerts._mbta-transit-ci.agent.dataworksai.com
    elif urn.startswith("_"):
        if m := DNS_PATTERN.match(urn):
            # Maps: _<label>._<app_namespace>.agent.<tld>
            return ParsedURN(tld=m.group(3), app_namespace=m.group(2), label=m.group(1), raw=urn)

    # 3. Try Email-like: alerts.mbta-transit-ci#agents.dataworksai.com
    elif "#" in urn:
        if m := EMAIL_PATTERN.match(urn):
            # Maps: <label>.<app_namespace>#<tld>
            return ParsedURN(tld=m.group(3), app_namespace=m.group(2), label=m.group(1), raw=urn)

    # Fallback if nothing matches
    raise ValueError(f"malformed_urn: {urn!r}")
