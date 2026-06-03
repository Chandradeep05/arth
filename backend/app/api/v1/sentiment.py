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

    # Try cache first
    cached = await cache.get(cache.sentiment_key(symbol))
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

    # Compute fresh sentiment
    engine = SentimentEngine()
    result = await engine.analyze(symbol)

    # Cache for 5 minutes
    await cache.set(cache.sentiment_key(symbol), result, ttl=300)

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
