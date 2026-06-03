"""
Price model — OHLCV data stored in TimescaleDB hypertable.

This is the core time-series table. TimescaleDB automatically partitions
by time for efficient range queries on historical data.

Note: The hypertable creation is handled in the Alembic migration,
not in the model definition (SQLAlchemy doesn't natively support
TimescaleDB's CREATE_HYPERTABLE).
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    String, Float, BigInteger, DateTime, Index, UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.db.base import Base


class Price(Base):
    """OHLCV price data — TimescaleDB hypertable."""

    __tablename__ = "prices"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    # Stock symbol (e.g., "RELIANCE.NS", "AAPL")
    symbol: Mapped[str] = mapped_column(String(32), nullable=False, index=True)

    # Timestamp of the price data point
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )

    # OHLCV data
    open: Mapped[float] = mapped_column(Float, nullable=False)
    high: Mapped[float] = mapped_column(Float, nullable=False)
    low: Mapped[float] = mapped_column(Float, nullable=False)
    close: Mapped[float] = mapped_column(Float, nullable=False)
    volume: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)

    # Adjusted close (for splits/dividends)
    adj_close: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Timeframe: 1m, 5m, 15m, 1h, 1d, 1wk
    timeframe: Mapped[str] = mapped_column(String(8), nullable=False, default="1d")

    # Data source for auditability
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="yahoo")

    __table_args__ = (
        UniqueConstraint("symbol", "timestamp", "timeframe", name="uq_price_symbol_time_tf"),
        Index("ix_prices_symbol_timestamp", "symbol", "timestamp"),
        Index("ix_prices_symbol_timeframe", "symbol", "timeframe"),
    )

    def __repr__(self) -> str:
        return f"<Price(symbol={self.symbol}, time={self.timestamp}, close={self.close})>"


class Indicator(Base):
    """Computed technical indicators per symbol/timeframe."""

    __tablename__ = "indicators"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    symbol: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )

    # RSI (14-period)
    rsi_14: Mapped[float | None] = mapped_column(Float, nullable=True)

    # MACD (12, 26, 9)
    macd_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    macd_signal: Mapped[float | None] = mapped_column(Float, nullable=True)
    macd_histogram: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Bollinger Bands (20, 2)
    bb_upper: Mapped[float | None] = mapped_column(Float, nullable=True)
    bb_middle: Mapped[float | None] = mapped_column(Float, nullable=True)
    bb_lower: Mapped[float | None] = mapped_column(Float, nullable=True)

    # VWAP
    vwap: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Simple & Exponential Moving Averages
    sma_20: Mapped[float | None] = mapped_column(Float, nullable=True)
    sma_50: Mapped[float | None] = mapped_column(Float, nullable=True)
    ema_12: Mapped[float | None] = mapped_column(Float, nullable=True)
    ema_26: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Timeframe
    timeframe: Mapped[str] = mapped_column(String(8), nullable=False, default="1d")

    __table_args__ = (
        UniqueConstraint("symbol", "timestamp", "timeframe", name="uq_indicator_symbol_time_tf"),
        Index("ix_indicators_symbol_timestamp", "symbol", "timestamp"),
    )

    def __repr__(self) -> str:
        return f"<Indicator(symbol={self.symbol}, time={self.timestamp}, rsi={self.rsi_14})>"
