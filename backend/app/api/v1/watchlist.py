"""
Watchlist Batch API endpoint.

Provides a single batch endpoint that fetches quotes, risk scores,
and sentiment labels for multiple symbols in parallel using asyncio.gather.

Max 20 symbols per request to keep response times reasonable.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Dict, List

from fastapi import APIRouter, Depends

from app.config import Settings, get_settings
from app.core.logging import get_logger
from app.data.adapters.yahoo import yahoo_adapter
from app.data.cache import CacheManager
from app.dependencies import get_redis
from app.engines.risk.engine import RiskEngine
from app.engines.sentiment.engine import SentimentEngine
from app.models.schemas.market import FreshnessMetadata
from app.models.schemas.watchlist import WatchlistBatchRequest

logger = get_logger(__name__)
router = APIRouter(prefix="/watchlist", tags=["watchlist"])

# Reusable singleton instances (stateless)
_yahoo = yahoo_adapter
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
    async def _get_quote() -> Dict[str, Any] | None:
        try:
            data = await cache.get_or_fetch(
                key=CacheManager.quote_key(symbol),
                fetch_func=_yahoo.get_quote,
                ttl=settings.redis_cache_ttl_tick,
                symbol=symbol,
            )
            if data:
                data.pop("_cache_hit", None)
                data.pop("_cached_at", None)
                data.pop("_validation", None)
            return data
        except Exception as e:
            logger.warning("watchlist_quote_failed", symbol=symbol, error=str(e))
            return None

    # --- Risk ---
    async def _get_risk() -> Dict[str, Any] | None:
        try:
            cached = await cache.get(CacheManager.risk_key(symbol))
            if cached:
                cached.pop("_cache_hit", None)
                cached.pop("_cached_at", None)
                return cached
            result = await _risk_engine.compute_risk(symbol)
            await cache.set(CacheManager.risk_key(symbol), result, ttl=600)
            return result
        except Exception as e:
            logger.warning("watchlist_risk_failed", symbol=symbol, error=str(e))
            return None

    # --- Sentiment ---
    async def _get_sentiment() -> Dict[str, Any] | None:
        try:
            cached = await cache.get(CacheManager.sentiment_key(symbol))
            if cached:
                cached.pop("_cache_hit", None)
                cached.pop("_cached_at", None)
                return cached
            result = await _sentiment_engine.analyze(symbol)
            await cache.set(CacheManager.sentiment_key(symbol), result, ttl=300)
            return result
        except Exception as e:
            logger.warning("watchlist_sentiment_failed", symbol=symbol, error=str(e))
            return None

    # Run all three concurrently
    quote, risk, sentiment = await asyncio.gather(
        _get_quote(),
        _get_risk(),
        _get_sentiment(),
    )

    # Build combined summary
    return {
        "symbol": symbol.upper(),
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
    redis=Depends(get_redis),
    settings: Settings = Depends(get_settings),
):
    """Batch fetch quotes, risk scores, and sentiment for watchlist symbols.

    Accepts up to 20 symbols.  For each symbol the endpoint fetches
    quote data, risk score, and sentiment label **in parallel** using
    ``asyncio.gather``, returning a consolidated list.

    Individual symbol failures are handled gracefully — the overall
    request still succeeds with ``data_available`` flags per symbol.
    """
    cache = CacheManager(redis)

    logger.info(
        "watchlist_batch_request",
        symbols=request.symbols,
        count=len(request.symbols),
    )

    # Fetch all symbols in parallel
    tasks = [
        _fetch_symbol_data(sym, cache, settings)
        for sym in request.symbols
    ]
    results: List[Dict[str, Any]] = await asyncio.gather(*tasks)

    return {
        "success": True,
        "data": results,
        "count": len(results),
        "freshness": FreshnessMetadata(
            source="yahoo_finance",
            timestamp=datetime.now(timezone.utc),
            is_stale=False,
            delay_label="~15s delayed",
            cache_hit=False,
        ).model_dump(),
    }
