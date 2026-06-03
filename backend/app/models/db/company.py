"""
Company model — represents a stock/equity.

Stores symbol, name, exchange, sector, and basic metadata.
Supports both Indian (NSE/BSE) and US (NYSE/NASDAQ) markets.
"""

from __future__ import annotations

from sqlalchemy import String, Float, BigInteger, Boolean, Index
from sqlalchemy.orm import Mapped, mapped_column

from app.models.db.base import Base, TimestampMixin


class Company(Base, TimestampMixin):
    __tablename__ = "companies"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    # Symbol with exchange suffix (e.g., "RELIANCE.NS", "AAPL")
    symbol: Mapped[str] = mapped_column(String(32), unique=True, nullable=False, index=True)

    # Clean name (e.g., "Reliance Industries Limited")
    name: Mapped[str] = mapped_column(String(256), nullable=False)

    # Exchange: NSE, BSE, NYSE, NASDAQ
    exchange: Mapped[str] = mapped_column(String(16), nullable=False, index=True)

    # Market: india, us
    market: Mapped[str] = mapped_column(String(16), nullable=False, default="india")

    # Sector classification
    sector: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    industry: Mapped[str | None] = mapped_column(String(128), nullable=True)

    # Basic fundamentals (cached, updated daily)
    market_cap: Mapped[float | None] = mapped_column(Float, nullable=True)
    pe_ratio: Mapped[float | None] = mapped_column(Float, nullable=True)
    eps: Mapped[float | None] = mapped_column(Float, nullable=True)
    dividend_yield: Mapped[float | None] = mapped_column(Float, nullable=True)
    book_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    debt_to_equity: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Volume metrics
    avg_volume: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    # Status
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Composite indexes for common queries
    __table_args__ = (
        Index("ix_companies_market_sector", "market", "sector"),
        Index("ix_companies_exchange_active", "exchange", "is_active"),
    )

    def __repr__(self) -> str:
        return f"<Company(symbol={self.symbol}, name={self.name}, exchange={self.exchange})>"
