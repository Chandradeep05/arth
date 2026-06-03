"""
Pydantic schemas for market data API requests and responses.

These define the exact shape of data sent to and from the API.
All responses include freshness metadata for the frontend to display
staleness indicators.
"""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


# ── Response Metadata ──

class FreshnessMetadata(BaseModel):
    """Attached to every data response — drives the DataFreshness UI component."""
    source: str = Field(description="Data source name (e.g., 'yahoo_finance')")
    timestamp: datetime = Field(description="When this data was fetched")
    is_stale: bool = Field(default=False, description="True if data exceeds freshness threshold")
    delay_label: str = Field(default="~15s delayed", description="Human-readable delay description")
    cache_hit: bool = Field(default=False, description="Whether this was served from cache")


class APIResponse(BaseModel):
    """Standard API response wrapper."""
    success: bool = True
    data: dict | list | None = None
    freshness: FreshnessMetadata | None = None
    trace_id: str | None = None


# ── Stock Quote ──

class StockQuote(BaseModel):
    """Current stock price and basic info."""
    symbol: str
    name: str
    price: float
    change: float
    change_percent: float
    volume: int
    high: float
    low: float
    open: float
    previous_close: float
    market_cap: Optional[float] = None
    pe_ratio: Optional[float] = None
    timestamp: datetime
    exchange: str
    market: str  # "india" or "us"
    currency: str = "INR"


class StockQuoteResponse(BaseModel):
    """Stock quote API response."""
    success: bool = True
    data: StockQuote
    freshness: FreshnessMetadata
    trace_id: str | None = None


# ── OHLCV Data ──

class OHLCVBar(BaseModel):
    """Single OHLCV candlestick bar."""
    date: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int
    adj_close: Optional[float] = None


class OHLCVResponse(BaseModel):
    """Historical OHLCV data response."""
    success: bool = True
    symbol: str
    timeframe: str = "1d"
    data: List[OHLCVBar]
    freshness: FreshnessMetadata
    trace_id: str | None = None


# ── Technical Indicators ──

class MACDData(BaseModel):
    value: float
    signal: float
    histogram: float


class BollingerBands(BaseModel):
    upper: float
    middle: float
    lower: float


class TechnicalIndicators(BaseModel):
    """Computed technical indicators for a symbol."""
    symbol: str
    timestamp: datetime
    rsi_14: Optional[float] = None
    macd: Optional[MACDData] = None
    bollinger_bands: Optional[BollingerBands] = None
    vwap: Optional[float] = None
    sma_20: Optional[float] = None
    sma_50: Optional[float] = None

    # Interpretive signals
    rsi_signal: Optional[str] = None  # "oversold", "neutral", "overbought"
    macd_signal_type: Optional[str] = None  # "bullish_crossover", "bearish_crossover", "neutral"
    bb_position: Optional[str] = None  # "above_upper", "middle", "below_lower"


class TechnicalIndicatorsResponse(BaseModel):
    success: bool = True
    data: TechnicalIndicators
    freshness: FreshnessMetadata
    trace_id: str | None = None


# ── Market Index ──

class MarketIndex(BaseModel):
    """Major market index data."""
    symbol: str
    name: str
    value: float
    change: float
    change_percent: float
    timestamp: datetime


class MarketOverviewResponse(BaseModel):
    """Market overview with major indices."""
    success: bool = True
    indices: List[MarketIndex]
    freshness: FreshnessMetadata
    trace_id: str | None = None


# ── Sector Performance ──

class SectorPerformance(BaseModel):
    """Sector-level performance data."""
    sector: str
    change_percent: float
    top_gainer: Optional[str] = None
    top_loser: Optional[str] = None
    volume: Optional[int] = None


# ── Search ──

class SearchResult(BaseModel):
    """Stock search result."""
    symbol: str
    name: str
    exchange: str
    market: str
    sector: Optional[str] = None


class SearchResponse(BaseModel):
    success: bool = True
    query: str
    results: List[SearchResult]
    trace_id: str | None = None


# ── Top Movers ──

class StockMover(BaseModel):
    """Stock in top gainers/losers list."""
    symbol: str
    name: str
    price: float
    change: float
    change_percent: float
    volume: int


class TopMoversResponse(BaseModel):
    success: bool = True
    gainers: List[StockMover]
    losers: List[StockMover]
    freshness: FreshnessMetadata
    trace_id: str | None = None
