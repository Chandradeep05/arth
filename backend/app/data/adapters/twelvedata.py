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
        """Store in cache with TTL and bounded max size."""
        now = time.monotonic()
        if len(_cache) > 500:
            expired = [k for k, v in _cache.items() if now >= v[1]]
            for k in expired:
                _cache.pop(k, None)
            if len(_cache) > 500:
                for k in list(_cache.keys())[:100]:
                    _cache.pop(k, None)
        _cache[key] = (data, now + ttl)

    @property
    def is_cooling_down(self) -> bool:
        """Check if adapter is currently in rate-limit cooldown."""
        return bool(self._cache_get("_rate_limit_cooldown"))

    async def _throttled_request(
        self, endpoint: str, params: Dict[str, Any],
        cache_key: Optional[str] = None, cache_ttl: float = _CACHE_TTL_QUOTE,
        quota_count: int = 1,
    ) -> Optional[Dict[str, Any]]:
        """Make a rate-limited, cached API request.

        On 429 (rate limit): returns None and sets a 60s cooldown.
        Does NOT raise — prevents circuit breaker from treating
        rate limits as outages.
        """
        # Check cache first — cache hits consume ZERO provider quota
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

            # Outbound request boundary: check and acquire central quota governor
            if quota_count > 0:
                from app.core.provider_quota import quota_governor
                if not await quota_governor.acquire("twelvedata", count=quota_count):
                    logger.warning("twelvedata_quota_governor_blocked", endpoint=endpoint, count=quota_count)
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

    @staticmethod
    def _parse_quote_payload(data: dict, fallback_symbol: str = "") -> Optional[Dict[str, Any]]:
        """Parse a raw Twelve Data /quote JSON object into the normalized quote dictionary.

        Shared by both single get_quote and batch get_batch_quotes to guarantee schema
        consistency and avoid cache-collision between raw API payloads and parsed outputs.
        """
        if not data or not isinstance(data, dict):
            return None
        if data.get("status") == "error":
            return None
        if "close" not in data:
            return None

        def _safe_float(val, fallback=0.0):
            """Parse to float, returning fallback for empty/missing/invalid."""
            if val is None or val == "":
                return fallback
            try:
                return float(val)
            except (ValueError, TypeError):
                return fallback

        price_raw = data.get("close")
        if price_raw is None or str(price_raw).strip() == "":
            return None
        price = _safe_float(price_raw, 0)
        if price <= 0:
            return None

        prev_close_raw = data.get("previous_close")
        prev_close = _safe_float(prev_close_raw, 0) if prev_close_raw is not None else None
        change = _safe_float(data.get("change"), 0)
        change_pct = _safe_float(data.get("percent_change"), 0)

        raw_open = _safe_float(data.get("open"), 0)
        raw_high = _safe_float(data.get("high"), 0)
        raw_low = _safe_float(data.get("low"), 0)

        quote_ts = None
        raw_ts = data.get("timestamp")
        if raw_ts and str(raw_ts).isdigit():
            quote_ts = datetime.fromtimestamp(int(raw_ts), tz=timezone.utc)

        sym = data.get("symbol", fallback_symbol)

        return {
            "symbol": sym.upper() if sym else "",
            "name": data.get("name", sym),
            "price": round(price, 2),
            "change": round(change, 2),
            "change_percent": round(change_pct, 2),
            "volume": int(_safe_float(data.get("volume"), 0)),
            "high": round(raw_high, 2) if raw_high > 0 else None,
            "low": round(raw_low, 2) if raw_low > 0 else None,
            "open": round(raw_open, 2) if raw_open > 0 else None,
            "previous_close": round(prev_close, 2) if prev_close is not None else None,
            "market_cap": None,  # Not in /quote, needs /statistics (paid)
            "pe_ratio": None,    # Not in /quote
            "timestamp": quote_ts,
            "exchange": data.get("exchange", "NASDAQ"),
            "market": "us",
            "currency": data.get("currency", "USD"),
        }

    async def get_quote(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Get US stock quote from Twelve Data /quote endpoint."""

        async def _fetch():
            # Stores and reads the RAW Twelve Data API payload under quote:{symbol}
            data = await self._throttled_request(
                "quote", {"symbol": symbol},
                cache_key=f"quote:{symbol}", cache_ttl=_CACHE_TTL_QUOTE,
            )
            return self._parse_quote_payload(data, fallback_symbol=symbol)

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
        still cost 1 credit per symbol.
        Cache checks are performed first so only actual misses consume quota.
        """
        all_results = []
        missing_symbols = []

        # Deduplicate symbols while preserving order
        unique_symbols = list(dict.fromkeys(symbols))

        # 1. Check cache for individually cached symbols first (0 quota cost).
        # We store the RAW Twelve Data item under quote:{symbol}. Parse with _parse_quote_payload
        # so single-quote and batch paths share the exact same raw payload representation.
        for sym in unique_symbols:
            cached_raw = self._cache_get(f"quote:{sym}")
            if cached_raw is not None and isinstance(cached_raw, dict):
                parsed = self._parse_quote_payload(cached_raw, fallback_symbol=sym)
                if parsed:
                    all_results.append(parsed)
                    continue
            missing_symbols.append(sym)

        if not missing_symbols:
            logger.debug("twelvedata_batch_all_cached", count=len(unique_symbols))
            return all_results

        # 2. Split missing symbols into chunks of _MAX_BATCH_SIZE (8)
        for i in range(0, len(missing_symbols), _MAX_BATCH_SIZE):
            # If we're already rate-limited, stop — return what we have so far
            if self._cache_get("_rate_limit_cooldown"):
                logger.info("twelvedata_batch_stopping_early", reason="rate_limited", fetched=len(all_results))
                break

            chunk = missing_symbols[i:i + _MAX_BATCH_SIZE]
            chunk_key = f"batch:{'|'.join(sorted(chunk))}"

            # Check cache for this exact chunk if previously cached together
            cached_chunk = self._cache_get(chunk_key)
            if cached_chunk is not None and cached_chunk:
                all_results.extend(cached_chunk)
                continue

            async def _fetch_chunk(syms=chunk):
                symbol_str = ",".join(syms)
                # Pass quota_count=len(syms) so quota governor acquires 1 credit per symbol in chunk
                data = await self._throttled_request(
                    "quote", {"symbol": symbol_str}, quota_count=len(syms),
                )
                if not data or not isinstance(data, dict):
                    return []

                if "symbol" in data:
                    raw_items = [data]
                else:
                    raw_items = [v for v in data.values()
                                 if isinstance(v, dict) and "symbol" in v]

                chunk_results = []
                for raw_item in raw_items:
                    if raw_item.get("status") == "error":
                        continue
                    # 1. Cache the RAW per-symbol payload under quote:{symbol}
                    # This guarantees that a subsequent single get_quote(sym) reads
                    # the exact same raw dictionary structure!
                    item_sym = raw_item.get("symbol", "")
                    if item_sym:
                        self._cache_set(f"quote:{item_sym}", raw_item, _CACHE_TTL_QUOTE)

                    # 2. Parse with the shared parser function
                    parsed = self._parse_quote_payload(raw_item, fallback_symbol=item_sym)
                    if parsed:
                        chunk_results.append(parsed)

                return chunk_results

            try:
                chunk_results = await self.execute_with_resilience(_fetch_chunk)
                chunk_results = chunk_results or []
                # NEVER cache empty results: quota denials or errors must remain retryable
                if chunk_results:
                    self._cache_set(chunk_key, chunk_results, _CACHE_TTL_QUOTE)
                all_results.extend(chunk_results)
            except Exception as e:
                logger.warning("twelvedata_batch_chunk_failed", error=str(e))

            # Brief pause between chunks to be polite (NOT 60s)
            if i + _MAX_BATCH_SIZE < len(missing_symbols):
                await asyncio.sleep(2)

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
