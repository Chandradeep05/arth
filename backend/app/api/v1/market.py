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
import math

from fastapi import APIRouter, Depends, Query

from app.config import Settings, get_settings
import pandas as pd
from app.core.exceptions import DataSourceError, SymbolNotFoundError
from app.core.logging import get_logger
from app.data.cache import CacheManager
from app.data.market_data_provider import market_data
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

# Alias for backwards compatibility with any internal caller
_yahoo_adapter = market_data


def _raise_data_error(symbol: str):
    """Raise the appropriate error when data source returns no data.

    Checks health across underlying providers (Upstox, NSE, TwelveData)
    to detect rate limiting and provider circuit trips.
    """
    is_indian = symbol.upper().endswith(('.NS', '.BO'))
    chain = ["upstox", "nse"] if is_indian else ["twelvedata", "finnhub"]
    health_dict = market_data.get_health()

    is_rate_limited = False
    is_circuit_open = False
    is_recent_failure = False

    for prov in chain:
        h = health_dict.get(prov, {})
        err = str(h.get("last_error_message", "")).lower()
        if any(kw in err for kw in ["rate", "429", "too many", "crumb", "cooldown"]):
            is_rate_limited = True
        if h.get("circuit_state", "closed") != "closed":
            is_circuit_open = True
        if h.get("failure_count", 0) > 0 and h.get("last_failure") is not None:
            is_recent_failure = True

    # Also check TwelveData cooldown directly
    twelvedata_adapter = market_data._twelve
    if not is_indian and twelvedata_adapter:
        try:
            if getattr(twelvedata_adapter, "is_cooling_down", False) or bool(twelvedata_adapter._cache_get("_rate_limit_cooldown")):
                is_rate_limited = True
        except Exception:
            pass

    if is_rate_limited or is_circuit_open or is_recent_failure:
        raise DataSourceError(
            source="MarketDataProvider",
            message=f"Data for '{symbol}' temporarily unavailable — data provider rate limited or failing. Try again in ~60s.",
        )
    raise SymbolNotFoundError(symbol)


def _make_freshness(
    source: str = "MarketDataProvider",
    cache_hit: bool = False,
    settings: Settings | None = None,
) -> FreshnessMetadata:
    """Build freshness metadata for a response."""
    return FreshnessMetadata(
        source=source,
        timestamp=datetime.now(timezone.utc),
        is_stale=False,
        delay_label="~15s delayed" if source.lower() in ("yahoo_finance", "twelvedata", "twelve data") else "real-time",
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

    async def _fetch_quote(sym: str = None, symbol: str = None) -> dict | None:
        s = sym or symbol
        res = await market_data.get_quote(s)
        if res and res.available and isinstance(res.data, dict):
            d = dict(res.data)
            d["_source"] = res.source or "MarketDataProvider"
            return d
        return None

    data = await cache.get_or_fetch(
        key=cache.quote_key(symbol),
        fetch_func=_fetch_quote,
        ttl=settings.redis_cache_ttl_tick,
        sym=symbol,
    )

    if data is None:
        _raise_data_error(symbol)

    cache_hit = data.pop("_cache_hit", False)
    source_name = data.pop("_source", None)
    data.pop("_cached_at", None)
    data.pop("_validation", None)  # Validation metadata from DataQualityValidator

    source_label = market_data.get_source_label(symbol, source_name)

    return StockQuoteResponse(
        data=StockQuote(**data),
        freshness=_make_freshness(source=source_label, cache_hit=cache_hit),
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

    def _normalize_ohlcv_bar(raw: dict) -> dict | None:
        if not isinstance(raw, dict):
            return None
        dt_val = (
            raw.get("date")
            or raw.get("Datetime")
            or raw.get("datetime")
            or raw.get("time")
            or raw.get("timestamp")
            or raw.get("t")
        )
        if dt_val is None:
            return None
        date_str = dt_val.isoformat() if hasattr(dt_val, "isoformat") else str(dt_val)

        def _val(*keys, fallback=0.0):
            for k in keys:
                v = raw.get(k)
                if v is not None and v != "":
                    try:
                        f = float(v)
                        if not (math.isnan(f) or math.isinf(f)):
                            return f
                    except (ValueError, TypeError):
                        pass
            return fallback

        close = _val("close", "Close", "c")
        if close <= 0:
            return None

        open_p = _val("open", "Open", "o", fallback=close)
        high_p = _val("high", "High", "h", fallback=max(open_p, close))
        low_p = _val("low", "Low", "l", fallback=min(open_p, close))
        vol = int(_val("volume", "Volume", "v", "vol", fallback=0))

        if open_p <= 0 or high_p <= 0 or low_p <= 0:
            return None

        return {
            "date": date_str,
            "open": round(open_p, 2),
            "high": round(high_p, 2),
            "low": round(low_p, 2),
            "close": round(close, 2),
            "volume": max(0, vol),
            "adj_close": None,
        }

    # Try cache first (stored as {"bars": [...], "_source": ...})
    cached = await cache.get(cache_key)
    if cached and "bars" in cached:
        cached.pop("_cache_hit", None)
        cached.pop("_cached_at", None)
        raw_bars = cached["bars"]
        bars = [_normalize_ohlcv_bar(b) for b in raw_bars if _normalize_ohlcv_bar(b)] if isinstance(raw_bars, list) else []
        source_name = cached.get("_source")
        cache_hit = True
    else:
        # Fetch fresh from MarketDataProvider
        result = await market_data.get_history(symbol, period=period, interval=interval)
        if result is None or not result.available or result.data is None:
            _raise_data_error(symbol)

        df = result.data
        source_name = result.source
        bars = []
        if isinstance(df, pd.DataFrame):
            for dt, row in df.iterrows():
                dt_str = dt.isoformat() if hasattr(dt, "isoformat") else str(dt)
                bar_dict = {
                    "date": dt_str,
                    "open": row.get("Open") if "Open" in row else row.get("open"),
                    "high": row.get("High") if "High" in row else row.get("high"),
                    "low": row.get("Low") if "Low" in row else row.get("low"),
                    "close": row.get("Close") if "Close" in row else row.get("close"),
                    "volume": row.get("Volume") if "Volume" in row else row.get("volume"),
                }
                norm = _normalize_ohlcv_bar(bar_dict)
                if norm:
                    bars.append(norm)
        elif isinstance(df, dict) and "bars" in df:
            bars = [_normalize_ohlcv_bar(b) for b in df["bars"] if _normalize_ohlcv_bar(b)]
        elif isinstance(df, list):
            bars = [_normalize_ohlcv_bar(b) for b in df if _normalize_ohlcv_bar(b)]

        # Cache as a dict wrapper so CacheManager can add metadata
        await cache.set(
            cache_key,
            {"bars": bars, "_source": source_name},
            ttl=settings.redis_cache_ttl_indicators,
        )

    source_label = market_data.get_source_label(symbol, source_name)

    valid_bars = []
    for b in bars:
        norm = _normalize_ohlcv_bar(b)
        if norm:
            try:
                valid_bars.append(OHLCVBar(**norm))
            except Exception:
                continue

    return OHLCVResponse(
        symbol=symbol.upper(),
        timeframe=interval,
        data=valid_bars,
        freshness=_make_freshness(source=source_label, cache_hit=cache_hit),
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
        # Fetch fresh via MarketDataProvider
        indices_list = await market_data.get_market_indices()
        if indices_list:
            await cache.set(cache_key, {"indices": indices_list}, ttl=settings.redis_cache_ttl_tick)
        else:
            indices_list = []

    # Parse indices safely — never let one bad index dict crash the whole response
    parsed_indices = []
    for idx in indices_list:
        try:
            parsed_indices.append(MarketIndex(**idx))
        except Exception as e:
            logger.warning("skipping_malformed_index", index_data=str(idx)[:200], error=str(e))

    return MarketOverviewResponse(
        indices=parsed_indices,
        freshness=_make_freshness(source="MarketDataProvider", cache_hit=cache_hit),
    )


@router.get("/search", response_model=SearchResponse)
async def search_stocks(
    q: str = Query(description="Search query (stock name or symbol)"),
):
    """Search for stocks by name or symbol."""
    results = await market_data.search(q)

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

    async def _fetch_company(sym: str = None, symbol: str = None) -> dict | None:
        s = sym or symbol
        res = await market_data.get_company_info(s)
        if res and res.available and isinstance(res.data, dict):
            d = dict(res.data)
            d["_source"] = res.source or "MarketDataProvider"
            return d
        return None

    data = await cache.get_or_fetch(
        key=cache.company_key(symbol),
        fetch_func=_fetch_company,
        ttl=settings.redis_cache_ttl_fundamentals,
        sym=symbol,
    )

    if data is None:
        _raise_data_error(symbol)

    cache_hit = data.pop("_cache_hit", False)
    source_name = data.pop("_source", None)
    data.pop("_cached_at", None)

    source_label = market_data.get_source_label(symbol, source_name)

    return {
        "success": True,
        "data": data,
        "freshness": _make_freshness(source=source_label, cache_hit=cache_hit).model_dump(),
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

    # Try cache first or stampede-protected fetch
    cached = await cache.get(cache.indicators_key(symbol))
    was_cached = cached is not None
    if not was_cached:
        async def _fetch_and_compute(sym: str = None, symbol: str = None) -> dict | None:
            s = sym or symbol
            res = await market_data.get_history(s, period="3mo", interval="1d")
            if not res or not res.available or res.data is None:
                return None
            df = res.data
            bars = []
            if isinstance(df, pd.DataFrame):
                for _, row in df.iterrows():
                    bars.append({
                        "open": float(row["Open"]),
                        "high": float(row["High"]),
                        "low": float(row["Low"]),
                        "close": float(row["Close"]),
                        "volume": int(row["Volume"]),
                    })
            elif isinstance(df, dict) and "bars" in df:
                bars = df["bars"]
            elif isinstance(df, list):
                bars = df
            return compute_indicators(bars)

        indicators = await cache.get_or_fetch(
            key=cache.indicators_key(symbol),
            fetch_func=_fetch_and_compute,
            ttl=settings.redis_cache_ttl_indicators,
            sym=symbol,
        )
    else:
        indicators = cached

    if indicators is None:
        return {
            "success": False,
            "message": "Insufficient data for indicator computation",
        }

    indicators.pop("_cache_hit", None)
    indicators.pop("_cached_at", None)

    source_label = market_data.get_source_label(symbol)

    return {
        "success": True,
        "data": {"symbol": symbol.upper(), **indicators},
        "freshness": _make_freshness(source=source_label, cache_hit=was_cached).model_dump(),
    }


@router.post("/batch-quotes")
async def batch_quotes(
    request: dict,
    redis=Depends(get_redis),
    settings: Settings = Depends(get_settings),
):
    """Batch-fetch quotes for multiple symbols.

    Body: {"symbols": ["RELIANCE.NS", "TCS.NS", ...]}

    Results are cached for 30 seconds.
    """
    symbols = request.get("symbols", [])
    if not symbols:
        return {"success": True, "data": []}

    # Cap at 50 symbols
    symbols = symbols[:50]

    cache = CacheManager(redis)
    cache_key = "batch_quotes:" + ":".join(sorted(s.upper() for s in symbols))

    # Try cache first (30s TTL for dashboard freshness)
    cached = await cache.get(cache_key)
    if cached and "quotes" in cached:
        cached.pop("_cache_hit", None)
        cached.pop("_cached_at", None)
        return {
            "success": True,
            "data": cached["quotes"],
            "count": len(cached["quotes"]),
            "freshness": _make_freshness(source="MarketDataProvider", cache_hit=True).model_dump(),
        }

    # Fetch fresh via market_data
    quotes = await market_data.get_batch_quotes(symbols)

    if quotes:
        await cache.set(cache_key, {"quotes": quotes}, ttl=30)

    return {
        "success": True,
        "data": quotes,
        "count": len(quotes),
        "freshness": _make_freshness(source="MarketDataProvider", cache_hit=False).model_dump(),
    }


@router.get("/health")
async def market_health():
    """Health check for the market data subsystem."""
    health_dict = market_data.get_health()
    all_healthy = any(
        h.get("is_healthy", False) if isinstance(h, dict) else getattr(h, "is_healthy", False)
        for h in health_dict.values()
    ) if health_dict else False

    primary_health = health_dict.get("upstox") or health_dict.get("twelvedata") or {}
    return {
        "adapter": primary_health,
        "providers": health_dict,
        "status": "healthy" if all_healthy else "degraded",
    }
