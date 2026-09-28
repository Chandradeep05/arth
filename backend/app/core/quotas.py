"""
ARTH Phase 4 -- Per-User Rate Quotas

Layer 3 of rate limiting (on top of the existing Phase 3 IP-based limits):
  Layer 1: IP-based rate limit (RateLimitMiddleware from Phase 3)
  Layer 2: User burst rate limit (short window, prevents request spikes)
  Layer 3: Daily/hourly feature quotas (expensive operations)

Reuses the sliding window pattern from rate_limiter.py.
Keys: user:{user_id}:quota:{endpoint_group}
"""

from __future__ import annotations

import asyncio
import time
from typing import Dict, List
from uuid import UUID

from fastapi import HTTPException

from app.core.logging import get_logger

logger = get_logger(__name__)

# Fallback in-memory quota tracking when Redis is unavailable in non-dev environments
_in_memory_quotas: Dict[str, List[float]] = {}
_in_memory_lock = asyncio.Lock()

# Endpoint group definitions: (window_seconds, max_requests)
QUOTA_CONFIG = {
    "chat": (3600, 30),         # 30 messages per hour
    "research_gen": (86400, 10), # 10 deep research reports per day
    "prediction": (86400, 20),   # 20 forecasts per day
    "accuracy": (3600, 5),       # 5 backtests per hour
}


async def check_user_quota(
    user_id: UUID,
    endpoint_group: str,
    redis,
    *,
    max_requests: int = None,
    window_seconds: int = None,
) -> None:
    """
    Check and increment per-user quota counter.
    Raises HTTP 429 if the user has exceeded their quota.

    Uses Redis ZADD sliding window -- same mechanism as Phase 3 rate_limiter.py.
    Key format: user:{user_id}:quota:{endpoint_group}

    Args:
        user_id: The authenticated user's ID
        endpoint_group: One of 'chat', 'research_gen', 'prediction'
        redis: Active Redis connection
        max_requests: Override default from QUOTA_CONFIG
        window_seconds: Override default from QUOTA_CONFIG
    """
    config = QUOTA_CONFIG.get(endpoint_group)
    if config:
        win_secs, max_req = config
    else:
        win_secs, max_req = 3600, 30  # Safe fallback

    if max_requests is not None:
        max_req = max_requests
    if window_seconds is not None:
        win_secs = window_seconds

    key = f"user:{user_id}:quota:{endpoint_group}"
    now = time.time()
    window_start = now - win_secs

    if redis is None:
        try:
            from app.config import get_settings
            is_dev = get_settings().is_development
        except Exception:
            is_dev = True

        if is_dev:
            # In local development, skip quota enforcement
            return

        # In production / non-development, do NOT fail open!
        # Enforce quota limits per process using an in-memory sliding window counter.
        async with _in_memory_lock:
            timestamps = _in_memory_quotas.get(key, [])
            valid_timestamps = [t for t in timestamps if t > window_start]
            if len(valid_timestamps) >= max_req:
                logger.warning(
                    "user_quota_exceeded_fallback",
                    user_id=str(user_id),
                    endpoint_group=endpoint_group,
                    count=len(valid_timestamps),
                    limit=max_req,
                    window_seconds=win_secs,
                )
                raise HTTPException(
                    status_code=429,
                    detail=(
                        f"Quota exceeded for {endpoint_group}: "
                        f"{max_req} requests per {win_secs // 3600}h window. "
                        f"Try again later."
                    ),
                )
            valid_timestamps.append(now)
            _in_memory_quotas[key] = valid_timestamps
        return

    # Atomic quota check via Lua script:
    # 1. Remove expired entries
    # 2. Count remaining
    # 3. If under limit, add new entry and return 1 (allowed)
    # 4. If at/over limit, return 0 (rejected)
    _QUOTA_LUA = """
    redis.call('zremrangebyscore', KEYS[1], 0, ARGV[1])
    local count = redis.call('zcard', KEYS[1])
    if count < tonumber(ARGV[2]) then
        redis.call('zadd', KEYS[1], ARGV[3], ARGV[4])
        redis.call('expire', KEYS[1], tonumber(ARGV[5]))
        return count + 1
    else
        redis.call('expire', KEYS[1], tonumber(ARGV[5]))
        return -1
    end
    """
    import secrets as _secrets
    member = f"{now}:{_secrets.token_hex(4)}"  # Unique member to prevent collision
    result = await redis.eval(
        _QUOTA_LUA,
        1,  # number of keys
        key,  # KEYS[1]
        str(window_start),  # ARGV[1] - window start
        str(max_req),       # ARGV[2] - limit
        str(now),           # ARGV[3] - score
        member,             # ARGV[4] - unique member
        str(win_secs + 10), # ARGV[5] - TTL
    )

    if result == -1:
        logger.warning(
            "user_quota_exceeded",
            user_id=str(user_id),
            endpoint_group=endpoint_group,
            count=max_req,
            limit=max_req,
            window_seconds=win_secs,
        )
        raise HTTPException(
            status_code=429,
            detail=(
                f"Quota exceeded for {endpoint_group}: "
                f"{max_req} requests per {win_secs // 3600}h window. "
                f"Try again later."
            ),
        )

    logger.debug(
        "user_quota_ok",
        user_id=str(user_id),
        endpoint_group=endpoint_group,
        count=result,
        limit=max_req,
    )
