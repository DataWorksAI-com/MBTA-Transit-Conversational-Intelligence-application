"""
Async TTL cache for resolved agent_name → ResolutionResponse mappings.

Cache key is an MD5 hash of agent_name + location + protocols.
Includes a secondary index for high-performance invalidation by agent_name.

Thread-safe via asyncio.Lock.
"""
import asyncio
import hashlib
import json
from datetime import datetime, timedelta
from typing import Any, Dict, Optional


class ResolutionCache:
    """In-memory TTL cache keyed by (agent_name, location, protocols)."""

    def __init__(self):
        # _store: cache_key → {data: dict, expires_at: datetime, cached_at: datetime}
        self._store: Dict[str, Dict[str, Any]] = {}

        # _agent_index: agent_name → set(cache_keys) — O(1) invalidation
        self._agent_index: Dict[str, set] = {}

        self._lock = asyncio.Lock()
        self._hits = 0
        self._misses = 0
        self._evictions = 0

        # Legacy public counters (kept for compat)
        self.hits = 0
        self.misses = 0

    # ── Key generation ────────────────────────────────────────────────────────

    def _make_key(self, agent_name: str, context: Any) -> str:
        """Generate stable cache key from agent_name + location + protocols."""
        if hasattr(context, "dict"):
            ctx = context.dict()
        else:
            ctx = context or {}

        key_parts = {
            "agent_name": agent_name,
            "location": ctx.get("location"),
            "protocols": sorted(ctx.get("protocols", ["A2A"])),
        }
        raw = json.dumps(key_parts, sort_keys=True)
        return hashlib.md5(raw.encode()).hexdigest()

    # ── Internal helpers ──────────────────────────────────────────────────────

    async def _remove_key(self, key: str, agent_name: str):
        """Remove from both store and secondary index safely."""
        if key in self._store:
            del self._store[key]

        if agent_name in self._agent_index:
            self._agent_index[agent_name].discard(key)
            if not self._agent_index[agent_name]:
                del self._agent_index[agent_name]

    # ── Public API ────────────────────────────────────────────────────────────

    async def get(self, agent_name: str, context: Any = None) -> Optional[Dict]:
        """Return cached data if present and not expired, else None."""
        key = self._make_key(agent_name, context or {})
        async with self._lock:
            entry = self._store.get(key)
            if entry is None:
                self._misses += 1
                self.misses += 1
                return None

            if datetime.now() > entry["expires_at"]:
                await self._remove_key(key, agent_name)
                self._evictions += 1
                self._misses += 1
                self.misses += 1
                return None

            self._hits += 1
            self.hits += 1
            return entry["data"]

    async def set(self, agent_name: str, context: Any, data: Dict, ttl: int) -> None:
        """Store resolution data with secondary agent-name index."""
        key = self._make_key(agent_name, context or {})
        now = datetime.now()
        async with self._lock:
            self._store[key] = {
                "data": data,
                "expires_at": now + timedelta(seconds=ttl),
                "cached_at": now,
            }
            if agent_name not in self._agent_index:
                self._agent_index[agent_name] = set()
            self._agent_index[agent_name].add(key)

    async def invalidate(self, agent_name: str) -> bool:
        """Invalidate all cache entries for an agent (O(1) via secondary index)."""
        async with self._lock:
            keys_to_remove = self._agent_index.get(agent_name, set()).copy()
            if not keys_to_remove:
                return False
            for k in keys_to_remove:
                await self._remove_key(k, agent_name)
            return True

    async def clear(self) -> None:
        """Remove all cache entries and reset the index."""
        async with self._lock:
            self._store.clear()
            self._agent_index.clear()

    async def get_stats(self) -> Dict:
        """Return cache statistics."""
        async with self._lock:
            total = self._hits + self._misses
            return {
                "hits": self._hits,
                "misses": self._misses,
                "evictions": self._evictions,
                "total_requests": total,
                "hit_rate_percent": round(self._hits / total * 100, 1) if total else 0.0,
                "current_size": len(self._store),
                "indexed_agents": len(self._agent_index),
            }

    async def stats(self) -> Dict:
        """Alias for get_stats() — kept for backward compat."""
        return await self.get_stats()
