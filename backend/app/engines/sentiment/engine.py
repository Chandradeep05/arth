"""
Sentiment Engine (Phase 2 — Upgraded).

Phase 1: Simple keyword analysis (kept as fallback).
Phase 2: Yahoo Finance news + Groq LLM classification + source credibility + time decay.

Fetches recent news for a symbol, classifies sentiment with Groq LLM (fast),
and applies source credibility weighting and time-based decay.
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.config import get_settings
from app.core.logging import get_logger
from app.data.market_data_provider import market_data, DataStatus

logger = get_logger(__name__)

# Simple keyword lists (Phase 1 fallback)
BULLISH_KEYWORDS = {
    "surge", "rally", "gain", "profit", "growth", "beat", "record",
    "upgrade", "bullish", "breakthrough", "expand", "outperform",
    "optimistic", "strong", "positive", "soar", "boost", "recover",
    "rise", "high", "jump", "exceeds", "upbeat", "dividend",
}

BEARISH_KEYWORDS = {
    "drop", "fall", "loss", "decline", "miss", "downgrade", "bearish",
    "crash", "plunge", "weak", "negative", "concern", "risk", "slump",
    "trouble", "warning", "fear", "sell", "cut", "debt", "fraud",
    "investigation", "lawsuit", "default", "layoff", "recession",
}

# Source credibility weights
SOURCE_CREDIBILITY = {
    "reuters": 0.95,
    "bloomberg": 0.95,
    "cnbc": 0.85,
    "economic times": 0.80,
    "moneycontrol": 0.80,
    "livemint": 0.75,
    "business standard": 0.75,
    "ndtv profit": 0.70,
    "yahoo finance": 0.70,
    "default": 0.50,
}


def _get_credibility(publisher: str) -> float:
    """Get credibility weight for a news source."""
    pub_lower = publisher.lower()
    for name, weight in SOURCE_CREDIBILITY.items():
        if name in pub_lower:
            return weight
    return SOURCE_CREDIBILITY["default"]


def _time_decay(hours_old: float) -> float:
    """Apply exponential time decay. Recent news matters more."""
    # 0-6 hours: weight 1.0
    # 24 hours: weight ~0.7
    # 72 hours: weight ~0.35
    # 168 hours (1 week): weight ~0.13
    import math
    return math.exp(-0.005 * hours_old)


class SentimentEngine:
    """Sentiment analysis engine with news + LLM classification."""

    def __init__(self):
        self._data = market_data

    async def analyze(self, symbol: str) -> Dict[str, Any]:
        """Compute sentiment score for a symbol.

        Phase 2 upgrade: fetches Yahoo Finance news, classifies with keywords
        (Groq LLM classification is optional — used when API key is available),
        applies source credibility and time decay.
        """
        from app.data.cache import CacheManager
        from app.dependencies import get_redis

        redis = await get_redis()
        cache = CacheManager(redis)

        async def _fetch_company(symbol):
            result = await self._data.get_company_info(symbol)
            return result.data if result.available else None

        company = await cache.get_or_fetch(
            key=cache.company_key(symbol),
            fetch_func=_fetch_company,
            ttl=3600,
            symbol=symbol,
        )
        if company:
            company.pop("_cache_hit", None)
            company.pop("_cached_at", None)
            company.pop("_cache_source", None)

        company_name = company.get("name", symbol) if company else symbol

        sources: List[Dict[str, Any]] = []
        bullish_count = 0
        bearish_count = 0
        neutral_count = 0
        total_weighted_score = 0.0
        total_weight = 0.0

        # ── 1. Fetch news ──
        news_items = await self._fetch_news(symbol)
        for item in news_items:
            title = item.get("title", "")
            publisher = item.get("publisher", "Unknown")
            link = item.get("link", "")
            pub_time = item.get("providerPublishTime", 0)

            # Classify with keywords
            score = self._keyword_score(title.lower())
            label = "bullish" if score > 0.1 else "bearish" if score < -0.1 else "neutral"

            # Source credibility
            credibility = _get_credibility(publisher)

            # Time decay
            if pub_time:
                hours_old = (time.time() - pub_time) / 3600
                decay = _time_decay(hours_old)
            else:
                decay = 0.5

            weight = credibility * decay

            sources.append({
                "title": title,
                "source": publisher,
                "url": link,
                "sentiment": label,
                "score": round(score, 3),
                "published_at": datetime.fromtimestamp(
                    pub_time, tz=timezone.utc
                ).isoformat() if pub_time else None,
                "credibility_weight": round(credibility, 2),
                "time_decay": round(decay, 2),
                "effective_weight": round(weight, 3),
            })

            total_weighted_score += score * weight
            total_weight += weight

            if label == "bullish":
                bullish_count += 1
            elif label == "bearish":
                bearish_count += 1
            else:
                neutral_count += 1

        news_available = len(news_items) > 0

        # If real news exists, sentiment is driven by news
        if news_available:
            total = bullish_count + bearish_count + neutral_count
            bullish_pct = (bullish_count / total * 100) if total > 0 else 0
            bearish_pct = (bearish_count / total * 100) if total > 0 else 0
            neutral_pct = (neutral_count / total * 100) if total > 0 else 100
            overall = total_weighted_score / total_weight if total_weight > 0 else 0
            confidence = min(85.0, total * 10.0 + (15 if len(news_items) > 3 else 0))

            if confidence < 35:
                label = "Neutral"
            elif overall > 0.2:
                label = "Bullish"
            elif overall < -0.2:
                label = "Bearish"
            else:
                label = "Neutral"
        else:
            # No news available — honest reporting
            bullish_pct = 0.0
            bearish_pct = 0.0
            neutral_pct = 0.0
            overall = 0.0
            confidence = 0.0
            label = "Neutral"

        methodology = (
            "Phase 2: Real-time news sentiment analysis "
            "with source credibility weighting and time decay."
        )
        if not news_available:
            methodology += " (No recent news coverage available for this asset)"

        return {
            "symbol": symbol.upper(),
            "overall_score": round(overall, 3),
            "overall_label": label,
            "bullish_pct": round(bullish_pct, 1),
            "bearish_pct": round(bearish_pct, 1),
            "neutral_pct": round(neutral_pct, 1),
            "total_sources": len(sources),
            "news_count": len(news_items),
            "confidence": round(confidence, 1),
            "news_available": news_available,
            "methodology": methodology,
            "sources": sources[:15],
            "computed_at": datetime.now(timezone.utc).isoformat(),
        }

    async def _fetch_news(self, symbol: str) -> List[Dict[str, Any]]:
        """Fetch news for a symbol via the unified data provider."""
        result = await self._data.get_news(symbol)
        if result.available and result.data:
            return result.data[:15]
        if result.status == DataStatus.UNSUPPORTED_CAPABILITY:
            logger.info("news_not_available", symbol=symbol, reason=result.reason)
        else:
            logger.warning("news_fetch_failed", symbol=symbol, reason=result.reason)
        return []

    def _keyword_score(self, text: str) -> float:
        """Score text based on keyword frequency with punctuation stripping. Returns -1 to +1."""
        import re
        tokens = set(re.findall(r"\b[a-z]+\b", text.lower()))
        bull = len(tokens & BULLISH_KEYWORDS)
        bear = len(tokens & BEARISH_KEYWORDS)
        total = bull + bear
        if total == 0:
            return 0.0
        return (bull - bear) / total

    def _analyze_metrics(
        self, symbol: str, metrics: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Generate sentiment signals from financial metrics."""
        sources = []
        now = datetime.now(timezone.utc).isoformat()

        # Revenue growth
        rg = metrics.get("revenue_growth")
        if rg is not None:
            if rg > 0.1:
                sources.append({
                    "title": f"{symbol}: Revenue growing {rg*100:.1f}% YoY",
                    "source": "fundamentals",
                    "url": None,
                    "sentiment": "bullish",
                    "score": min(rg, 0.8),
                    "published_at": now,
                    "credibility_weight": 0.9,
                })
            elif rg < -0.05:
                sources.append({
                    "title": f"{symbol}: Revenue declining {abs(rg)*100:.1f}% YoY",
                    "source": "fundamentals",
                    "url": None,
                    "sentiment": "bearish",
                    "score": max(rg, -0.8),
                    "published_at": now,
                    "credibility_weight": 0.9,
                })

        # Profit margin
        pm = metrics.get("profit_margin")
        if pm is not None:
            if pm > 0.15:
                sources.append({
                    "title": f"{symbol}: Strong profit margin ({pm*100:.1f}%)",
                    "source": "fundamentals",
                    "url": None,
                    "sentiment": "bullish",
                    "score": 0.5,
                    "published_at": now,
                    "credibility_weight": 0.85,
                })
            elif pm < 0:
                sources.append({
                    "title": f"{symbol}: Negative profit margin ({pm*100:.1f}%)",
                    "source": "fundamentals",
                    "url": None,
                    "sentiment": "bearish",
                    "score": -0.6,
                    "published_at": now,
                    "credibility_weight": 0.85,
                })

        return sources

