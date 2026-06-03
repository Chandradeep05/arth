"""
Yahoo Finance data adapter — Primary (and only) data source for Phase 1.

Uses the `yfinance` library to fetch:
- Real-time quotes (delayed ~15s)
- Historical OHLCV data
- Company info and fundamentals
- Stock search (via ticker validation)

Important notes:
- Yahoo Finance data is delayed ~15s during market hours
- No official API — yfinance scrapes Yahoo's endpoints
- Rate limits are undocumented; we handle failures gracefully
- Indian stocks use .NS (NSE) or .BO (BSE) suffix
- US stocks use plain symbols (AAPL, MSFT)
"""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import yfinance as yf

from app.core.logging import get_logger
from app.data.adapters.base import BaseDataAdapter

logger = get_logger(__name__)

# Thread pool for yfinance (it's synchronous)
_executor = ThreadPoolExecutor(max_workers=4)


class YahooFinanceAdapter(BaseDataAdapter):
    """Yahoo Finance data adapter using yfinance library."""

    adapter_name = "yahoo_finance"

    def _detect_market(self, symbol: str) -> tuple[str, str, str]:
        """Detect market and exchange from symbol suffix."""
        if symbol.upper().endswith(".NS"):
            return "india", "NSE", "INR"
        elif symbol.upper().endswith(".BO"):
            return "india", "BSE", "INR"
        else:
            return "us", "NYSE/NASDAQ", "USD"

    def _run_sync(self, func, *args, **kwargs):
        """Run a synchronous yfinance call in a thread pool."""
        loop = asyncio.get_running_loop()
        return loop.run_in_executor(_executor, lambda: func(*args, **kwargs))

    async def get_quote(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Get current stock quote with basic info."""

        async def _fetch():
            ticker = yf.Ticker(symbol)
            # Capture ticker in default arg to avoid closure bug
            info = await self._run_sync(lambda t=ticker: t.info)

            if not info or "regularMarketPrice" not in info:
                # Try fast_info as fallback
                fast = await self._run_sync(lambda t=ticker: t.fast_info)
                if not fast:
                    return None

                market, exchange, currency = self._detect_market(symbol)
                return {
                    "symbol": symbol.upper(),
                    "name": info.get("shortName", info.get("longName", symbol)),
                    "price": getattr(fast, "last_price", 0),
                    "change": 0,
                    "change_percent": 0,
                    "volume": getattr(fast, "last_volume", 0),
                    "high": getattr(fast, "day_high", 0),
                    "low": getattr(fast, "day_low", 0),
                    "open": getattr(fast, "open", 0),
                    "previous_close": getattr(fast, "previous_close", 0),
                    "market_cap": getattr(fast, "market_cap", None),
                    "pe_ratio": None,
                    "timestamp": datetime.now(timezone.utc),
                    "exchange": exchange,
                    "market": market,
                    "currency": currency,
                }

            market, exchange, currency = self._detect_market(symbol)
            price = info.get("regularMarketPrice", info.get("currentPrice", 0))
            prev_close = info.get("regularMarketPreviousClose", info.get("previousClose", 0))
            change = price - prev_close if price and prev_close else 0
            change_pct = (change / prev_close * 100) if prev_close else 0

            return {
                "symbol": symbol.upper(),
                "name": info.get("shortName", info.get("longName", symbol)),
                "price": price,
                "change": round(change, 2),
                "change_percent": round(change_pct, 2),
                "volume": info.get("regularMarketVolume", info.get("volume", 0)),
                "high": info.get("regularMarketDayHigh", info.get("dayHigh", 0)),
                "low": info.get("regularMarketDayLow", info.get("dayLow", 0)),
                "open": info.get("regularMarketOpen", info.get("open", 0)),
                "previous_close": prev_close,
                "market_cap": info.get("marketCap"),
                "pe_ratio": info.get("trailingPE", info.get("forwardPE")),
                "timestamp": datetime.now(timezone.utc),
                "exchange": exchange,
                "market": market,
                "currency": currency,
            }

        return await self.execute_with_resilience(_fetch)

    async def get_ohlcv(
        self, symbol: str, period: str = "1mo", interval: str = "1d"
    ) -> Optional[List[Dict[str, Any]]]:
        """Get historical OHLCV data."""

        async def _fetch():
            ticker = yf.Ticker(symbol)
            # Capture variables in default args to avoid closure bugs
            hist = await self._run_sync(
                lambda t=ticker, p=period, i=interval: t.history(period=p, interval=i)
            )

            if hist is None or hist.empty:
                return None

            bars = []
            for idx, row in hist.iterrows():
                bar = {
                    "date": idx.to_pydatetime().replace(tzinfo=timezone.utc)
                    if idx.tzinfo is None
                    else idx.to_pydatetime(),
                    "open": round(float(row["Open"]), 2),
                    "high": round(float(row["High"]), 2),
                    "low": round(float(row["Low"]), 2),
                    "close": round(float(row["Close"]), 2),
                    "volume": int(row["Volume"]),
                }
                # Handle adj_close — column name varies across yfinance versions
                for col_name in ["Adj Close", "adj_close", "Adj_Close"]:
                    if col_name in row.index:
                        bar["adj_close"] = round(float(row[col_name]), 2)
                        break
                else:
                    bar["adj_close"] = None
                bars.append(bar)
            return bars

        return await self.execute_with_resilience(_fetch)

    async def get_company_info(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Get company fundamentals and metadata."""

        async def _fetch():
            ticker = yf.Ticker(symbol)
            info = await self._run_sync(lambda t=ticker: t.info)

            if not info:
                return None

            market, exchange, currency = self._detect_market(symbol)

            return {
                "symbol": symbol.upper(),
                "name": info.get("shortName", info.get("longName", symbol)),
                "sector": info.get("sector"),
                "industry": info.get("industry"),
                "exchange": exchange,
                "market": market,
                "description": info.get("longBusinessSummary"),
                "website": info.get("website"),
                "metrics": {
                    "market_cap": info.get("marketCap"),
                    "pe_ratio": info.get("trailingPE"),
                    "eps": info.get("trailingEps"),
                    "revenue": info.get("totalRevenue"),
                    "revenue_growth": info.get("revenueGrowth"),
                    "profit_margin": info.get("profitMargins"),
                    "debt_to_equity": info.get("debtToEquity"),
                    "dividend_yield": info.get("dividendYield"),
                    "book_value": info.get("bookValue"),
                    "roe": info.get("returnOnEquity"),
                    "roa": info.get("returnOnAssets"),
                    "current_ratio": info.get("currentRatio"),
                },
            }

        return await self.execute_with_resilience(_fetch)

    async def search(self, query: str) -> List[Dict[str, Any]]:
        """Search for stocks by name or symbol."""

        async def _fetch():
            # yfinance doesn't have a proper search API
            # We try common patterns for Indian and US stocks
            results = []
            candidates = [
                query.upper(),
                f"{query.upper()}.NS",  # NSE
                f"{query.upper()}.BO",  # BSE
            ]

            for sym in candidates:
                try:
                    ticker = yf.Ticker(sym)
                    # Capture ticker in default arg to avoid closure bug
                    info = await self._run_sync(lambda t=ticker: t.info)
                    if info and info.get("regularMarketPrice") is not None:
                        market, exchange, currency = self._detect_market(sym)
                        results.append({
                            "symbol": sym,
                            "name": info.get("shortName", info.get("longName", sym)),
                            "exchange": exchange,
                            "market": market,
                            "sector": info.get("sector"),
                        })
                except Exception:
                    continue

            return results

        result = await self.execute_with_resilience(_fetch)
        return result or []

    async def get_market_indices(self) -> Optional[List[Dict[str, Any]]]:
        """Get major market indices (NIFTY 50, SENSEX, S&P 500, NASDAQ)."""
        indices = [
            {"symbol": "^NSEI", "name": "NIFTY 50"},
            {"symbol": "^BSESN", "name": "SENSEX"},
            {"symbol": "^GSPC", "name": "S&P 500"},
            {"symbol": "^IXIC", "name": "NASDAQ"},
        ]

        async def _fetch():
            results = []
            for idx in indices:
                try:
                    ticker = yf.Ticker(idx["symbol"])
                    # CRITICAL: capture ticker via default arg to avoid
                    # the classic Python closure-in-a-loop bug
                    info = await self._run_sync(lambda t=ticker: t.info)
                    if info:
                        price = info.get("regularMarketPrice", 0)
                        prev = info.get("regularMarketPreviousClose", 0)
                        change = price - prev if price and prev else 0
                        change_pct = (change / prev * 100) if prev else 0

                        results.append({
                            "symbol": idx["symbol"],
                            "name": idx["name"],
                            "value": round(price, 2),
                            "change": round(change, 2),
                            "change_percent": round(change_pct, 2),
                            "timestamp": datetime.now(timezone.utc),
                        })
                except Exception as e:
                    logger.warning(
                        "index_fetch_failed",
                        symbol=idx["symbol"],
                        error=str(e),
                    )
            return results

        return await self.execute_with_resilience(_fetch)

    async def health_check(self) -> bool:
        """Check if Yahoo Finance is reachable by fetching NIFTY 50."""
        try:
            ticker = yf.Ticker("^NSEI")
            info = await self._run_sync(lambda t=ticker: t.info)
            return info is not None and "regularMarketPrice" in info
        except Exception:
            return False
