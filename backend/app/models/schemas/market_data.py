"""
ARTH — Typed Data Contracts for Market Data

Canonical schemas that all data adapters normalize into before returning data.
Prevents adapter-specific field names from leaking past the data boundary.
Fixes the cache serialization bug (DataFrames into dict cache) by ensuring
all cached values are Pydantic model instances with proper serialization.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


class DataProvenance(BaseModel):
    """Tracks the source and freshness of every data point."""
    source: str                          # adapter name: "twelvedata", "finnhub", "fmp", "nse"
    source_label: str                    # human-readable: "Twelve Data", "Finnhub"
    fetched_at: datetime                 # when the data was fetched from the provider
    freshness_seconds: int = 0           # age of data in seconds
    freshness_label: str = "just now"    # human-readable age: "6 minutes ago"
    confidence: str = "high"             # "high", "medium", "low"
    is_stale: bool = False               # True if data exceeds freshness threshold
    cache_hit: bool = False              # True if served from cache
    degraded: bool = False               # True if served from a fallback provider
    degradation_reason: str | None = None  # e.g. "TwelveData rate-limited, served from Finnhub"


class NormalizedQuote(BaseModel):
    """Canonical quote schema — all adapters normalize into this."""
    symbol: str
    name: str = ""
    price: float
    change: float = 0.0
    change_percent: float = 0.0
    open: float | None = None
    high: float | None = None
    low: float | None = None
    previous_close: float | None = None
    volume: int | None = None
    market_cap: float | None = None
    pe_ratio: float | None = None
    week_52_high: float | None = None
    week_52_low: float | None = None
    exchange: str = ""
    currency: str = "USD"
    market_state: str = ""   # "regular", "pre", "post", "closed"
    provenance: DataProvenance


class OHLCVBar(BaseModel):
    """Single OHLCV bar (one candle)."""
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int = 0


class NormalizedOHLCV(BaseModel):
    """Canonical OHLCV response — historical price data."""
    symbol: str
    interval: str = "1d"     # "1m", "5m", "15m", "1h", "1d", "1wk", "1mo"
    bars: list[OHLCVBar] = []
    provenance: DataProvenance


class NormalizedCompanyInfo(BaseModel):
    """Canonical company information schema."""
    symbol: str
    name: str = ""
    description: str = ""
    sector: str = ""
    industry: str = ""
    country: str = ""
    exchange: str = ""
    currency: str = "USD"
    market_cap: float | None = None
    employees: int | None = None
    website: str = ""
    logo_url: str = ""
    provenance: DataProvenance


class NormalizedSearchResult(BaseModel):
    """Single search result entry."""
    symbol: str
    name: str = ""
    exchange: str = ""
    type: str = ""           # "equity", "etf", "index"
    currency: str = ""


class SearchResults(BaseModel):
    """Canonical search results response."""
    query: str
    results: list[NormalizedSearchResult] = []
    provenance: DataProvenance


class NormalizedIndicators(BaseModel):
    """Canonical technical indicators response."""
    symbol: str
    rsi_14: float | None = None
    macd: float | None = None
    macd_signal: float | None = None
    macd_histogram: float | None = None
    bb_upper: float | None = None
    bb_middle: float | None = None
    bb_lower: float | None = None
    sma_20: float | None = None
    sma_50: float | None = None
    sma_200: float | None = None
    ema_12: float | None = None
    ema_26: float | None = None
    vwap: float | None = None
    atr_14: float | None = None
    obv: float | None = None
    provenance: DataProvenance


class ConfidenceScore(BaseModel):
    """
    Unified confidence scoring — attached to predictions, research, risk, etc.
    
    NOTE: Prediction-specific calibration (comparing confidence to actual hit rate)
    is deferred until the outcome tracker has collected enough real data.
    This initial version only covers data-completeness-based confidence.
    """
    score: float = Field(ge=0.0, le=1.0)   # 0.0 - 1.0
    band: str                               # "high", "medium", "low"
    reasons: list[str] = []                 # ["High volatility regime", "Small training window"]
    factors_positive: list[str] = []
    factors_negative: list[str] = []

