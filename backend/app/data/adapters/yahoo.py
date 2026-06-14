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
from app.engines.data_quality.validator import DataQualityValidator

logger = get_logger(__name__)

# Thread pool for yfinance (it's synchronous)
# Limit to 2 workers to avoid memory spikes on Render free tier (512MB)
_executor = ThreadPoolExecutor(max_workers=2)

# Module-level data quality validator
_validator = DataQualityValidator()


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
        """Get current stock quote with basic info.

        Uses fast_info (lightweight, ~0.5s) as primary source.
        Falls back to full ticker.info only if fast_info fails.
        """

        async def _fetch():
            ticker = yf.Ticker(symbol)
            market, exchange, currency = self._detect_market(symbol)

            # Try fast_info FIRST — it's 10x faster and uses 10x less memory
            try:
                fast = await self._run_sync(lambda t=ticker: t.fast_info)
                if fast and getattr(fast, "last_price", 0):
                    price = getattr(fast, "last_price", 0)
                    prev_close = getattr(fast, "previous_close", 0)
                    change = price - prev_close if price and prev_close else 0
                    change_pct = (change / prev_close * 100) if prev_close else 0

                    return {
                        "symbol": symbol.upper(),
                        "name": symbol.replace(".NS", "").replace(".BO", ""),
                        "price": round(price, 2),
                        "change": round(change, 2),
                        "change_percent": round(change_pct, 2),
                        "volume": getattr(fast, "last_volume", 0) or 0,
                        "high": round(getattr(fast, "day_high", 0) or 0, 2),
                        "low": round(getattr(fast, "day_low", 0) or 0, 2),
                        "open": round(getattr(fast, "open", 0) or 0, 2),
                        "previous_close": round(prev_close or 0, 2),
                        "market_cap": getattr(fast, "market_cap", None),
                        "pe_ratio": None,  # fast_info doesn't have P/E
                        "timestamp": datetime.now(timezone.utc),
                        "exchange": exchange,
                        "market": market,
                        "currency": currency,
                    }
            except Exception as e:
                logger.debug("fast_info_failed", symbol=symbol, error=str(e))

            # Fallback to full info (slower, heavier)
            info = await self._run_sync(lambda t=ticker: t.info)

            if not info or "regularMarketPrice" not in info:
                return None

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

        result = await self.execute_with_resilience(_fetch)

        # ── Data quality validation (non-blocking) ──
        if result is not None:
            try:
                validation = _validator.validate_quote(result)
                result["_validation"] = validation.to_dict()
                if validation.errors:
                    logger.warning(
                        "quote_validation_errors",
                        symbol=symbol,
                        errors=validation.errors,
                    )
                if validation.warnings:
                    logger.info(
                        "quote_validation_warnings",
                        symbol=symbol,
                        warnings=validation.warnings,
                    )
            except Exception as e:
                logger.error("quote_validation_failed", symbol=symbol, error=str(e))

        return result

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

        result = await self.execute_with_resilience(_fetch)

        # ── Data quality validation (non-blocking) ──
        if result is not None:
            try:
                validation = _validator.validate_ohlcv_bars(result)
                if validation.warnings:
                    logger.info(
                        "ohlcv_validation_warnings",
                        symbol=symbol,
                        count=len(result),
                        warnings=validation.warnings,
                    )
                if validation.errors:
                    logger.warning(
                        "ohlcv_validation_errors",
                        symbol=symbol,
                        errors=validation.errors,
                    )
                # Attach validation as a dict wrapper so consumers can inspect it
                # We return a dict with data + validation instead of a bare list
                # only if the consumer opts in; for backward compat we keep the list.
                # Attach as an attribute on the list object.
                result = {"bars": result, "_validation": validation.to_dict()}
            except Exception as e:
                logger.error("ohlcv_validation_failed", symbol=symbol, error=str(e))
                result = {"bars": result, "_validation": None}

        return result

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
            symbols = [idx["symbol"] for idx in indices]
            symbol_str = " ".join(symbols)

            try:
                # Batch download all indices in ONE call
                df = await self._run_sync(
                    lambda: yf.download(
                        symbol_str,
                        period="2d",  # 2 days to compute change vs previous close
                        interval="1d",
                        group_by="ticker",
                        progress=False,
                        threads=False,
                    )
                )

                if df is None or df.empty:
                    return results

                for idx in indices:
                    sym = idx["symbol"]
                    try:
                        if len(symbols) == 1:
                            ticker_df = df
                        else:
                            if sym not in df.columns.get_level_values(0):
                                continue
                            ticker_df = df[sym]

                        if ticker_df.empty or len(ticker_df) < 1:
                            continue

                        last_row = ticker_df.iloc[-1]
                        price = float(last_row.get("Close", 0) or 0)

                        # Previous close from prior day row
                        if len(ticker_df) >= 2:
                            prev_row = ticker_df.iloc[-2]
                            prev = float(prev_row.get("Close", 0) or 0)
                        else:
                            prev = float(last_row.get("Open", 0) or 0)

                        if price == 0:
                            continue

                        change = price - prev if price and prev else 0
                        change_pct = (change / prev * 100) if prev else 0

                        results.append({
                            "symbol": sym,
                            "name": idx["name"],
                            "value": round(price, 2),
                            "change": round(change, 2),
                            "change_percent": round(change_pct, 2),
                            "timestamp": datetime.now(timezone.utc),
                        })
                    except Exception as e:
                        logger.warning(
                            "index_parse_failed",
                            symbol=sym,
                            error=str(e),
                        )
            except Exception as e:
                logger.error("indices_batch_fetch_failed", error=str(e))

            return results

        return await self.execute_with_resilience(_fetch)

    async def get_batch_quotes(
        self, symbols: list[str]
    ) -> list[dict[str, Any]]:
        """Batch-fetch quotes for multiple symbols using yf.download().

        This is MUCH more efficient than calling get_quote() N times:
        - yf.download() makes ONE HTTP request for all symbols
        - Uses ~10x less memory than N separate Ticker().info calls
        - Avoids triggering Yahoo's rate limiter

        Returns a list of quote dicts (same shape as get_quote output).
        Symbols that fail silently return None and are filtered out.
        """

        async def _fetch():
            import pandas as pd

            if not symbols:
                return []

            symbol_str = " ".join(symbols)

            # Use period="2d" so we always have yesterday's close for change calculation
            # (period="1d" returns empty during off-hours / weekends)
            df = await self._run_sync(
                lambda: yf.download(
                    symbol_str,
                    period="2d",
                    interval="1d",
                    group_by="ticker",
                    progress=False,
                    threads=False,  # Single thread to save memory
                )
            )

            if df is None or df.empty:
                return []

            results: list[dict[str, Any]] = []

            for sym in symbols:
                try:
                    market, exchange, currency = self._detect_market(sym)

                    if len(symbols) == 1:
                        # Single ticker: columns are flat (Open, High, Low, Close, Volume)
                        ticker_df = df
                    else:
                        # Multi-ticker: columns are MultiIndex (ticker, field)
                        if sym not in df.columns.get_level_values(0):
                            continue
                        ticker_df = df[sym]

                    if ticker_df.empty or len(ticker_df) < 1:
                        continue

                    # Drop rows where all values are NaN
                    ticker_df = ticker_df.dropna(how="all")
                    if ticker_df.empty:
                        continue

                    last_row = ticker_df.iloc[-1]
                    price = float(last_row.get("Close", 0) or 0)
                    high = float(last_row.get("High", 0) or 0)
                    low = float(last_row.get("Low", 0) or 0)
                    opn = float(last_row.get("Open", 0) or 0)
                    volume = int(last_row.get("Volume", 0) or 0)

                    if price == 0:
                        continue

                    # Get previous day's close for proper change calculation
                    if len(ticker_df) >= 2:
                        prev_row = ticker_df.iloc[-2]
                        prev_close = float(prev_row.get("Close", 0) or 0)
                    else:
                        prev_close = opn if opn > 0 else price

                    change = round(price - prev_close, 2) if prev_close else 0
                    change_pct = round((change / prev_close * 100), 2) if prev_close else 0

                    results.append({
                        "symbol": sym.upper(),
                        "name": sym.replace(".NS", "").replace(".BO", ""),
                        "price": round(price, 2),
                        "change": change,
                        "change_percent": change_pct,
                        "volume": volume,
                        "high": round(high, 2),
                        "low": round(low, 2),
                        "open": round(opn, 2),
                        "previous_close": round(prev_close, 2),
                        "market_cap": None,
                        "pe_ratio": None,
                        "timestamp": datetime.now(timezone.utc),
                        "exchange": exchange,
                        "market": market,
                        "currency": currency,
                    })
                except Exception as e:
                    logger.warning(
                        "batch_quote_parse_failed",
                        symbol=sym,
                        error=str(e),
                    )
                    continue

            return results

        result = await self.execute_with_resilience(_fetch)
        return result or []

    async def health_check(self) -> bool:
        """Check if Yahoo Finance is reachable by fetching NIFTY 50."""
        try:
            ticker = yf.Ticker("^NSEI")
            info = await self._run_sync(lambda t=ticker: t.info)
            return info is not None and "regularMarketPrice" in info
        except Exception:
            return False


# ── Module-level singleton ──────────────────────────────────────
# All routers and engines should import this instead of creating
# their own YahooFinanceAdapter instances. This ensures a single
# shared circuit breaker and thread pool across the application.
yahoo_adapter = YahooFinanceAdapter()

