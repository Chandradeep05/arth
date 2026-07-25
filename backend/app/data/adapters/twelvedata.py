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
# Free tier: 8 credits/min. Each symbol in a request = 1 credit.
# With caching, we rarely hit the API more than once per 5min.
_request_semaphore = asyncio.Semaphore(1)
_MIN_REQUEST_INTERVAL = 1.0  # 1s between API calls (cache handles throttling)
_last_request_time = [0.0]

# ── In-memory cache ──────────────────────────────────────────────
# Avoids burning credits on repeat requests.
_cache: Dict[str, tuple] = {}  # key → (data, expiry_time)
_CACHE_TTL_QUOTE = 300       # 5 min for quotes
_CACHE_TTL_SEARCH = 3600     # 1 hour for searches
_CACHE_TTL_OHLCV = 600       # 10 min for OHLCV

# ── Shared httpx client ──────────────────────────────────────────
_http_client: Optional[httpx.AsyncClient] = None
_api_key: Optional[str] = None

BASE_URL = "https://api.twelvedata.com"

# Max symbols per batch (free tier = 8 credits/min)
_MAX_BATCH_SIZE = 8


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

    @staticmethod
    def _cache_get(key: str) -> Optional[Any]:
        """Get from cache if not expired."""
        entry = _cache.get(key)
        if entry and time.monotonic() < entry[1]:
            return entry[0]
        return None

    @staticmethod
    def _cache_set(key: str, data: Any, ttl: float):
        """Store in cache with TTL."""
        _cache[key] = (data, time.monotonic() + ttl)

    async def _throttled_request(
        self, endpoint: str, params: Dict[str, Any],
        cache_key: Optional[str] = None, cache_ttl: float = _CACHE_TTL_QUOTE,
    ) -> Optional[Dict[str, Any]]:
        """Make a rate-limited, cached API request.

        On 429 (rate limit): returns None and sets a 60s cooldown.
        Does NOT raise — prevents circuit breaker from treating
        rate limits as outages.
        """
        # Check cache first
        if cache_key:
            cached = self._cache_get(cache_key)
            if cached is not None:
                return cached

        # Check if we're in rate-limit cooldown
        if self._cache_get("_rate_limit_cooldown"):
            logger.debug("twelvedata_in_cooldown", endpoint=endpoint)
            return None

        api_key = _get_api_key()
        if not api_key:
            return None

        params["apikey"] = api_key

        async with _request_semaphore:
            # Re-check cache (another request may have populated it while waiting)
            if cache_key:
                cached = self._cache_get(cache_key)
                if cached is not None:
                    return cached

            # Re-check cooldown (might have been set while waiting for semaphore)
            if self._cache_get("_rate_limit_cooldown"):
                return None

            now = time.monotonic()
            elapsed = now - _last_request_time[0]
            if elapsed < _MIN_REQUEST_INTERVAL:
                await asyncio.sleep(_MIN_REQUEST_INTERVAL - elapsed)

            try:
                client = _get_client()
                resp = await client.get(f"{BASE_URL}/{endpoint}", params=params)
                _last_request_time[0] = time.monotonic()

                if resp.status_code == 429:
                    # Rate limited — set 60s cooldown and return None.
                    # Do NOT raise — this is not a service outage,
                    # it's a normal free-tier constraint.
                    logger.warning(
                        "twelvedata_rate_limited",
                        endpoint=endpoint,
                        cooldown_s=60,
                    )
                    self._cache_set("_rate_limit_cooldown", True, 60.0)
                    return None

                data = resp.json()

                # Check for API-level errors (wrong symbol, paid feature, etc.)
                if data.get("status") == "error":
                    code = data.get("code")
                    msg = data.get("message", "")

                    # Rate limit can also come as a JSON error
                    if code == 429 or "rate" in msg.lower():
                        logger.warning("twelvedata_rate_limited_json", endpoint=endpoint)
                        self._cache_set("_rate_limit_cooldown", True, 60.0)
                        return None

                    logger.warning(
                        "twelvedata_api_error",
                        endpoint=endpoint,
                        code=code,
                        message=msg,
                    )
                    return None

                # Cache successful response
                if cache_key:
                    self._cache_set(cache_key, data, cache_ttl)

                return data

            except httpx.HTTPError as e:
                logger.error("twelvedata_http_error", endpoint=endpoint, error=str(e))
                raise

    async def get_quote(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Get US stock quote from Twelve Data /quote endpoint."""

        async def _fetch():
            data = await self._throttled_request(
                "quote", {"symbol": symbol},
                cache_key=f"quote:{symbol}", cache_ttl=_CACHE_TTL_QUOTE,
            )
            if data is None or "close" not in data:
                return None

            def _safe_float(val, fallback=0.0):
                """Parse to float, returning fallback for empty/missing/invalid."""
                if val is None or val == "":
                    return fallback
                try:
                    return float(val)
                except (ValueError, TypeError):
                    return fallback

            price = _safe_float(data.get("close"), 0)
            prev_close = _safe_float(data.get("previous_close"), price)
            change = _safe_float(data.get("change"), 0)
            change_pct = _safe_float(data.get("percent_change"), 0)

            # open/high/low may be "0" or "" when market is closed.
            # Fall back to price so the UI never shows $0.00 or NaN.
            raw_open = _safe_float(data.get("open"), 0)
            raw_high = _safe_float(data.get("high"), 0)
            raw_low = _safe_float(data.get("low"), 0)

            return {
                "symbol": data.get("symbol", symbol).upper(),
                "name": data.get("name", symbol),
                "price": round(price, 2),
                "change": round(change, 2),
                "change_percent": round(change_pct, 2),
                "volume": int(_safe_float(data.get("volume"), 0)),
                "high": round(raw_high if raw_high > 0 else price, 2),
                "low": round(raw_low if raw_low > 0 else price, 2),
                "open": round(raw_open if raw_open > 0 else prev_close, 2),
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
            data = await self._throttled_request(
                "time_series",
                {"symbol": symbol, "interval": td_interval, "outputsize": outputsize},
                cache_key=f"ohlcv:{symbol}:{period}:{interval}",
                cache_ttl=_CACHE_TTL_OHLCV,
            )
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
            data = await self._throttled_request(
                "quote", {"symbol": symbol},
                cache_key=f"quote:{symbol}", cache_ttl=_CACHE_TTL_QUOTE,
            )
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
            data = await self._throttled_request(
                "symbol_search", {"symbol": query, "outputsize": 10},
                cache_key=f"search:{query.lower()}",
                cache_ttl=_CACHE_TTL_SEARCH,
            )
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
        """US indices are paid-only on free tier. Return empty."""
        # SPX, IXIC, DJI all require Grow/Venture plan.
        # Don't waste credits on calls that always fail.
        return []

    async def get_batch_quotes(self, symbols: List[str]) -> List[Dict[str, Any]]:
        """Batch-fetch quotes in chunks of 8 (free tier = 8 credits/min).

        Each symbol costs 1 credit. Comma-separated symbols in one call
        still cost 1 credit per symbol. So we chunk and cache aggressively.
        """
        all_results = []

        # Split into chunks of _MAX_BATCH_SIZE
        for i in range(0, len(symbols), _MAX_BATCH_SIZE):
            chunk = symbols[i:i + _MAX_BATCH_SIZE]
            chunk_key = f"batch:{'|'.join(sorted(chunk))}"

            # Check cache for this exact chunk
            cached = self._cache_get(chunk_key)
            if cached is not None:
                all_results.extend(cached)
                continue

            async def _fetch_chunk(syms=chunk):
                symbol_str = ",".join(syms)
                data = await self._throttled_request(
                    "quote", {"symbol": symbol_str},
                )
                if data is None:
                    return []

                results = []
                if isinstance(data, dict) and "symbol" in data:
                    items = [data]
                elif isinstance(data, dict):
                    items = [v for v in data.values()
                             if isinstance(v, dict) and "symbol" in v]
                else:
                    return []

                for item in items:
                    if item.get("status") == "error":
                        continue
                    try:
                        def _safe_float(val, fallback=0.0):
                            if val is None or val == "":
                                return fallback
                            try:
                                return float(val)
                            except (ValueError, TypeError):
                                return fallback

                        price = _safe_float(item.get("close"), 0)
                        prev_close = _safe_float(item.get("previous_close"), price)
                        # open/high/low may be "0" or "" when market is closed —
                        # fall back to price/prev_close so the UI never shows blanks.
                        raw_open = _safe_float(item.get("open"), 0)
                        raw_high = _safe_float(item.get("high"), 0)
                        raw_low = _safe_float(item.get("low"), 0)

                        results.append({
                            "symbol": item.get("symbol", ""),
                            "name": item.get("name", ""),
                            "price": round(price, 2),
                            "change": round(_safe_float(item.get("change"), 0), 2),
                            "change_percent": round(_safe_float(item.get("percent_change"), 0), 2),
                            "volume": int(_safe_float(item.get("volume"), 0)),
                            "high": round(raw_high if raw_high > 0 else price, 2),
                            "low": round(raw_low if raw_low > 0 else price, 2),
                            "open": round(raw_open if raw_open > 0 else prev_close, 2),
                            "previous_close": round(prev_close, 2),
                            "market_cap": None,
                            "pe_ratio": None,
                            "timestamp": datetime.now(timezone.utc),
                            "exchange": item.get("exchange", "NASDAQ"),
                            "market": "us",
                            "currency": item.get("currency", "USD"),
                        })
                    except (ValueError, TypeError):
                        continue

                return results

            try:
                chunk_results = await self.execute_with_resilience(_fetch_chunk)
                chunk_results = chunk_results or []
                # Cache the chunk results
                self._cache_set(chunk_key, chunk_results, _CACHE_TTL_QUOTE)
                all_results.extend(chunk_results)
            except Exception as e:
                logger.warning("twelvedata_batch_chunk_failed", error=str(e))

            # Wait 60s between chunks to reset credit counter
            if i + _MAX_BATCH_SIZE < len(symbols):
                await asyncio.sleep(60)

        return all_results

    async def health_check(self) -> bool:
        """Quick health check against Twelve Data."""
        try:
            data = await self._throttled_request(
                "quote", {"symbol": "AAPL"},
                cache_key="health:AAPL", cache_ttl=_CACHE_TTL_QUOTE,
            )
            return data is not None and "close" in data
        except Exception:
            return False


# ── Module-level singleton ──────────────────────────────────────
twelvedata_adapter = TwelveDataAdapter()
