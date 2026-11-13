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
    def __init__(
        self,
        per_second: Optional[int] = None,
        per_minute: Optional[int] = None,
        per_day: Optional[int] = None,
    ):
        self.per_second = per_second
        self.per_minute = per_minute
        self.per_day = per_day


# Provider quota configuration
PROVIDER_LIMITS: Dict[str, ProviderLimit] = {
    "twelvedata": ProviderLimit(per_second=None, per_minute=8, per_day=800),
    "finnhub": ProviderLimit(per_second=30, per_minute=60, per_day=10000),
    "fmp": ProviderLimit(per_second=None, per_minute=None, per_day=250),
    "upstox": ProviderLimit(per_second=10, per_minute=300, per_day=10000),
    "nse": ProviderLimit(per_second=5, per_minute=30, per_day=3000),
}

_ATOMIC_QUOTA_LUA = """
local count = tonumber(ARGV[1])
local sec_limit = tonumber(ARGV[2])
local min_limit = tonumber(ARGV[3])
local day_limit = tonumber(ARGV[4])
local sec_ttl = tonumber(ARGV[5])
local min_ttl = tonumber(ARGV[6])
local day_ttl = tonumber(ARGV[7])

local has_sec = sec_limit > 0
local has_min = min_limit > 0
local has_day = day_limit > 0

if has_sec then
    local cur_sec = tonumber(redis.call('get', KEYS[1]) or '0')
    if cur_sec + count > sec_limit then
        return -2 -- Rejected on second burst
    end
end

if has_min then
    local cur_min = tonumber(redis.call('get', KEYS[2]) or '0')
    if cur_min + count > min_limit then
        return 0 -- Rejected on minute burst
    end
end

if has_day then
    local cur_day = tonumber(redis.call('get', KEYS[3]) or '0')
    if cur_day + count > day_limit then
        return -1 -- Rejected on daily limit
    end
end

if has_sec then
    redis.call('incrby', KEYS[1], count)
    local ttl = redis.call('ttl', KEYS[1])
    if ttl < 0 then
        redis.call('expire', KEYS[1], sec_ttl)
    end
end

if has_min then
    redis.call('incrby', KEYS[2], count)
    local ttl = redis.call('ttl', KEYS[2])
    if ttl < 0 then
        redis.call('expire', KEYS[2], min_ttl)
    end
end

if has_day then
    redis.call('incrby', KEYS[3], count)
    local ttl = redis.call('ttl', KEYS[3])
    if ttl < 0 then
        redis.call('expire', KEYS[3], day_ttl)
    end
end

return 1 -- Allowed
"""


class ProviderQuotaGovernor:
    """Centralized governor ensuring ARTH never exceeds external provider API quotas."""

    def __init__(self):
        self._lock = asyncio.Lock()
        # In-memory tracking: provider -> [(timestamp), ...]
        self._sec_calls: Dict[str, list[float]] = {}
        self._minute_calls: Dict[str, list[float]] = {}
        # In-memory daily tracking: (provider, date_str) -> count
        self._daily_counts: Dict[Tuple[str, str], int] = {}

    async def acquire(self, provider: str, redis_client=None, count: int = 1) -> bool:
        """
        Attempt to acquire `count` request tokens for the given provider.
        Returns True if within budget, False if quota exceeded.
        """
        if count <= 0:
            return True

        prov = provider.lower().strip()
        limits = PROVIDER_LIMITS.get(prov)
        if not limits:
            return True  # Unregulated provider

        if redis_client is None:
            try:
                from app.dependencies import _redis_client
                redis_client = _redis_client
            except Exception:
                pass

        now_utc = datetime.now(timezone.utc)
        today_str = now_utc.strftime("%Y-%m-%d")
        now_epoch = time.time()

        # Check fail-closed boundary in production
        try:
            from app.config import get_settings
            is_prod = get_settings().is_production
        except Exception:
            is_prod = False

        if redis_client is None and is_prod:
            logger.error("provider_quota_redis_unavailable_in_production_fail_closed", provider=prov)
            return False

        # ── 1. Redis Tier (Distributed) ──
        if redis_client is not None:
            epoch_sec = int(now_epoch)
            epoch_min = int(now_epoch // 60)
            sec_key = f"quota:provider:{prov}:sec:{epoch_sec}" if limits.per_second is not None else None
            minute_key = f"quota:provider:{prov}:min:{epoch_min}" if limits.per_minute is not None else None
            daily_key = f"quota:provider:{prov}:daily:{today_str}" if limits.per_day is not None else None

            # Primary: Atomic check-and-reserve Lua script (eliminates partial reservation and immortal keys)
            if hasattr(redis_client, "eval"):
                try:
                    res = await redis_client.eval(
                        _ATOMIC_QUOTA_LUA,
                        3,
                        sec_key or "quota:noop:sec",
                        minute_key or "quota:noop:min",
                        daily_key or "quota:noop:day",
                        count,
                        limits.per_second if limits.per_second is not None else -1,
                        limits.per_minute if limits.per_minute is not None else -1,
                        limits.per_day if limits.per_day is not None else -1,
                        10,
                        120,
                        90000,
                    )
                    if res == 1:
                        return True
                    elif res == -2:
                        logger.warning(
                            "provider_second_quota_exceeded",
                            provider=prov,
                            limit=limits.per_second,
                            count=count,
                        )
                        return False
                    elif res == 0:
                        logger.warning(
                            "provider_minute_quota_exceeded",
                            provider=prov,
                            limit=limits.per_minute,
                            count=count,
                        )
                        return False
                    elif res == -1:
                        logger.warning(
                            "provider_daily_quota_exceeded",
                            provider=prov,
                            limit=limits.per_day,
                            count=count,
                        )
                        return False
                except Exception as lua_err:
                    logger.warning("quota_lua_script_failed_fallback_to_commands", provider=prov, error=str(lua_err))

            # Fallback path (e.g. simplified test mock redis instances without Lua evaluation support)
            sec_incremented = False
            daily_incremented = False
            try:
                # 1. Second burst limit check
                if limits.per_second is not None and sec_key:
                    used_sec = await redis_client.incrby(sec_key, count)
                    sec_incremented = True
                    if used_sec == count:
                        try:
                            await redis_client.expire(sec_key, 10)
                        except Exception:
                            pass
                    if used_sec > limits.per_second:
                        try:
                            await redis_client.decrby(sec_key, count)
                        except Exception:
                            pass
                        sec_key = None
                        logger.warning(
                            "provider_second_quota_exceeded",
                            provider=prov,
                            used=used_sec,
                            limit=limits.per_second,
                            count=count,
                        )
                        return False

                # 2. Minute burst limit check
                if limits.per_minute is not None and minute_key:
                    used_min = await redis_client.incrby(minute_key, count)
                    if used_min == count:
                        try:
                            await redis_client.expire(minute_key, 120)
                        except Exception:
                            pass
                    if used_min > limits.per_minute:
                        try:
                            await redis_client.decrby(minute_key, count)
                        except Exception:
                            pass
                        if sec_key and sec_incremented:
                            try:
                                await redis_client.decrby(sec_key, count)
                            except Exception:
                                pass
                        minute_key = None
                        logger.warning(
                            "provider_minute_quota_exceeded",
                            provider=prov,
                            used=used_min,
                            limit=limits.per_minute,
                            count=count,
                        )
                        return False

                # 3. Daily limit check
                if limits.per_day is not None and daily_key:
                    try:
                        used_today = await redis_client.incrby(daily_key, count)
                        daily_incremented = True
                        if used_today == count:
                            try:
                                await redis_client.expire(daily_key, 90000)
                            except Exception:
                                pass
                        if used_today > limits.per_day:
                            try:
                                await redis_client.decrby(daily_key, count)
                            except Exception:
                                pass
                            daily_incremented = False
                            if sec_key and sec_incremented:
                                try:
                                    await redis_client.decrby(sec_key, count)
                                except Exception:
                                    pass
                            if minute_key:
                                try:
                                    await redis_client.decrby(minute_key, count)
                                except Exception:
                                    pass
                                minute_key = None
                            logger.warning(
                                "provider_daily_quota_exceeded",
                                provider=prov,
                                used=used_today,
                                limit=limits.per_day,
                                count=count,
                            )
                            return False
                    except Exception as daily_err:
                        if daily_incremented:
                            try:
                                await redis_client.decrby(daily_key, count)
                            except Exception:
                                pass
                            daily_incremented = False
                        if sec_key and sec_incremented:
                            try:
                                await redis_client.decrby(sec_key, count)
                            except Exception:
                                pass
                        if minute_key:
                            try:
                                await redis_client.decrby(minute_key, count)
                            except Exception:
                                pass
                            minute_key = None
                        raise daily_err

                return True
            except Exception as e:
                if daily_incremented and daily_key:
                    try:
                        await redis_client.decrby(daily_key, count)
                    except Exception:
                        pass
                if sec_key and sec_incremented:
                    try:
                        await redis_client.decrby(sec_key, count)
                    except Exception:
                        pass
                if minute_key:
                    try:
                        await redis_client.decrby(minute_key, count)
                    except Exception:
                        pass
                logger.warning("provider_quota_redis_error_fallback", provider=prov, error=str(e))
                if is_prod:
                    logger.error("provider_quota_redis_failure_in_production_fail_closed", provider=prov, error=str(e))
                    return False
                # Fall through to in-memory governor (dev/test only)

        # ── 2. In-Memory Tier (Process-local fallback for dev/test) ──
        async with self._lock:
            # Check daily
            if limits.per_day is not None:
                day_key = (prov, today_str)
                current_day_count = self._daily_counts.get(day_key, 0)
                if current_day_count + count > limits.per_day:
                    logger.warning(
                        "provider_in_memory_daily_quota_exceeded",
                        provider=prov,
                        used=current_day_count,
                        limit=limits.per_day,
                        count=count,
                    )
                    return False

            # Check second sliding window
            if limits.per_second is not None:
                window_sec = now_epoch - 1.0
                sec_calls = self._sec_calls.get(prov, [])
                sec_calls = [t for t in sec_calls if t > window_sec]
                if len(sec_calls) + count > limits.per_second:
                    logger.warning(
                        "provider_in_memory_second_quota_exceeded",
                        provider=prov,
                        used=len(sec_calls),
                        limit=limits.per_second,
                        count=count,
                    )
                    self._sec_calls[prov] = sec_calls
                    return False
                for _ in range(count):
                    sec_calls.append(now_epoch)
                self._sec_calls[prov] = sec_calls

            # Check minute sliding window
            if limits.per_minute is not None:
                window_start = now_epoch - 60.0
                calls = self._minute_calls.get(prov, [])
                calls = [t for t in calls if t > window_start]
                if len(calls) + count > limits.per_minute:
                    logger.warning(
                        "provider_in_memory_minute_quota_exceeded",
                        provider=prov,
                        used=len(calls),
                        limit=limits.per_minute,
                        count=count,
                    )
                    self._minute_calls[prov] = calls
                    return False
                for _ in range(count):
                    calls.append(now_epoch)
                self._minute_calls[prov] = calls

            # Increment daily
            if limits.per_day is not None:
                day_key = (prov, today_str)
                self._daily_counts[day_key] = self._daily_counts.get(day_key, 0) + count

            return True

    def reset(self) -> None:
        """Reset in-memory counters (useful for unit testing)."""
        self._sec_calls.clear()
        self._minute_calls.clear()
        self._daily_counts.clear()

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
