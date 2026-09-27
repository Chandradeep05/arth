"""
Risk Intelligence API endpoints.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends

from app.config import Settings, get_settings
from app.core.logging import get_logger
from app.data.cache import CacheManager
from app.dependencies import get_redis
from app.engines.risk.engine import RiskEngine
from app.models.schemas.market import FreshnessMetadata

logger = get_logger(__name__)
router = APIRouter(prefix="/risk", tags=["risk"])


# ── Specific routes MUST come before parameterized /{symbol} ──

@router.get("/governance/{symbol}")
async def get_governance(
    symbol: str,
    redis=Depends(get_redis),
    settings: Settings = Depends(get_settings),
):
    """Get governance data and score for a stock symbol.

    Includes: institutional ownership, insider ownership, pledge %,
    major holders, and a governance score (0-100).
    """
    from app.engines.governance.engine import get_governance_data

    cache = CacheManager(redis)
    cache_key = f"governance:{symbol.upper()}"

    # Try cache (governance data changes slowly — 1hr TTL)
    cached = await cache.get(cache_key)
    was_cached = cached is not None
    if not was_cached:
        result = await cache.get_or_fetch(
            key=cache_key,
            fetch_func=get_governance_data,
            ttl=3600,
            symbol=symbol,
        )
    else:
        result = cached

    if not result:
        return {"success": False, "message": f"Could not fetch governance data for {symbol}"}
    if result.get("error"):
        return {"success": False, "message": result.get("message")}

    result.pop("_cache_hit", None)
    result.pop("_cached_at", None)

    return {
        "success": True,
        "data": result,
        "freshness": FreshnessMetadata(
            source="cache" if was_cached else "yahoo_finance",
            timestamp=datetime.now(timezone.utc),
            is_stale=False,
            delay_label="Cached" if was_cached else "~15s delayed",
            cache_hit=was_cached,
        ).model_dump(),
    }


# ── Catch-all parameterized route MUST come last ──

@router.get("/{symbol}")
async def get_risk_score(
    symbol: str,
    redis=Depends(get_redis),
    settings: Settings = Depends(get_settings),
):
    """Get composite risk score for a stock symbol."""
    cache = CacheManager(redis)

    # Try cache first or stampede-protected fetch
    cached = await cache.get(cache.risk_key(symbol))
    was_cached = cached is not None
    if not was_cached:
        engine = RiskEngine()
        result = await cache.get_or_fetch(
            key=cache.risk_key(symbol),
            fetch_func=engine.compute_risk,
            ttl=600,
            symbol=symbol,
        )
    else:
        result = cached

    if not result:
        result = {}

    result.pop("_cache_hit", None)
    result.pop("_cached_at", None)

    return {
        "success": True,
        "data": result,
        "freshness": FreshnessMetadata(
            source="cache" if was_cached else "yahoo_finance",
            timestamp=datetime.now(timezone.utc),
            is_stale=False,
            delay_label="Cached" if was_cached else "~15s delayed",
            cache_hit=was_cached,
        ).model_dump(),
    }

