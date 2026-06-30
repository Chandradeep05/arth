"""
Financial Statements API endpoints (Phase 2).

Provides REST endpoints for:
- Structured financial statements (income, balance sheet, cash flow)
- Computed financial ratios with YoY trends
- Financial health scorecard (0-100)

All responses include FreshnessMetadata and are cached via Redis
with a 24h TTL (fundamentals change infrequently).
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends

from app.config import Settings, get_settings
from app.core.exceptions import DataSourceError, SymbolNotFoundError
from app.core.logging import get_logger
from app.data.cache import CacheManager
from app.dependencies import get_redis
from app.engines.research.statement_parser import StatementParser
from app.models.schemas.market import FreshnessMetadata

logger = get_logger(__name__)
router = APIRouter(prefix="/financials", tags=["financials"])

# Singleton parser instance (stateless)
_parser = StatementParser()


def _make_freshness(
    source: str = "yahoo_finance",
    cache_hit: bool = False,
) -> FreshnessMetadata:
    """Build freshness metadata for a financials response."""
    return FreshnessMetadata(
        source=source,
        timestamp=datetime.now(timezone.utc),
        is_stale=False,
        delay_label="Reported data",
        cache_hit=cache_hit,
    )


@router.get("/{symbol}/statements")
async def get_statements(
    symbol: str,
    redis=Depends(get_redis),
    settings: Settings = Depends(get_settings),
):
    """Get structured financial statements (income, balance sheet, cash flow).

    Returns annual and quarterly data for each statement type,
    with each period containing all available line items.
    """
    cache = CacheManager(redis)
    cache_key = CacheManager.financials_key(symbol)

    # Try cache first
    cached = await cache.get(cache_key)
    if cached:
        cached.pop("_cache_hit", None)
        cached.pop("_cached_at", None)
        return {
            "success": True,
            "data": cached,
            "freshness": _make_freshness(source="cache", cache_hit=True).model_dump(),
        }

    # Fetch fresh
    try:
        data = await _parser.get_statements(symbol)
    except Exception as e:
        logger.error("financials_fetch_failed", symbol=symbol, error=str(e))
        err_msg = str(e).lower()
        if "rate" in err_msg or "too many" in err_msg or "429" in err_msg:
            raise DataSourceError(
                source="Yahoo Finance",
                message=f"Rate limited — financials for '{symbol}' temporarily unavailable.",
            )
        raise SymbolNotFoundError(symbol)

    if data.get("error") and data["periods_available"]["annual"] == 0:
        raise SymbolNotFoundError(symbol)

    # Cache for 24h (fundamentals TTL)
    await cache.set(cache_key, data, ttl=settings.redis_cache_ttl_fundamentals)

    return {
        "success": True,
        "data": data,
        "freshness": _make_freshness(cache_hit=False).model_dump(),
    }


@router.get("/{symbol}/ratios")
async def get_ratios(
    symbol: str,
    redis=Depends(get_redis),
    settings: Settings = Depends(get_settings),
):
    """Get computed financial ratios with historical trends.

    Includes ROE, ROA, current ratio, D/E, profit margin,
    operating margin, revenue growth, and free cash flow — each
    with current value, previous value, change, and direction.
    """
    cache = CacheManager(redis)
    cache_key = CacheManager.ratios_key(symbol)

    # Try cache first
    cached = await cache.get(cache_key)
    if cached:
        cached.pop("_cache_hit", None)
        cached.pop("_cached_at", None)
        return {
            "success": True,
            "data": cached,
            "freshness": _make_freshness(source="cache", cache_hit=True).model_dump(),
        }

    # Compute fresh
    try:
        data = await _parser.get_ratios(symbol)
    except Exception as e:
        logger.error("ratios_compute_failed", symbol=symbol, error=str(e))
        return {
            "success": False,
            "message": f"Failed to compute ratios for {symbol}: {str(e)}",
        }

    # Cache for 24h
    await cache.set(cache_key, data, ttl=settings.redis_cache_ttl_fundamentals)

    return {
        "success": True,
        "data": data,
        "freshness": _make_freshness(cache_hit=False).model_dump(),
    }


@router.get("/{symbol}/health-score")
async def get_health_score(
    symbol: str,
    redis=Depends(get_redis),
    settings: Settings = Depends(get_settings),
):
    """Get financial health scorecard (0-100 with category breakdown).

    Four categories scored 0-25 each:
    - Profitability (profit margin, ROE, ROA)
    - Solvency (D/E ratio, current ratio)
    - Efficiency (operating margin, FCF)
    - Growth (revenue growth, margin trend)
    """
    cache = CacheManager(redis)
    cache_key = CacheManager.health_key(symbol)

    # Try cache first
    cached = await cache.get(cache_key)
    if cached:
        cached.pop("_cache_hit", None)
        cached.pop("_cached_at", None)
        return {
            "success": True,
            "data": cached,
            "freshness": _make_freshness(source="cache", cache_hit=True).model_dump(),
        }

    # Compute fresh
    try:
        data = await _parser.get_health_score(symbol)
    except Exception as e:
        logger.error("health_score_failed", symbol=symbol, error=str(e))
        return {
            "success": False,
            "message": f"Failed to compute health score for {symbol}: {str(e)}",
        }

    # Cache for 24h
    await cache.set(cache_key, data, ttl=settings.redis_cache_ttl_fundamentals)

    return {
        "success": True,
        "data": data,
        "freshness": _make_freshness(cache_hit=False).model_dump(),
    }
