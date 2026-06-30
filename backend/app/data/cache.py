"""
Cache manager with in-memory fallback for when Redis is unavailable.

Caching strategy per data type (TTL in seconds):
- Tick/quote data: 30s (slightly more than Yahoo's ~15s delay to reduce calls)
- Technical indicators: 60s
- OHLCV data: 300s (5 min — historical data doesn't change fast)
- Sentiment/Risk: 600s (10 min — computed from news, not live prices)
- Company fundamentals: 3600s (1 hour — changes at most daily)
- Research reports: 3600s (1 hour — AI-generated, expensive to recompute)
- Financials/Ratios: 86400s (24 hours — quarterly data)

In-memory cache activates automatically when Redis is unavailable (Render free tier).
Uses a bounded dict with TTL per entry and periodic cleanup.
"""

from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

import redis.asyncio as aioredis

from app.core.logging import get_logger

logger = get_logger(__name__)

# ── In-Memory Cache (module-level singleton) ─────────────────────────
# Activated when Redis is unavailable. Stores (value_dict, expiry_time) tuples.
# Bounded to MAX_ENTRIES to prevent unbounded memory growth on Render (512MB).
_memory_cache: Dict[str, Tuple[dict, float]] = {}
_MAX_ENTRIES = 500
_CLEANUP_INTERVAL = 60.0  # seconds between cleanup sweeps
_last_cleanup = [0.0]

# ── Thundering Herd Protection ────────────────────────────────────────
# Prevents N concurrent cache misses for the same key from making N
# Yahoo calls. Only the first miss fetches; others wait and read cache.
_fetch_locks: Dict[str, asyncio.Lock] = {}


def _memory_get(key: str) -> Optional[dict]:
    """Get from in-memory cache. Returns None if missing or expired."""
    entry = _memory_cache.get(key)
    if entry is None:
        return None
    value, expiry = entry
    if time.monotonic() > expiry:
        # Expired — remove and return miss
        _memory_cache.pop(key, None)
        return None
    return value


def _memory_set(key: str, value: dict, ttl: int) -> None:
    """Set in-memory cache entry with TTL. Cleans up expired entries periodically."""
    now = time.monotonic()

    # Periodic cleanup: remove expired entries every CLEANUP_INTERVAL
    if now - _last_cleanup[0] > _CLEANUP_INTERVAL:
        expired_keys = [
            k for k, (_, exp) in _memory_cache.items() if now > exp
        ]
        for k in expired_keys:
            _memory_cache.pop(k, None)
        _last_cleanup[0] = now
        if expired_keys:
            logger.debug("memory_cache_cleanup", removed=len(expired_keys), remaining=len(_memory_cache))

    # Evict oldest entries if at capacity
    if len(_memory_cache) >= _MAX_ENTRIES:
        # Remove the 20% oldest entries by expiry time
        sorted_keys = sorted(_memory_cache.keys(), key=lambda k: _memory_cache[k][1])
        for k in sorted_keys[: _MAX_ENTRIES // 5]:
            _memory_cache.pop(k, None)
        logger.debug("memory_cache_eviction", evicted=_MAX_ENTRIES // 5)

    _memory_cache[key] = (value, now + ttl)


def _memory_delete(key: str) -> None:
    """Delete from in-memory cache."""
    _memory_cache.pop(key, None)


class CacheManager:
    """Cache manager with Redis primary and in-memory fallback."""

    def __init__(self, redis_client: aioredis.Redis | None):
        self._redis = redis_client
        self._hits = 0
        self._misses = 0

    @property
    def is_available(self) -> bool:
        """True if Redis is connected. In-memory fallback always works."""
        return self._redis is not None

    @property
    def hit_rate(self) -> float:
        total = self._hits + self._misses
        return (self._hits / total * 100) if total > 0 else 0.0

    async def get(self, key: str) -> Optional[dict]:
        """Get a cached value. Tries Redis first, then in-memory fallback."""
        # Try Redis
        if self._redis is not None:
            try:
                value = await self._redis.get(key)
                if value is not None:
                    self._hits += 1
                    data = json.loads(value)
                    data["_cache_hit"] = True
                    data["_cached_at"] = data.get("_cached_at", datetime.now(timezone.utc).isoformat())
                    return data
            except Exception as e:
                logger.warning("cache_redis_get_failed", key=key, error=str(e))

        # Fallback: in-memory cache
        mem_data = _memory_get(key)
        if mem_data is not None:
            self._hits += 1
            # Return a copy so callers can mutate without affecting cache
            result = dict(mem_data)
            result["_cache_hit"] = True
            result["_cache_source"] = "memory"
            return result

        self._misses += 1
        return None

    async def set(self, key: str, value: dict, ttl: int = 60) -> bool:
        """Set a cached value. Writes to both Redis and in-memory."""
        # Add cache timestamp
        value["_cached_at"] = datetime.now(timezone.utc).isoformat()

        # Always write to in-memory (even if Redis works — serves as backup)
        _memory_set(key, value, ttl)

        # Try Redis
        if self._redis is not None:
            try:
                await self._redis.setex(
                    key,
                    ttl,
                    json.dumps(value, default=str),
                )
                return True
            except Exception as e:
                logger.warning("cache_redis_set_failed", key=key, error=str(e))

        return True  # In-memory write succeeded

    async def delete(self, key: str) -> bool:
        """Delete a cached value from both stores."""
        _memory_delete(key)

        if self._redis is not None:
            try:
                await self._redis.delete(key)
            except Exception as e:
                logger.warning("cache_redis_delete_failed", key=key, error=str(e))

        return True

    async def get_or_fetch(
        self,
        key: str,
        fetch_func,
        ttl: int = 60,
        *args,
        **kwargs,
    ) -> Optional[dict]:
        """
        Get from cache or fetch from source.

        Includes thundering herd protection: if N concurrent requests all miss
        the cache for the same key, only ONE actually calls Yahoo. The rest
        wait for the lock, then read from cache.
        """
        # Try cache first (Redis → in-memory)
        cached = await self.get(key)
        if cached is not None:
            return cached

        # Acquire per-key lock to prevent duplicate fetches
        if key not in _fetch_locks:
            _fetch_locks[key] = asyncio.Lock()

        async with _fetch_locks[key]:
            # Re-check cache — another coroutine may have populated it
            cached = await self.get(key)
            if cached is not None:
                return cached

            # Cache still empty — we're the one who fetches
            try:
                data = await fetch_func(*args, **kwargs)
                if data is not None:
                    await self.set(key, data, ttl)
                    data["_cache_hit"] = False
                return data
            except Exception as e:
                logger.error("cache_fetch_failed", key=key, error=str(e))
                return None

    def get_stats(self) -> dict:
        """Get cache statistics for observability."""
        return {
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": round(self.hit_rate, 2),
            "redis_available": self.is_available,
            "memory_entries": len(_memory_cache),
            "memory_max": _MAX_ENTRIES,
        }

    # ── Convenience key builders ──

    @staticmethod
    def quote_key(symbol: str) -> str:
        return f"quote:{symbol.upper()}"

    @staticmethod
    def ohlcv_key(symbol: str, period: str, interval: str) -> str:
        return f"ohlcv:{symbol.upper()}:{period}:{interval}"

    @staticmethod
    def indicators_key(symbol: str) -> str:
        return f"indicators:{symbol.upper()}"

    @staticmethod
    def company_key(symbol: str) -> str:
        return f"company:{symbol.upper()}"

    @staticmethod
    def research_key(symbol: str) -> str:
        return f"research:{symbol.upper()}"

    @staticmethod
    def sentiment_key(symbol: str) -> str:
        return f"sentiment:{symbol.upper()}"

    @staticmethod
    def risk_key(symbol: str) -> str:
        return f"risk:{symbol.upper()}"

    @staticmethod
    def indices_key() -> str:
        return "market:indices"

    @staticmethod
    def financials_key(symbol: str) -> str:
        return f"financials:{symbol.upper()}"

    @staticmethod
    def ratios_key(symbol: str) -> str:
        return f"ratios:{symbol.upper()}"

    @staticmethod
    def health_key(symbol: str) -> str:
        return f"health:{symbol.upper()}"
