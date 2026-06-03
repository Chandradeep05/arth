"""
Pydantic schemas for Sentiment and Risk API responses.
"""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field

from app.models.schemas.market import FreshnessMetadata


# ── Sentiment Schemas ──

class SentimentSource(BaseModel):
    """Individual sentiment data point from a source."""
    title: str
    source: str  # e.g., "reuters", "reddit", "moneycontrol"
    url: Optional[str] = None
    sentiment: str  # "bullish", "bearish", "neutral"
    score: float = Field(ge=-1.0, le=1.0, description="Sentiment score: -1 (bearish) to +1 (bullish)")
    published_at: datetime
    credibility_weight: float = Field(
        default=1.0, ge=0.0, le=1.0,
        description="Source credibility weight (WSJ=1.0, Reddit=0.3)"
    )


class SentimentScore(BaseModel):
    """Aggregate sentiment score for a symbol."""
    symbol: str
    overall_score: float = Field(ge=-1.0, le=1.0)
    overall_label: str  # "Bullish", "Bearish", "Neutral"
    bullish_pct: float
    bearish_pct: float
    neutral_pct: float
    total_sources: int
    confidence: float = Field(ge=0, le=100)
    sources: List[SentimentSource] = Field(default_factory=list)
    computed_at: datetime


class SentimentResponse(BaseModel):
    success: bool = True
    data: SentimentScore
    freshness: FreshnessMetadata
    trace_id: str | None = None


# ── Risk Schemas ──

class RiskDimension(BaseModel):
    """Individual risk dimension score."""
    dimension: str  # "volatility", "liquidity", "financial_health", "governance"
    score: float = Field(ge=0, le=100, description="Risk score: 0 (safe) to 100 (risky)")
    label: str  # "Low", "Medium", "High", "Critical"
    factors: List[str] = Field(default_factory=list, description="Contributing factors")


class RiskScore(BaseModel):
    """Composite risk score for a symbol."""
    symbol: str
    composite_score: float = Field(ge=0, le=100)
    composite_label: str  # "Low Risk", "Medium Risk", "High Risk", "Critical Risk"
    dimensions: List[RiskDimension]
    confidence: float = Field(ge=0, le=100)
    computed_at: datetime
    disclaimer: str = Field(
        default="⚠ Risk scores are probabilistic assessments, not guarantees. "
        "Past risk patterns may not predict future outcomes."
    )


class RiskResponse(BaseModel):
    success: bool = True
    data: RiskScore
    freshness: FreshnessMetadata
    trace_id: str | None = None
