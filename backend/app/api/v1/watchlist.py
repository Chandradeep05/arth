"""
Watchlist Batch API endpoint.

Provides a single batch endpoint that fetches quotes, risk scores,
and sentiment labels for multiple symbols.

Max 20 symbols per request to keep response times reasonable.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Dict, List

from fastapi import APIRouter, Depends

from app.config import Settings, get_settings
from app.core.auth import UserContext, require_active_user
from app.core.logging import get_logger
from app.data.cache import CacheManager
from app.data.market_data_provider import market_data
from app.dependencies import get_redis
from app.engines.risk.engine import RiskEngine
from app.engines.sentiment.engine import SentimentEngine
from app.models.schemas.market import FreshnessMetadata
from app.models.schemas.watchlist import WatchlistBatchRequest

logger = get_logger(__name__)
router = APIRouter(prefix="/watchlist", tags=["watchlist"])

# Reusable singleton instances (stateless)
_risk_engine = RiskEngine()
_sentiment_engine = SentimentEngine()


async def _fetch_symbol_data(
    symbol: str,
    cache: CacheManager,
    settings: Settings,
) -> Dict[str, Any]:
    """Fetch quote, risk score, and sentiment for a single symbol.

    Runs all three fetches concurrently and assembles a combined result.
    Graceful degradation: if any fetch fails, its value is set to None.
    """
    # --- Quote ---
    async def _get_quote():
        try:
            async def _fetch(sym: str = None, symbol: str = None):
                s = sym or symbol
                res = await market_data.get_quote(s)
                if res and res.available:
                    data = dict(res.data) if res.data else {}
                    data["_source"] = res.source or "MarketDataProvider"
                    data["_cached"] = getattr(res, "cached", False)
                    return data
                return None

            data = await cache.get_or_fetch(
                key=CacheManager.quote_key(symbol),
                fetch_func=_fetch,
                ttl=settings.redis_cache_ttl_tick,
                sym=symbol,
            )
            if data:
                src = data.pop("_source", "MarketDataProvider")
                was_cached = data.pop("_cache_hit", False) or data.pop("_cached", False)
                data.pop("_cached_at", None)
                data.pop("_validation", None)
                return data, src, was_cached
            return None, "MarketDataProvider", False
        except Exception as e:
            logger.warning("watchlist_quote_failed", symbol=symbol, error=str(e))
            return None, "MarketDataProvider", False

    # --- Risk ---
    async def _get_risk() -> Dict[str, Any] | None:
        try:
            data = await cache.get_or_fetch(
                key=CacheManager.risk_key(symbol),
                fetch_func=_risk_engine.compute_risk,
                ttl=600,
                symbol=symbol,
            )
            if data:
                data.pop("_cache_hit", None)
                data.pop("_cached_at", None)
            return data
        except Exception as e:
            logger.warning("watchlist_risk_failed", symbol=symbol, error=str(e))
            return None

    # --- Sentiment ---
    async def _get_sentiment() -> Dict[str, Any] | None:
        try:
            data = await cache.get_or_fetch(
                key=CacheManager.sentiment_key(symbol),
                fetch_func=_sentiment_engine.analyze,
                ttl=300,
                symbol=symbol,
            )
            if data:
                data.pop("_cache_hit", None)
                data.pop("_cached_at", None)
            return data
        except Exception as e:
            logger.warning("watchlist_sentiment_failed", symbol=symbol, error=str(e))
            return None

    # Run all three concurrently
    quote_res, risk, sentiment = await asyncio.gather(
        _get_quote(),
        _get_risk(),
        _get_sentiment(),
    )

    quote, quote_source, quote_cached = quote_res

    # Build combined summary
    return {
        "symbol": symbol.upper(),
        "source": quote_source,
        "quote_cached": quote_cached,
        "quote": {
            "price": quote.get("price") if quote else None,
            "change": quote.get("change") if quote else None,
            "change_percent": quote.get("change_percent") if quote else None,
            "volume": quote.get("volume") if quote else None,
            "name": quote.get("name") if quote else None,
            "market_cap": quote.get("market_cap") if quote else None,
        } if quote else None,
        "risk_score": risk.get("composite_score") if risk else None,
        "risk_label": risk.get("composite_label") if risk else None,
        "sentiment_score": sentiment.get("overall_score") if sentiment else None,
        "sentiment_label": sentiment.get("overall_label") if sentiment else None,
        "data_available": {
            "quote": quote is not None,
            "risk": risk is not None,
            "sentiment": sentiment is not None,
        },
    }


@router.post("/batch")
async def batch_fetch(
    request: WatchlistBatchRequest,
    user: UserContext = Depends(require_active_user),
    redis=Depends(get_redis),
    settings: Settings = Depends(get_settings),
):
    """Batch fetch quotes, risk scores, and sentiment for watchlist symbols.

    Accepts up to 20 symbols. For each symbol the endpoint fetches
    quote data, risk score, and sentiment label. Circuit breakers and
    fallbacks are handled by MarketDataProvider.

    Individual symbol failures are handled gracefully — the overall
    request still succeeds with ``data_available`` flags per symbol.
    """
    cache = CacheManager(redis)

    logger.info(
        "watchlist_batch_request",
        user_id=str(user.user_id),
        symbols=request.symbols,
        count=len(request.symbols),
    )

    results: List[Dict[str, Any]] = []
    for sym in request.symbols:
        result = await _fetch_symbol_data(sym, cache, settings)
        results.append(result)

    sources = [
        r.get("source") for r in results
        if r.get("source") and r.get("source") not in ("unavailable", "error", "MarketDataProvider")
    ]
    primary_source = ", ".join(sorted(set(sources))) if sources else "MarketDataProvider"
    any_cached = any(r.get("quote_cached", False) for r in results) if results else False

    return {
        "success": True,
        "data": results,
        "count": len(results),
        "freshness": FreshnessMetadata(
            source=primary_source,
            timestamp=datetime.now(timezone.utc),
            is_stale=False,
            delay_label="Multi-provider real-time & intraday",
            cache_hit=any_cached,
        ).model_dump(),
    }
