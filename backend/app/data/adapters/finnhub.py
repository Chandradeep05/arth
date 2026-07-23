"""
Finnhub adapter — API key authenticated source for US stocks news, profiles, and basic fundamentals.

Free tier: 60 requests/min.
Endpoints used:
- /company-news    → get_news
- /stock/profile2  → get_company_info
- /stock/metric    → get_fundamentals
- /quote           → get_quote
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Dict, List, Optional
import httpx

from app.core.logging import get_logger
from app.data.adapters.base import BaseDataAdapter

logger = get_logger(__name__)

_request_semaphore = asyncio.Semaphore(2)
_MIN_REQUEST_INTERVAL = 0.2  # 60 req/min limit -> ~1s/5 req
_last_request_time = [0.0]

_cache: Dict[str, tuple] = {}
_CACHE_TTL_QUOTE = 300       # 5 min
_CACHE_TTL_PROFILE = 86400   # 24 hours
_CACHE_TTL_NEWS = 600        # 10 min
_CACHE_TTL_METRICS = 3600    # 1 hour

_http_client: Optional[httpx.AsyncClient] = None

BASE_URL = "https://finnhub.io/api/v1"


def _get_client() -> httpx.AsyncClient:
    global _http_client
    if _http_client is None or _http_client.is_closed:
        _http_client = httpx.AsyncClient(timeout=15.0)
    return _http_client


def _get_api_key() -> str:
    from app.config import get_settings
    settings = get_settings()
    key = settings.finnhub_api_key
    if not key or key == "YOUR_FINNHUB_KEY":
        return ""
    return key


class FinnhubAdapter(BaseDataAdapter):
    """Adapter for Finnhub REST API."""

    adapter_name = "finnhub"

    def __init__(self):
        super().__init__()

    async def _throttled_get(self, endpoint: str, params: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        api_key = _get_api_key()
        if not api_key:
            logger.warning("finnhub_key_missing", endpoint=endpoint)
            return None

        # Check in-memory cache
        cache_key = f"{endpoint}:{sorted(params.items())}"
        now = time.time()
        if cache_key in _cache:
            data, exp = _cache[cache_key]
            if now < exp:
                return data

        async with _request_semaphore:
            elapsed = now - _last_request_time[0]
            if elapsed < _MIN_REQUEST_INTERVAL:
                await asyncio.sleep(_MIN_REQUEST_INTERVAL - elapsed)
            _last_request_time[0] = time.time()

            client = _get_client()
            full_params = {**params, "token": api_key}

            try:
                resp = await client.get(f"{BASE_URL}/{endpoint}", params=full_params)
                if resp.status_code == 429:
                    logger.warning("finnhub_rate_limited", endpoint=endpoint)
                    return None
                if resp.status_code != 200:
                    logger.warning("finnhub_api_error", code=resp.status_code, endpoint=endpoint)
                    return None

                data = resp.json()

                # Determine cache TTL
                ttl = _CACHE_TTL_QUOTE
                if "profile" in endpoint:
                    ttl = _CACHE_TTL_PROFILE
                elif "news" in endpoint:
                    ttl = _CACHE_TTL_NEWS
                elif "metric" in endpoint:
                    ttl = _CACHE_TTL_METRICS

                _cache[cache_key] = (data, now + ttl)
                return data

            except Exception as e:
                logger.error("finnhub_request_failed", endpoint=endpoint, error=str(e))
                return None

    async def get_company_info(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Fetch company profile from /stock/profile2."""
        clean_symbol = symbol.split(".")[0].upper()
        raw = await self._throttled_get("stock/profile2", {"symbol": clean_symbol})
        if not raw or not raw.get("name"):
            return None

        return {
            "symbol": symbol.upper(),
            "name": raw.get("name", ""),
            "exchange": raw.get("exchange", ""),
            "currency": raw.get("currency", "USD"),
            "country": raw.get("country", ""),
            "industry": raw.get("finnhubIndustry", ""),
            "market_cap": raw.get("marketCapitalization"),
            "share_outstanding": raw.get("shareOutstanding"),
            "weburl": raw.get("weburl", ""),
            "logo": raw.get("logo", ""),
        }

    async def get_news(self, symbol: str, count: int = 15) -> Optional[List[Dict[str, Any]]]:
        """Fetch company news from /company-news."""
        from datetime import datetime, timedelta
        clean_symbol = symbol.split(".")[0].upper()

        to_date = datetime.now().strftime("%Y-%m-%d")
        from_date = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")

        raw = await self._throttled_get("company-news", {
            "symbol": clean_symbol,
            "from": from_date,
            "to": to_date
        })

        if not raw or not isinstance(raw, list):
            return None

        articles = []
        for item in raw[:count]:
            articles.append({
                "headline": item.get("headline", ""),
                "summary": item.get("summary", ""),
                "url": item.get("url", ""),
                "datetime": item.get("datetime"),
                "source": item.get("source", "Finnhub"),
                "image": item.get("image", "")
            })

        return articles if articles else None

    async def get_fundamentals(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Fetch financial metrics from /stock/metric."""
        clean_symbol = symbol.split(".")[0].upper()
        raw = await self._throttled_get("stock/metric", {"symbol": clean_symbol, "metric": "all"})
        if not raw or "metric" not in raw:
            return None

        m = raw["metric"]
        return {
            "pe_ratio": m.get("peBasicExclExtraTTM") or m.get("peNormalizedAnnual"),
            "pb_ratio": m.get("pbAnnual") or m.get("pbQuarterly"),
            "ps_ratio": m.get("psTTM"),
            "roe": m.get("roeTTM"),
            "roa": m.get("roaTTM"),
            "eps_ttm": m.get("epsTTM"),
            "52_week_high": m.get("52WeekHigh"),
            "52_week_low": m.get("52WeekLow"),
            "beta": m.get("beta"),
            "dividend_yield": m.get("dividendYieldIndicatedAnnual"),
        }


    async def get_quote(self, symbol: str) -> Optional[Dict[str, Any]]:
        clean_symbol = symbol.split(".")[0].upper()
        raw = await self._throttled_get("quote", {"symbol": clean_symbol})
        if not raw or raw.get("c") is None:
            return None
        return {
            "symbol": symbol.upper(),
            "price": raw.get("c"),
            "change": raw.get("d"),
            "percent_change": raw.get("dp"),
            "high": raw.get("h"),
            "low": raw.get("l"),
            "open": raw.get("o"),
            "previous_close": raw.get("pc"),
        }

    async def get_ohlcv(self, symbol: str, period: str = "1mo", interval: str = "1d") -> Optional[List[Dict[str, Any]]]:
        return None

    async def search(self, query: str) -> List[Dict[str, Any]]:
        raw = await self._throttled_get("search", {"q": query})
        if not raw or "result" not in raw:
            return []
        return raw.get("result", [])

    async def health_check(self) -> bool:
        return _get_api_key() != ""


finnhub_adapter = FinnhubAdapter()
