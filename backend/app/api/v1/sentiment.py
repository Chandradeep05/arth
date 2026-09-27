"""
Sentiment API endpoints.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends

from app.config import Settings, get_settings
from app.core.logging import get_logger
from app.data.cache import CacheManager
from app.dependencies import get_redis
from app.engines.sentiment.engine import SentimentEngine
from app.models.schemas.market import FreshnessMetadata

logger = get_logger(__name__)
router = APIRouter(prefix="/sentiment", tags=["sentiment"])


@router.get("/{symbol}")
async def get_sentiment(
    symbol: str,
    redis=Depends(get_redis),
    settings: Settings = Depends(get_settings),
):
    """Get sentiment analysis for a stock symbol."""
    cache = CacheManager(redis)

    # Try cache first or stampede-protected fetch
    cached = await cache.get(cache.sentiment_key(symbol))
    was_cached = cached is not None
    if not was_cached:
        engine = SentimentEngine()
        result = await cache.get_or_fetch(
            key=cache.sentiment_key(symbol),
            fetch_func=engine.analyze,
            ttl=300,
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
