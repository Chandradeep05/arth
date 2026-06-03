"""
Market data API endpoints.

Provides REST endpoints for:
- Stock quotes (cached, with freshness metadata)
- Historical OHLCV data
- Market indices (NIFTY 50, SENSEX, S&P 500, NASDAQ)
- Stock search
- Technical indicators

All responses include:
- FreshnessMetadata (source, timestamp, staleness flag, delay label)
- Trace ID (from middleware)
- Graceful degradation (cached data if source fails)
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query

from app.config import Settings, get_settings
from app.core.exceptions import SymbolNotFoundError
from app.core.logging import get_logger
from app.data.adapters.yahoo import YahooFinanceAdapter
from app.data.cache import CacheManager
from app.dependencies import get_redis
from app.models.schemas.market import (
    FreshnessMetadata,
    MarketIndex,
    MarketOverviewResponse,
    OHLCVBar,
    OHLCVResponse,
    SearchResponse,
    SearchResult,
    StockQuote,
    StockQuoteResponse,
)

logger = get_logger(__name__)
router = APIRouter(prefix="/market", tags=["market"])

# Singleton adapter (stateless except for circuit breaker)
_yahoo_adapter = YahooFinanceAdapter()


def _make_freshness(
    source: str = "yahoo_finance",
    cache_hit: bool = False,
    settings: Settings | None = None,
) -> FreshnessMetadata:
    """Build freshness metadata for a response."""
    return FreshnessMetadata(
        source=source,
        timestamp=datetime.now(timezone.utc),
        is_stale=False,
        delay_label="~15s delayed",
        cache_hit=cache_hit,
    )


@router.get("/quote/{symbol}", response_model=StockQuoteResponse)
async def get_quote(
    symbol: str,
    redis=Depends(get_redis),
    settings: Settings = Depends(get_settings),
):
    """
    Get current stock quote for a symbol.

    Examples:
    - /api/v1/market/quote/RELIANCE.NS (NSE)
    - /api/v1/market/quote/AAPL (US)
    - /api/v1/market/quote/TCS.BO (BSE)
    """
    cache = CacheManager(redis)

    data = await cache.get_or_fetch(
        key=cache.quote_key(symbol),
        fetch_func=_yahoo_adapter.get_quote,
        ttl=settings.redis_cache_ttl_tick,
        symbol=symbol,
    )

    if data is None:
        raise SymbolNotFoundError(symbol)

    cache_hit = data.pop("_cache_hit", False)
    data.pop("_cached_at", None)

    return StockQuoteResponse(
        data=StockQuote(**data),
        freshness=_make_freshness(cache_hit=cache_hit),
    )


@router.get("/ohlcv/{symbol}", response_model=OHLCVResponse)
async def get_ohlcv(
    symbol: str,
    period: str = Query(default="1mo", description="1d, 5d, 1mo, 3mo, 6mo, 1y, 2y, 5y, max"),
    interval: str = Query(default="1d", description="1m, 5m, 15m, 1h, 1d, 1wk, 1mo"),
    redis=Depends(get_redis),
    settings: Settings = Depends(get_settings),
):
    """Get historical OHLCV data for charting."""
    cache = CacheManager(redis)
    cache_key = cache.ohlcv_key(symbol, period, interval)
    cache_hit = False

    # Try cache first (stored as {"bars": [...]})
    cached = await cache.get(cache_key)
    if cached and "bars" in cached:
        cached.pop("_cache_hit", None)
        cached.pop("_cached_at", None)
        bars = cached["bars"]
        cache_hit = True
    else:
        # Fetch fresh from Yahoo
        bars = await _yahoo_adapter.get_ohlcv(symbol, period=period, interval=interval)
        if bars is None:
            raise SymbolNotFoundError(symbol)
        # Cache as a dict wrapper so CacheManager can add metadata
        await cache.set(cache_key, {"bars": bars}, ttl=settings.redis_cache_ttl_indicators)

    return OHLCVResponse(
        symbol=symbol.upper(),
        timeframe=interval,
        data=[OHLCVBar(**bar) for bar in bars],
        freshness=_make_freshness(cache_hit=cache_hit),
    )


@router.get("/indices", response_model=MarketOverviewResponse)
async def get_indices(
    redis=Depends(get_redis),
    settings: Settings = Depends(get_settings),
):
    """Get major market indices: NIFTY 50, SENSEX, S&P 500, NASDAQ."""
    cache = CacheManager(redis)
    cache_key = cache.indices_key()
    cache_hit = False

    # Try cache first
    cached = await cache.get(cache_key)
    if cached and "indices" in cached:
        cached.pop("_cache_hit", None)
        cached.pop("_cached_at", None)
        indices_list = cached["indices"]
        cache_hit = True
    else:
        # Fetch fresh
        indices_list = await _yahoo_adapter.get_market_indices()
        if indices_list:
            await cache.set(cache_key, {"indices": indices_list}, ttl=settings.redis_cache_ttl_tick)
        else:
            indices_list = []

    return MarketOverviewResponse(
        indices=[MarketIndex(**idx) for idx in indices_list],
        freshness=_make_freshness(cache_hit=cache_hit),
    )


@router.get("/search", response_model=SearchResponse)
async def search_stocks(
    q: str = Query(description="Search query (stock name or symbol)"),
):
    """Search for stocks by name or symbol."""
    results = await _yahoo_adapter.search(q)

    return SearchResponse(
        query=q,
        results=[SearchResult(**r) for r in results],
    )


@router.get("/company/{symbol}")
async def get_company_info(
    symbol: str,
    redis=Depends(get_redis),
    settings: Settings = Depends(get_settings),
):
    """Get company fundamentals and metadata."""
    cache = CacheManager(redis)

    data = await cache.get_or_fetch(
        key=cache.company_key(symbol),
        fetch_func=_yahoo_adapter.get_company_info,
        ttl=settings.redis_cache_ttl_fundamentals,
        symbol=symbol,
    )

    if data is None:
        raise SymbolNotFoundError(symbol)

    cache_hit = data.pop("_cache_hit", False)
    data.pop("_cached_at", None)

    return {
        "success": True,
        "data": data,
        "freshness": _make_freshness(cache_hit=cache_hit).model_dump(),
    }


@router.get("/indicators/{symbol}")
async def get_indicators(
    symbol: str,
    redis=Depends(get_redis),
    settings: Settings = Depends(get_settings),
):
    """Get computed technical indicators for a symbol."""
    from app.engines.market.indicators import compute_indicators

    cache = CacheManager(redis)

    # Try cache first
    cached = await cache.get(cache.indicators_key(symbol))
    if cached:
        cached.pop("_cache_hit", None)
        cached.pop("_cached_at", None)
        return {
            "success": True,
            "data": {"symbol": symbol.upper(), **cached},
            "freshness": _make_freshness(cache_hit=True).model_dump(),
        }

    # Fetch OHLCV and compute indicators
    ohlcv = await _yahoo_adapter.get_ohlcv(symbol, period="3mo", interval="1d")
    if not ohlcv:
        raise SymbolNotFoundError(symbol)

    indicators = compute_indicators(ohlcv)
    if indicators is None:
        return {
            "success": False,
            "message": "Insufficient data for indicator computation",
        }

    # Cache for 60s
    await cache.set(cache.indicators_key(symbol), indicators, ttl=settings.redis_cache_ttl_indicators)

    return {
        "success": True,
        "data": {"symbol": symbol.upper(), **indicators},
        "freshness": _make_freshness(cache_hit=False).model_dump(),
    }


@router.get("/health")
async def market_health():
    """Health check for the market data subsystem."""
    adapter_health = _yahoo_adapter.get_health()
    return {
        "adapter": adapter_health.__dict__,
        "status": "healthy" if adapter_health.is_healthy else "degraded",
    }
