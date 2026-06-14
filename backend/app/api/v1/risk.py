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
    if cached:
        cached.pop("_cache_hit", None)
        cached.pop("_cached_at", None)
        return {
            "success": True,
            "data": cached,
            "freshness": FreshnessMetadata(
                source="cache",
                timestamp=datetime.now(timezone.utc),
                is_stale=False,
                delay_label="Cached",
                cache_hit=True,
            ).model_dump(),
        }

    result = await get_governance_data(symbol)

    if result.get("error"):
        return {"success": False, "message": result.get("message")}

    await cache.set(cache_key, result, ttl=3600)

    return {
        "success": True,
        "data": result,
        "freshness": FreshnessMetadata(
            source="yahoo_finance",
            timestamp=datetime.now(timezone.utc),
            is_stale=False,
            delay_label="~15s delayed",
            cache_hit=False,
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

    # Try cache first
    cached = await cache.get(cache.risk_key(symbol))
    if cached:
        cached.pop("_cache_hit", None)
        cached.pop("_cached_at", None)
        return {
            "success": True,
            "data": cached,
            "freshness": FreshnessMetadata(
                source="cache",
                timestamp=datetime.now(timezone.utc),
                is_stale=False,
                delay_label="Cached",
                cache_hit=True,
            ).model_dump(),
        }

    # Compute fresh risk score
    engine = RiskEngine()
    result = await engine.compute_risk(symbol)

    # Cache for 10 minutes
    await cache.set(cache.risk_key(symbol), result, ttl=600)

    return {
        "success": True,
        "data": result,
        "freshness": FreshnessMetadata(
            source="yahoo_finance",
            timestamp=datetime.now(timezone.utc),
            is_stale=False,
            delay_label="~15s delayed",
            cache_hit=False,
        ).model_dump(),
    }

