"""
ARTH Central Provider Quota Governor.

Tracks and enforces per-second, per-minute, and per-day rate and budget quotas across
external market data providers:
- Twelve Data: 8 requests/min, 800 requests/day (Free tier)
- Finnhub: 30 requests/sec, 60 requests/min, 10,000 requests/day (Free tier)
- Financial Modeling Prep (FMP): 250 requests/day (Basic tier)
- Upstox: 10 requests/sec, 300 requests/min, 10,000 requests/day (Standard API tier)
- NSE: 5 requests/sec, 30 requests/min, 3,000 requests/day

Architecture & Concurrency Invariants:
1. Production Quota Reservations MUST Use Atomic Distributed Lua:
   In production, quota reservation is strictly mediated via an atomic Redis Lua script
   evaluating sliding-window sorted sets for sub-second and per-minute burst limits,
   and daily budget counters.
2. Production Fails Closed:
   If Redis is unreachable, times out, throws any error, lacks Lua eval capability,
   or returns an unexpected value, production MUST FAIL CLOSED (acquire returns False).
   Production NEVER falls back to non-atomic Redis commands or process-local in-memory state.
3. Fail-Closed Environment Detection:
   Any failure or ambiguity in loading application settings (validation errors, missing
   configuration, import errors) defaults to True (production), guaranteeing that configuration
   faults cannot accidentally open permissions to process-local quotas.
4. Consistent Sliding Window Semantics:
   Both the distributed Redis tier (via ZSET sliding log with TTL expiration) and the
   in-memory dev/test fallback (via timestamp sliding windows under an asyncio Lock)
   enforce rolling sliding windows, completely preventing window-boundary burst exploits.
5. Development / Test Boundary:
   Non-atomic command fallback and process-local in-memory state exist ONLY behind an
   explicit, verified non-production boundary (app_env in DEVELOPMENT, STAGING).
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import os
import time
from typing import Dict, Optional, Tuple
from uuid import uuid4

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


# Provider quota configuration matching verified documentation & limits
PROVIDER_LIMITS: Dict[str, ProviderLimit] = {
    "twelvedata": ProviderLimit(per_second=None, per_minute=8, per_day=800),
    "finnhub": ProviderLimit(per_second=30, per_minute=60, per_day=10000),
    "fmp": ProviderLimit(per_second=None, per_minute=None, per_day=250),
    "upstox": ProviderLimit(per_second=10, per_minute=300, per_day=10000),
    "nse": ProviderLimit(per_second=5, per_minute=30, per_day=3000),
}

# Atomic Distributed Sliding-Window Quota Lua Script
# KEYS[1]: second rolling sorted-set key
# KEYS[2]: minute rolling sorted-set key
# KEYS[3]: daily counter key
# ARGV[1]: count
# ARGV[2]: sec_limit (-1 if disabled)
# ARGV[3]: min_limit (-1 if disabled)
# ARGV[4]: day_limit (-1 if disabled)
# ARGV[5]: now_ms (current unix timestamp in milliseconds)
# ARGV[6]: req_seed (unique batch ID prefix for member deduplication)
_ATOMIC_SLIDING_QUOTA_LUA = """
local sec_key = KEYS[1]
local min_key = KEYS[2]
local day_key = KEYS[3]

local count = tonumber(ARGV[1])
local sec_limit = tonumber(ARGV[2])
local min_limit = tonumber(ARGV[3])
local day_limit = tonumber(ARGV[4])
local now_ms = tonumber(ARGV[5])
local req_seed = ARGV[6]

local has_sec = sec_limit > 0
local has_min = min_limit > 0
local has_day = day_limit > 0

-- 1. Check per-second rolling sliding window (window: [now_ms - 1000, now_ms])
if has_sec then
    redis.call('ZREMRANGEBYSCORE', sec_key, '-inf', now_ms - 1000)
    local cur_sec = redis.call('ZCARD', sec_key)
    if cur_sec + count > sec_limit then
        return -2 -- Rejected on second burst limit
    end
end

-- 2. Check per-minute rolling sliding window (window: [now_ms - 60000, now_ms])
if has_min then
    redis.call('ZREMRANGEBYSCORE', min_key, '-inf', now_ms - 60000)
    local cur_min = redis.call('ZCARD', min_key)
    if cur_min + count > min_limit then
        return 0 -- Rejected on minute limit
    end
end

-- 3. Check daily budget limit
if has_day then
    local cur_day = tonumber(redis.call('GET', day_key) or '0')
    if cur_day + count > day_limit then
        return -1 -- Rejected on daily limit
    end
end

-- All checks passed atomically. Record reservations.
if has_sec then
    for i = 1, count do
        redis.call('ZADD', sec_key, now_ms, req_seed .. ':' .. i)
    end
    redis.call('EXPIRE', sec_key, 10)
end

if has_min then
    for i = 1, count do
        redis.call('ZADD', min_key, now_ms, req_seed .. ':' .. i)
    end
    redis.call('EXPIRE', min_key, 120)
end

if has_day then
    redis.call('INCRBY', day_key, count)
    local ttl = redis.call('TTL', day_key)
    if ttl < 0 then
        redis.call('EXPIRE', day_key, 90000)
    end
end

return 1 -- Allowed
"""


def is_production_environment() -> bool:
    """
    Authoritative production environment detection.

    FAILS CLOSED: Any failure to safely determine the environment (missing settings,
    validation errors, import errors, corrupt environment variables, or unrecognized values)
    defaults to True (production). This ensures process-local quota fallback can NEVER
    be reached during configuration failures or ambiguous states.
    """
    raw_env = (os.environ.get("APP_ENV") or os.environ.get("ENVIRONMENT") or "").strip().lower()
    if raw_env in ("production", "prod"):
        return True

    try:
        from app.config import get_settings, Environment
        settings = get_settings()
        if settings.is_production or settings.app_env == Environment.PRODUCTION:
            return True
        # Explicit, verified non-production environment:
        if settings.app_env in (Environment.DEVELOPMENT, Environment.STAGING):
            if raw_env in ("production", "prod"):
                return True
            return False
        # Unrecognized enum or corrupt configuration -> fail closed
        return True
    except Exception as e:
        logger.error("provider_quota_env_detection_failed_fail_closed", error=str(e))
        return True


class ProviderQuotaGovernor:
    """Centralized governor ensuring ARTH never exceeds external provider API quotas."""

    def __init__(self):
        self._lock = asyncio.Lock()
        # In-memory sliding log tracking for dev/test: provider -> [timestamp, ...]
        self._sec_calls: Dict[str, list[float]] = {}
        self._minute_calls: Dict[str, list[float]] = {}
        # In-memory daily tracking for dev/test: (provider, date_str) -> count
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
        now_ms = int(now_epoch * 1000)

        is_prod = is_production_environment()

        # ── 1. Production Mode: Strict Atomic Distributed Enforcement (Fail-Closed) ──
        if is_prod:
            if redis_client is None:
                logger.error("provider_quota_redis_unavailable_in_production_fail_closed", provider=prov)
                return False

            if not hasattr(redis_client, "eval"):
                logger.error("provider_quota_redis_eval_unsupported_in_production_fail_closed", provider=prov)
                return False

            sec_key = f"quota:provider:{prov}:sec_zset"
            min_key = f"quota:provider:{prov}:min_zset"
            daily_key = f"quota:provider:{prov}:daily:{today_str}"
            batch_id = f"{now_ms}_{uuid4().hex[:12]}"

            try:
                res = await redis_client.eval(
                    _ATOMIC_SLIDING_QUOTA_LUA,
                    3,
                    sec_key,
                    min_key,
                    daily_key,
                    count,
                    limits.per_second if limits.per_second is not None else -1,
                    limits.per_minute if limits.per_minute is not None else -1,
                    limits.per_day if limits.per_day is not None else -1,
                    now_ms,
                    batch_id,
                )
            except Exception as lua_err:
                # Catch ANY Redis execution error, network timeout, or connection drop.
                # In production, NO fallback to commands or in-memory is permitted.
                logger.error(
                    "provider_quota_redis_lua_execution_failed_fail_closed",
                    provider=prov,
                    error=str(lua_err),
                    error_type=type(lua_err).__name__,
                )
                return False

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
            else:
                logger.error(
                    "provider_quota_unexpected_lua_return_value_fail_closed",
                    provider=prov,
                    return_value=res,
                )
                return False

        # ── 2. Development / Test Mode: Distributed Redis if available, else In-Memory Sliding Log ──
        if redis_client is not None:
            sec_key = f"quota:provider:{prov}:sec_zset"
            min_key = f"quota:provider:{prov}:min_zset"
            daily_key = f"quota:provider:{prov}:daily:{today_str}"
            batch_id = f"{now_ms}_{uuid4().hex[:12]}"

            # Attempt atomic Lua if supported by the Redis client
            if hasattr(redis_client, "eval"):
                try:
                    res = await redis_client.eval(
                    _ATOMIC_SLIDING_QUOTA_LUA,
                    3,
                    sec_key,
                    min_key,
                    daily_key,
                    count,
                    limits.per_second if limits.per_second is not None else -1,
                    limits.per_minute if limits.per_minute is not None else -1,
                    limits.per_day if limits.per_day is not None else -1,
                    now_ms,
                    batch_id,
                )
                    if res == 1:
                        return True
                    elif res in (-2, 0, -1):
                        return False
                except Exception as dev_redis_err:
                    logger.warning("provider_quota_dev_redis_eval_failed_fallback", error=str(dev_redis_err))

            # Non-production command fallback with rollback (for unit test mock instances without Lua support)
            if hasattr(redis_client, "incrby"):
                minute_incremented = False
                daily_incremented = False
                try:
                    if limits.per_minute is not None:
                        used_min = await redis_client.incrby(min_key, count)
                        minute_incremented = True
                        if used_min == count and hasattr(redis_client, "expire"):
                            try:
                                await redis_client.expire(min_key, 120)
                            except Exception:
                                pass
                        if used_min > limits.per_minute:
                            if hasattr(redis_client, "decrby"):
                                try:
                                    await redis_client.decrby(min_key, count)
                                except Exception:
                                    pass
                            minute_incremented = False
                            return False

                    if limits.per_day is not None:
                        try:
                            used_today = await redis_client.incrby(daily_key, count)
                            daily_incremented = True
                            if used_today == count and hasattr(redis_client, "expire"):
                                try:
                                    await redis_client.expire(daily_key, 90000)
                                except Exception:
                                    pass
                            if used_today > limits.per_day:
                                if hasattr(redis_client, "decrby"):
                                    try:
                                        await redis_client.decrby(daily_key, count)
                                    except Exception:
                                        pass
                                daily_incremented = False
                                if minute_incremented and hasattr(redis_client, "decrby"):
                                    try:
                                        await redis_client.decrby(min_key, count)
                                    except Exception:
                                        pass
                                    minute_incremented = False
                                return False
                        except Exception as daily_err:
                            if daily_incremented and hasattr(redis_client, "decrby"):
                                try:
                                    await redis_client.decrby(daily_key, count)
                                except Exception:
                                    pass
                                daily_incremented = False
                            if minute_incremented and hasattr(redis_client, "decrby"):
                                try:
                                    await redis_client.decrby(min_key, count)
                                except Exception:
                                    pass
                                minute_incremented = False
                            raise daily_err

                    return True
                except Exception as cmd_err:
                    if daily_incremented and hasattr(redis_client, "decrby"):
                        try:
                            await redis_client.decrby(daily_key, count)
                        except Exception:
                            pass
                    if minute_incremented and hasattr(redis_client, "decrby"):
                        try:
                            await redis_client.decrby(min_key, count)
                        except Exception:
                            pass
                    logger.warning("provider_quota_dev_redis_commands_failed_falling_back_to_memory", error=str(cmd_err))

        # In-Memory sliding-log fallback for local development and unit tests
        async with self._lock:
            # 1. Daily limit check
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

            # 2. Per-second rolling sliding window check
            if limits.per_second is not None:
                window_sec = now_epoch - 1.0
                sec_calls = [t for t in self._sec_calls.get(prov, []) if t > window_sec]
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

            # 3. Per-minute rolling sliding window check
            if limits.per_minute is not None:
                window_min = now_epoch - 60.0
                min_calls = [t for t in self._minute_calls.get(prov, []) if t > window_min]
                if len(min_calls) + count > limits.per_minute:
                    logger.warning(
                        "provider_in_memory_minute_quota_exceeded",
                        provider=prov,
                        used=len(min_calls),
                        limit=limits.per_minute,
                        count=count,
                    )
                    self._minute_calls[prov] = min_calls
                    return False

            # All checks passed. Atomically record reservations under lock.
            if limits.per_day is not None:
                day_key = (prov, today_str)
                self._daily_counts[day_key] = self._daily_counts.get(day_key, 0) + count

            if limits.per_second is not None:
                for _ in range(count):
                    sec_calls.append(now_epoch)
                self._sec_calls[prov] = sec_calls

            if limits.per_minute is not None:
                for _ in range(count):
                    min_calls.append(now_epoch)
                self._minute_calls[prov] = min_calls

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
            calls_min = [t for t in self._minute_calls.get(prov, []) if t > now_epoch - 60.0]
            calls_sec = [t for t in self._sec_calls.get(prov, []) if t > now_epoch - 1.0]
            res[prov] = {
                "daily_used": daily_used,
                "daily_limit": limits.per_day,
                "minute_used": len(calls_min),
                "minute_limit": limits.per_minute,
                "second_used": len(calls_sec),
                "second_limit": limits.per_second,
            }
        return res


# Global singleton instance
quota_governor = ProviderQuotaGovernor()
