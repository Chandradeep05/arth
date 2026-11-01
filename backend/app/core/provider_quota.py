"""
ARTH Central Provider Quota Governor.

Tracks and enforces per-minute and per-day rate and budget quotas across
external market data providers:
- Twelve Data: 8 requests/min, 800 requests/day (Free tier)
- Finnhub: 60 requests/min, 10,000 requests/day (Free tier)
- Financial Modeling Prep (FMP): 250 requests/day (Basic tier)
- Upstox: 10 requests/sec, 10,000 requests/day (Standard API tier)

Persistence:
- Redis atomic INCR with expiry when Redis is available
- In-memory thread-safe fallback counters when Redis is absent
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import time
from typing import Dict, Optional, Tuple

from app.core.logging import get_logger

logger = get_logger(__name__)


class ProviderLimit:
    def __init__(self, per_minute: Optional[int] = None, per_day: Optional[int] = None):
        self.per_minute = per_minute
        self.per_day = per_day


# Provider quota configuration
PROVIDER_LIMITS: Dict[str, ProviderLimit] = {
    "twelvedata": ProviderLimit(per_minute=8, per_day=800),
    "finnhub": ProviderLimit(per_minute=60, per_day=10000),
    "fmp": ProviderLimit(per_minute=None, per_day=250),
    "upstox": ProviderLimit(per_minute=600, per_day=10000),
    "nse": ProviderLimit(per_minute=30, per_day=3000),
}


class ProviderQuotaGovernor:
    """Centralized governor ensuring ARTH never exceeds external provider API quotas."""

    def __init__(self):
        self._lock = asyncio.Lock()
        # In-memory tracking: provider -> [(timestamp), ...]
        self._minute_calls: Dict[str, list[float]] = {}
        # In-memory daily tracking: (provider, date_str) -> count
        self._daily_counts: Dict[Tuple[str, str], int] = {}

    async def acquire(self, provider: str, redis_client=None) -> bool:
        """
        Attempt to acquire 1 request token for the given provider.
        Returns True if within budget, False if quota exceeded.
        """
        prov = provider.lower().strip()
        limits = PROVIDER_LIMITS.get(prov)
        if not limits:
            return True  # Unregulated provider

        now_utc = datetime.now(timezone.utc)
        today_str = now_utc.strftime("%Y-%m-%d")
        now_epoch = time.time()

        # ── 1. Redis Tier (Distributed) ──
        if redis_client is not None:
            try:
                # 1. Minute burst limit check FIRST (prevents leaking daily counter on burst rejection)
                minute_key = None
                if limits.per_minute is not None:
                    epoch_min = int(now_epoch // 60)
                    minute_key = f"quota:provider:{prov}:min:{epoch_min}"
                    used_min = await redis_client.incr(minute_key)
                    if used_min == 1:
                        await redis_client.expire(minute_key, 120)
                    if used_min > limits.per_minute:
                        logger.warning(
                            "provider_minute_quota_exceeded",
                            provider=prov,
                            used=used_min,
                            limit=limits.per_minute,
                        )
                        return False

                # 2. Daily limit check (only reached if minute check passed)
                if limits.per_day is not None:
                    daily_key = f"quota:provider:{prov}:daily:{today_str}"
                    used_today = await redis_client.incr(daily_key)
                    if used_today == 1:
                        await redis_client.expire(daily_key, 90000)
                    if used_today > limits.per_day:
                        # Rollback minute counter since daily cap is hit
                        if minute_key:
                            try:
                                await redis_client.decr(minute_key)
                            except Exception:
                                pass
                        logger.warning(
                            "provider_daily_quota_exceeded",
                            provider=prov,
                            used=used_today,
                            limit=limits.per_day,
                        )
                        return False

                return True
            except Exception as e:
                logger.warning("provider_quota_redis_error_fallback", provider=prov, error=str(e))
                # Fall through to in-memory governor

        # ── 2. In-Memory Tier (Process-local fallback) ──
        async with self._lock:
            # Check daily
            if limits.per_day is not None:
                day_key = (prov, today_str)
                current_day_count = self._daily_counts.get(day_key, 0)
                if current_day_count >= limits.per_day:
                    logger.warning(
                        "provider_in_memory_daily_quota_exceeded",
                        provider=prov,
                        used=current_day_count,
                        limit=limits.per_day,
                    )
                    return False

            # Check minute sliding window
            if limits.per_minute is not None:
                window_start = now_epoch - 60.0
                calls = self._minute_calls.get(prov, [])
                calls = [t for t in calls if t > window_start]
                if len(calls) >= limits.per_minute:
                    logger.warning(
                        "provider_in_memory_minute_quota_exceeded",
                        provider=prov,
                        used=len(calls),
                        limit=limits.per_minute,
                    )
                    self._minute_calls[prov] = calls
                    return False
                calls.append(now_epoch)
                self._minute_calls[prov] = calls

            # Increment daily
            if limits.per_day is not None:
                day_key = (prov, today_str)
                self._daily_counts[day_key] = self._daily_counts.get(day_key, 0) + 1

            return True

    def get_status(self) -> Dict[str, dict]:
        """Return current in-memory quota usage for health/metrics display."""
        today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        now_epoch = time.time()
        res = {}
        for prov, limits in PROVIDER_LIMITS.items():
            day_key = (prov, today_str)
            daily_used = self._daily_counts.get(day_key, 0)
            calls = [t for t in self._minute_calls.get(prov, []) if t > now_epoch - 60.0]
            res[prov] = {
                "daily_used": daily_used,
                "daily_limit": limits.per_day,
                "minute_used": len(calls),
                "minute_limit": limits.per_minute,
            }
        return res


# Global singleton instance
quota_governor = ProviderQuotaGovernor()
