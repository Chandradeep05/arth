"""
Twelve Data adapter — API-key authenticated source for US stocks.

Uses REST API (httpx async) instead of scraping. No IP blocking.
Free tier: 8 credits/min, 800/day. US stocks only (NSE/BSE requires paid).

Endpoints used:
- /quote          → get_quote, get_batch_quotes, get_market_indices
- /time_series    → get_ohlcv
- /symbol_search  → search
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx

from app.core.logging import get_logger
from app.data.adapters.base import BaseDataAdapter

logger = get_logger(__name__)

# ── Rate limiting ─────────────────────────────────────────────────
# Free tier: 8 credits/min. We cap at 7 to leave margin.
_request_semaphore = asyncio.Semaphore(1)
_MIN_REQUEST_INTERVAL = 9.0  # ~6.6 req/min (safe under 8)
_last_request_time = [0.0]

# ── Shared httpx client ──────────────────────────────────────────
_http_client: Optional[httpx.AsyncClient] = None
_api_key: Optional[str] = None

BASE_URL = "https://api.twelvedata.com"

# Index symbol mapping: yfinance format → Twelve Data format
_INDEX_MAP = {
    "^GSPC": "SPX",       # S&P 500
    "^IXIC": "IXIC",      # NASDAQ Composite
    "^DJI": "DJI",        # Dow Jones
}

# Index display names
_INDEX_NAMES = {
    "SPX": "S&P 500",
    "IXIC": "NASDAQ",
    "DJI": "Dow Jones",
}


def _get_client() -> httpx.AsyncClient:
    """Get or create shared httpx client."""
    global _http_client
    if _http_client is None or _http_client.is_closed:
        _http_client = httpx.AsyncClient(timeout=15.0)
    return _http_client


def _get_api_key() -> str:
    """Get API key from settings (lazy load to avoid import cycles)."""
    global _api_key
    if _api_key is None:
        from app.config import get_settings
        _api_key = get_settings().twelvedata_api_key
        if _api_key:
            logger.info("twelvedata_configured", key_prefix=_api_key[:6] + "...")
        else:
            logger.warning("twelvedata_no_api_key",
                           note="Set TWELVEDATA_API_KEY env var for US stock data")
    return _api_key


class TwelveDataAdapter(BaseDataAdapter):
    """Twelve Data REST API adapter for US stocks."""

    adapter_name = "twelvedata"

    async def _throttled_request(
        self, endpoint: str, params: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """Make a rate-limited API request."""
        api_key = _get_api_key()
        if not api_key:
            return None

        params["apikey"] = api_key

        async with _request_semaphore:
            now = time.monotonic()
            elapsed = now - _last_request_time[0]
            if elapsed < _MIN_REQUEST_INTERVAL:
                await asyncio.sleep(_MIN_REQUEST_INTERVAL - elapsed)

            try:
                client = _get_client()
                resp = await client.get(f"{BASE_URL}/{endpoint}", params=params)
                _last_request_time[0] = time.monotonic()

                if resp.status_code == 429:
                    logger.warning("twelvedata_rate_limited", endpoint=endpoint)
                    raise Exception("Too Many Requests. Rate limited. Try after a while.")

                data = resp.json()

                if data.get("status") == "error":
                    logger.warning(
                        "twelvedata_api_error",
                        endpoint=endpoint,
                        code=data.get("code"),
                        message=data.get("message", ""),
                    )
                    return None

                return data

            except httpx.HTTPError as e:
                logger.error("twelvedata_http_error", endpoint=endpoint, error=str(e))
                raise

    async def get_quote(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Get US stock quote from Twelve Data /quote endpoint."""

        async def _fetch():
            data = await self._throttled_request("quote", {"symbol": symbol})
            if data is None or "close" not in data:
                return None

            price = float(data.get("close", 0))
            prev_close = float(data.get("previous_close", 0))
            change = float(data.get("change", 0))
            change_pct = float(data.get("percent_change", 0))

            return {
                "symbol": data.get("symbol", symbol).upper(),
                "name": data.get("name", symbol),
                "price": round(price, 2),
                "change": round(change, 2),
                "change_percent": round(change_pct, 2),
                "volume": int(data.get("volume", 0)),
                "high": round(float(data.get("high", 0)), 2),
                "low": round(float(data.get("low", 0)), 2),
                "open": round(float(data.get("open", 0)), 2),
                "previous_close": round(prev_close, 2),
                "market_cap": None,  # Not in /quote, needs /statistics (paid)
                "pe_ratio": None,    # Not in /quote
                "timestamp": datetime.now(timezone.utc),
                "exchange": data.get("exchange", "NASDAQ"),
                "market": "us",
                "currency": data.get("currency", "USD"),
            }

        return await self.execute_with_resilience(_fetch)

    async def get_ohlcv(
        self, symbol: str, period: str = "1mo", interval: str = "1d"
    ) -> Optional[Dict[str, Any]]:
        """Get historical OHLCV from Twelve Data /time_series."""

        # Map yfinance periods to Twelve Data outputsize
        period_to_size = {
            "1d": 1, "5d": 5, "1mo": 22, "3mo": 66,
            "6mo": 132, "1y": 252, "2y": 504, "5y": 1260,
        }
        outputsize = period_to_size.get(period, 22)

        # Map intervals
        interval_map = {
            "1d": "1day", "1wk": "1week", "1mo": "1month",
            "1h": "1h", "5m": "5min", "15m": "15min", "1m": "1min",
        }
        td_interval = interval_map.get(interval, "1day")

        async def _fetch():
            data = await self._throttled_request("time_series", {
                "symbol": symbol,
                "interval": td_interval,
                "outputsize": outputsize,
            })
            if data is None or "values" not in data:
                return None

            bars = []
            for bar_data in reversed(data["values"]):  # TD returns newest first
                try:
                    bars.append({
                        "date": datetime.strptime(
                            bar_data["datetime"], "%Y-%m-%d"
                        ).replace(tzinfo=timezone.utc),
                        "open": round(float(bar_data["open"]), 2),
                        "high": round(float(bar_data["high"]), 2),
                        "low": round(float(bar_data["low"]), 2),
                        "close": round(float(bar_data["close"]), 2),
                        "volume": int(bar_data.get("volume", 0)),
                        "adj_close": None,
                    })
                except (ValueError, KeyError):
                    continue

            return {"bars": bars}

        return await self.execute_with_resilience(_fetch)

    async def get_company_info(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Build company info from /quote data (profile endpoint is paid-only)."""

        async def _fetch():
            data = await self._throttled_request("quote", {"symbol": symbol})
            if data is None or "close" not in data:
                return None

            return {
                "symbol": data.get("symbol", symbol).upper(),
                "name": data.get("name", symbol),
                "sector": None,       # Needs /profile (paid)
                "industry": None,     # Needs /profile (paid)
                "exchange": data.get("exchange", "NASDAQ"),
                "market": "us",
                "description": None,  # Needs /profile (paid)
                "website": None,      # Needs /profile (paid)
                "metrics": {
                    "market_cap": None,
                    "pe_ratio": None,
                    "eps": None,
                    "revenue": None,
                    "revenue_growth": None,
                    "profit_margin": None,
                    "debt_to_equity": None,
                    "dividend_yield": None,
                    "book_value": None,
                    "roe": None,
                    "roa": None,
                    "current_ratio": None,
                },
            }

        return await self.execute_with_resilience(_fetch)

    async def search(self, query: str) -> List[Dict[str, Any]]:
        """Search symbols via /symbol_search."""

        async def _fetch():
            data = await self._throttled_request("symbol_search", {
                "symbol": query,
                "outputsize": 10,
            })
            if data is None or "data" not in data:
                return []

            results = []
            for item in data["data"]:
                results.append({
                    "symbol": item.get("symbol", ""),
                    "name": item.get("instrument_name", ""),
                    "exchange": item.get("exchange", ""),
                    "market": "india" if item.get("exchange") in ("NSE", "BSE") else "us",
                    "sector": None,
                })
            return results

        result = await self.execute_with_resilience(_fetch)
        return result or []

    async def get_market_indices(self) -> List[Dict[str, Any]]:
        """Get US indices (S&P 500, NASDAQ) from Twelve Data."""

        async def _fetch():
            results = []
            for yf_symbol, td_symbol in _INDEX_MAP.items():
                try:
                    data = await self._throttled_request("quote", {"symbol": td_symbol})
                    if data and "close" in data:
                        price = float(data.get("close", 0))
                        change = float(data.get("change", 0))
                        change_pct = float(data.get("percent_change", 0))

                        results.append({
                            "symbol": yf_symbol,
                            "name": _INDEX_NAMES.get(td_symbol, td_symbol),
                            "price": round(price, 2),
                            "change": round(change, 2),
                            "change_percent": round(change_pct, 2),
                            "market": "us",
                        })
                except Exception as e:
                    logger.warning("twelvedata_index_failed",
                                   symbol=td_symbol, error=str(e))
                    continue

            return results

        result = await self.execute_with_resilience(_fetch)
        return result or []

    async def get_batch_quotes(self, symbols: List[str]) -> List[Dict[str, Any]]:
        """Batch-fetch quotes. Twelve Data supports comma-separated symbols."""

        async def _fetch():
            # Twelve Data allows comma-separated symbols in one /quote call
            symbol_str = ",".join(symbols)
            data = await self._throttled_request("quote", {"symbol": symbol_str})
            if data is None:
                return []

            # Single symbol returns a dict, multiple returns a dict of dicts
            results = []
            if isinstance(data, dict) and "symbol" in data:
                # Single symbol response
                items = [data]
            elif isinstance(data, dict):
                # Multiple symbols — values are the quote dicts
                items = [v for v in data.values() if isinstance(v, dict) and "symbol" in v]
            else:
                return []

            for item in items:
                if item.get("status") == "error":
                    continue
                try:
                    price = float(item.get("close", 0))
                    change = float(item.get("change", 0))
                    change_pct = float(item.get("percent_change", 0))
                    volume = int(item.get("volume", 0))

                    results.append({
                        "symbol": item.get("symbol", ""),
                        "name": item.get("name", ""),
                        "price": round(price, 2),
                        "change": round(change, 2),
                        "change_percent": round(change_pct, 2),
                        "volume": volume,
                    })
                except (ValueError, TypeError):
                    continue

            return results

        result = await self.execute_with_resilience(_fetch)
        return result or []

    async def health_check(self) -> bool:
        """Quick health check against Twelve Data."""
        try:
            data = await self._throttled_request("quote", {"symbol": "AAPL"})
            return data is not None and "close" in data
        except Exception:
            return False


# ── Module-level singleton ──────────────────────────────────────
twelvedata_adapter = TwelveDataAdapter()
