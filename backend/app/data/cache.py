"""
Redis cache manager with TTL-based expiration.

Caching strategy per data type:
- Tick/quote data: 15s TTL (matches Yahoo Finance delay)
- Technical indicators: 60s TTL
- Company fundamentals: 24h TTL
- AI research reports: 1h TTL

Every cache read tracks hits/misses for observability metrics.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Optional

import redis.asyncio as aioredis

from app.core.logging import get_logger

logger = get_logger(__name__)


class CacheManager:
    """Redis cache manager for market data."""

    def __init__(self, redis_client: aioredis.Redis | None):
        self._redis = redis_client
        self._hits = 0
        self._misses = 0

    @property
    def is_available(self) -> bool:
        return self._redis is not None

    @property
    def hit_rate(self) -> float:
        total = self._hits + self._misses
        return (self._hits / total * 100) if total > 0 else 0.0

    async def get(self, key: str) -> Optional[dict]:
        """Get a cached value. Returns None on miss or if Redis is unavailable."""
        if not self.is_available:
            self._misses += 1
            return None

        try:
            value = await self._redis.get(key)
            if value is None:
                self._misses += 1
                return None

            self._hits += 1
            data = json.loads(value)

            # Attach cache metadata
            data["_cache_hit"] = True
            data["_cached_at"] = data.get("_cached_at", datetime.now(timezone.utc).isoformat())

            return data

        except Exception as e:
            logger.warning("cache_get_failed", key=key, error=str(e))
            self._misses += 1
            return None

    async def set(
        self, key: str, value: dict, ttl: int = 60
    ) -> bool:
        """Set a cached value with TTL in seconds."""
        if not self.is_available:
            return False

        try:
            # Add cache timestamp
            value["_cached_at"] = datetime.now(timezone.utc).isoformat()

            await self._redis.setex(
                key,
                ttl,
                json.dumps(value, default=str),
            )
            return True

        except Exception as e:
            logger.warning("cache_set_failed", key=key, error=str(e))
            return False

    async def delete(self, key: str) -> bool:
        """Delete a cached value."""
        if not self.is_available:
            return False

        try:
            await self._redis.delete(key)
            return True
        except Exception as e:
            logger.warning("cache_delete_failed", key=key, error=str(e))
            return False

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

        This is the primary interface — it tries cache first, falls back to
        the fetch function, and caches the result.
        """
        # Try cache first
        cached = await self.get(key)
        if cached is not None:
            return cached

        # Cache miss — fetch from source
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
            "is_available": self.is_available,
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
