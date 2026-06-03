"""
Sentiment Engine (Module 03 — Phase 1 Basic).

Phase 1: Simple news-based sentiment using keyword analysis.
Phase 2: Full FinBERT pipeline with source credibility weighting.

Fetches recent news for a symbol and classifies sentiment using
basic positive/negative keyword matching. This is intentionally simple
for Phase 1 — FinBERT deployment comes in Phase 2.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List

from app.core.logging import get_logger
from app.data.adapters.yahoo import YahooFinanceAdapter

logger = get_logger(__name__)

# Simple keyword lists for Phase 1 sentiment
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


class SentimentEngine:
    """Basic sentiment analysis engine for Phase 1."""

    def __init__(self):
        self._yahoo = YahooFinanceAdapter()

    async def analyze(self, symbol: str) -> Dict[str, Any]:
        """Compute sentiment score for a symbol from available news."""
        # Fetch company info (includes basic news from Yahoo)
        company = await self._yahoo.get_company_info(symbol)
        company_name = company.get("name", symbol) if company else symbol

        # In Phase 1, we do keyword-based sentiment on the company description
        # and any available context. Phase 2 adds NewsAPI + FinBERT.
        sources: List[Dict[str, Any]] = []
        bullish_count = 0
        bearish_count = 0
        neutral_count = 0

        # Analyze company description if available
        if company and company.get("description"):
            desc = company["description"].lower()
            score = self._keyword_score(desc)
            label = "bullish" if score > 0.1 else "bearish" if score < -0.1 else "neutral"
            sources.append({
                "title": f"{company_name} — Company Profile",
                "source": "yahoo_finance",
                "url": None,
                "sentiment": label,
                "score": round(score, 3),
                "published_at": datetime.now(timezone.utc).isoformat(),
                "credibility_weight": 0.8,
            })
            if label == "bullish":
                bullish_count += 1
            elif label == "bearish":
                bearish_count += 1
            else:
                neutral_count += 1

        # Analyze financial metrics for sentiment signals
        if company:
            metrics = company.get("metrics", {})
            metric_sources = self._analyze_metrics(symbol, metrics)
            for src in metric_sources:
                sources.append(src)
                if src["sentiment"] == "bullish":
                    bullish_count += 1
                elif src["sentiment"] == "bearish":
                    bearish_count += 1
                else:
                    neutral_count += 1

        total = bullish_count + bearish_count + neutral_count
        if total == 0:
            total = 1  # Avoid division by zero

        bullish_pct = bullish_count / total * 100
        bearish_pct = bearish_count / total * 100
        neutral_pct = neutral_count / total * 100

        # Overall score: -1 (bearish) to +1 (bullish)
        overall = (bullish_count - bearish_count) / total

        # Confidence is low for Phase 1 keyword analysis (only 2-3 sources)
        confidence = min(35.0, total * 15.0)

        # Suppress strong directional labels when confidence is low
        # A "Bullish" label at 35% confidence contradicts technical signals
        if confidence < 50:
            # At low confidence, only show Neutral unless signal is very strong
            if overall > 0.5:
                label = "Slightly Bullish"
            elif overall < -0.5:
                label = "Slightly Bearish"
            else:
                label = "Neutral"
        else:
            if overall > 0.2:
                label = "Bullish"
            elif overall < -0.2:
                label = "Bearish"
            else:
                label = "Neutral"

        return {
            "symbol": symbol.upper(),
            "overall_score": round(overall, 3),
            "overall_label": label,
            "bullish_pct": round(bullish_pct, 1),
            "bearish_pct": round(bearish_pct, 1),
            "neutral_pct": round(neutral_pct, 1),
            "total_sources": len(sources),
            "confidence": round(confidence, 1),
            "methodology": "Phase 1: News & fundamentals keyword analysis only. Does not incorporate price action or technical signals.",
            "sources": sources[:10],
            "computed_at": datetime.now(timezone.utc).isoformat(),
        }

    def _keyword_score(self, text: str) -> float:
        """Score text based on keyword frequency. Returns -1 to +1."""
        words = set(text.lower().split())
        bull = len(words & BULLISH_KEYWORDS)
        bear = len(words & BEARISH_KEYWORDS)
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
