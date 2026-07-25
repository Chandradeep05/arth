"""
NSE India adapter — official NSE API for Indian stocks & indices.

Free, no API key, no account. Requires cookie management:
1. Hit nseindia.com homepage to get session cookies
2. Use those cookies for API calls (expire ~30min)
3. Auto-refresh cookies when they expire

Endpoints:
- /api/quote-equity?symbol=RELIANCE     → stock quote
- /api/allIndices                        → NIFTY 50, SENSEX, etc.
- /api/chart-databyindex?index=RELIANCEEQn  → intraday chart
- /api/historical/cm/equity?symbol=RELIANCE  → historical OHLCV
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional

import httpx

from app.core.logging import get_logger

logger = get_logger(__name__)

# ── Circuit Breaker State ─────────────────────────────────────────
class _CircuitState(Enum):
    CLOSED = 'closed'       # Normal operation, requests go through
    OPEN = 'open'           # Failed, all requests return None immediately
    HALF_OPEN = 'half_open' # Cooldown expired, next request is a probe


# ── Cookie management ─────────────────────────────────────────────
_HOMEPAGE = "https://www.nseindia.com"
_API_BASE = "https://www.nseindia.com/api"

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate",
    "Referer": "https://www.nseindia.com",
    "Connection": "keep-alive",
}

# Rate limiting: NSE is sensitive to rapid requests
_request_lock = asyncio.Lock()
_MIN_INTERVAL = 1.5  # seconds between requests
_last_request_time = [0.0]


class NSESession:
    """Manages NSE cookies and session lifecycle."""

    def __init__(self):
        self._client: Optional[httpx.AsyncClient] = None
        self._cookie_time: float = 0.0
        self._cookie_ttl: float = 1500.0  # 25 min (cookies expire ~30min)
        self._initialized = False
        
        self._circuit_state = _CircuitState.CLOSED
        self._circuit_opened_at: float = 0.0
        self._consecutive_failures: int = 0
        self._circuit_cooldown: float = 300.0  # 5 minutes
        self._failure_threshold: int = 3  # Open after 3 consecutive 403s

    async def _ensure_client(self):
        """Create client if needed."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                headers=_HEADERS,
                timeout=15.0,
                follow_redirects=True,
            )
            self._initialized = False

    async def _refresh_cookies(self):
        """Visit NSE homepage to get fresh session cookies."""
        if self._circuit_state == _CircuitState.OPEN:
            return
            
        await self._ensure_client()
        try:
            resp = await self._client.get(_HOMEPAGE)
            if resp.status_code == 200:
                self._cookie_time = time.monotonic()
                self._initialized = True
                logger.info("nse_cookies_refreshed")
            else:
                logger.warning("nse_cookie_refresh_failed", status=resp.status_code)
        except Exception as e:
            logger.error("nse_cookie_refresh_error", error=str(e))

    async def get(self, endpoint: str, params: Optional[dict] = None) -> Optional[dict]:
        """Make an authenticated API request to NSE."""
        async with _request_lock:
            now = time.monotonic()
            
            # Check circuit state FIRST
            if self._circuit_state == _CircuitState.OPEN:
                if (now - self._circuit_opened_at) > self._circuit_cooldown:
                    self._circuit_state = _CircuitState.HALF_OPEN
                else:
                    return None
            
            # Rate limit
            elapsed = now - _last_request_time[0]
            if elapsed < _MIN_INTERVAL:
                await asyncio.sleep(_MIN_INTERVAL - elapsed)

            # Refresh cookies if needed
            if not self._initialized or (now - self._cookie_time) > self._cookie_ttl:
                await self._refresh_cookies()

            try:
                resp = await self._client.get(
                    f"{_API_BASE}/{endpoint}",
                    params=params,
                )
                _last_request_time[0] = time.monotonic()

                if resp.status_code == 401 or resp.status_code == 403:
                    if self._circuit_state != _CircuitState.OPEN:
                        # Cookies expired, refresh and retry once
                        logger.info("nse_cookies_expired_retrying")
                        await self._refresh_cookies()
                        resp = await self._client.get(
                            f"{_API_BASE}/{endpoint}",
                            params=params,
                        )
                        _last_request_time[0] = time.monotonic()

                # Process response and update circuit state
                if resp.status_code == 200:
                    if self._circuit_state == _CircuitState.HALF_OPEN:
                        self._circuit_state = _CircuitState.CLOSED
                        logger.info("nse_circuit_closed")
                    self._consecutive_failures = 0
                elif resp.status_code == 403:
                    self._consecutive_failures += 1
                    if self._circuit_state == _CircuitState.HALF_OPEN:
                        self._circuit_state = _CircuitState.OPEN
                        self._circuit_opened_at = time.monotonic()
                        logger.warning("nse_circuit_reopened")
                    elif self._circuit_state == _CircuitState.CLOSED and self._consecutive_failures >= self._failure_threshold:
                        self._circuit_state = _CircuitState.OPEN
                        self._circuit_opened_at = time.monotonic()
                        logger.warning("nse_circuit_opened")

                if resp.status_code != 200:
                    logger.warning(
                        "nse_api_error",
                        endpoint=endpoint,
                        status=resp.status_code,
                    )
                    return None

                return resp.json()

            except httpx.HTTPError as e:
                logger.error("nse_http_error", endpoint=endpoint, error=str(e))
                return None
            except Exception as e:
                logger.error("nse_request_error", endpoint=endpoint, error=str(e))
                return None

    async def close(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()


# ── Module-level session ──────────────────────────────────────────
_session = NSESession()


def _clean_symbol(symbol: str) -> str:
    """Convert yfinance-style symbol to NSE symbol.
    RELIANCE.NS → RELIANCE, TCS.NS → TCS
    """
    return symbol.upper().replace(".NS", "").replace(".BO", "")


class NSEAdapter:
    """NSE India official API adapter."""

    async def get_quote(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Get stock quote from NSE."""
        clean = _clean_symbol(symbol)
        data = await _session.get("quote-equity", params={"symbol": clean})

        if data is None:
            return None

        price_info = data.get("priceInfo", {})
        info = data.get("info", {})
        metadata = data.get("metadata", {})

        price = price_info.get("lastPrice", 0)
        prev_close = price_info.get("previousClose", 0)
        change = price_info.get("change", 0)
        change_pct = price_info.get("pChange", 0)

        if not price:
            return None

        return {
            "symbol": symbol.upper(),
            "name": info.get("companyName", metadata.get("companyName", clean)),
            "price": round(float(price), 2),
            "change": round(float(change), 2),
            "change_percent": round(float(change_pct), 2),
            "volume": int(price_info.get("totalTradedVolume", 0) or 0),
            "high": round(float(price_info.get("intraDayHighLow", {}).get("max", 0) or 0), 2),
            "low": round(float(price_info.get("intraDayHighLow", {}).get("min", 0) or 0), 2),
            "open": round(float(price_info.get("open", 0) or 0), 2),
            "previous_close": round(float(prev_close or 0), 2),
            "market_cap": None,
            "pe_ratio": metadata.get("pdSymbolPe"),
            "timestamp": datetime.now(timezone.utc),
            "exchange": "NSE",
            "market": "india",
            "currency": "INR",
        }

    async def get_market_indices(self) -> List[Dict[str, Any]]:
        """Get NIFTY 50, SENSEX and other indices."""
        data = await _session.get("allIndices")
        if data is None:
            return []

        results = []
        target_indices = {
            "NIFTY 50": "^NSEI",
            "NIFTY BANK": "^NSEBANK",
            "INDIA VIX": "^INDIAVIX",
            "NIFTY NEXT 50": "^NSMIDCP",
        }

        now = datetime.now(timezone.utc)

        for idx in data.get("data", []):
            name = idx.get("index", "")
            if name in target_indices:
                try:
                    results.append({
                        "symbol": target_indices[name],
                        "name": name,
                        "value": round(float(idx.get("last", 0)), 2),
                        "change": round(float(idx.get("variation", 0)), 2),
                        "change_percent": round(float(idx.get("percentChange", 0)), 2),
                        "timestamp": now,
                    })
                except (ValueError, TypeError):
                    continue

        # Try to get SENSEX from BSE section if available
        # NSE allIndices sometimes includes S&P BSE SENSEX
        for idx in data.get("data", []):
            name = idx.get("index", "")
            if "SENSEX" in name.upper():
                try:
                    results.append({
                        "symbol": "^BSESN",
                        "name": "S&P BSE SENSEX",
                        "value": round(float(idx.get("last", 0)), 2),
                        "change": round(float(idx.get("variation", 0)), 2),
                        "change_percent": round(float(idx.get("percentChange", 0)), 2),
                        "timestamp": now,
                    })
                    break
                except (ValueError, TypeError):
                    continue

        return results

    async def get_ohlcv(
        self, symbol: str, period: str = "1mo", interval: str = "1d"
    ) -> Optional[Dict[str, Any]]:
        """Get historical OHLCV from NSE.
        
        Uses the equity trade history endpoint.
        """
        clean = _clean_symbol(symbol)

        # Map period to date range
        period_days = {
            "1d": 1, "5d": 5, "1mo": 30, "3mo": 90,
            "6mo": 180, "1y": 365, "2y": 730,
        }
        days = period_days.get(period, 30)
        end_date = datetime.now()
        start_date = end_date - timedelta(days=days)

        data = await _session.get("historical/cm/equity", params={
            "symbol": clean,
            "from": start_date.strftime("%d-%m-%Y"),
            "to": end_date.strftime("%d-%m-%Y"),
        })

        if data is None or not data.get("data"):
            return None

        bars = []
        for row in data["data"]:
            try:
                # Parse NSE date format: "30-Jun-2026" or "2026-06-30"
                date_str = row.get("CH_TIMESTAMP", row.get("mTIMESTAMP", ""))
                try:
                    dt = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
                except ValueError:
                    try:
                        dt = datetime.strptime(date_str, "%d-%b-%Y").replace(tzinfo=timezone.utc)
                    except ValueError:
                        continue

                bars.append({
                    "date": dt,
                    "open": round(float(row.get("CH_OPENING_PRICE", row.get("open", 0))), 2),
                    "high": round(float(row.get("CH_TRADE_HIGH_PRICE", row.get("high", 0))), 2),
                    "low": round(float(row.get("CH_TRADE_LOW_PRICE", row.get("low", 0))), 2),
                    "close": round(float(row.get("CH_CLOSING_PRICE", row.get("close", 0))), 2),
                    "volume": int(float(row.get("CH_TOT_TRADED_QTY", row.get("volume", 0)) or 0)),
                    "adj_close": None,
                })
            except (ValueError, TypeError, KeyError):
                continue

        # Sort chronologically
        bars.sort(key=lambda x: x["date"])
        return {"bars": bars} if bars else None

    async def get_company_info(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Get company info from NSE quote endpoint."""
        clean = _clean_symbol(symbol)
        data = await _session.get("quote-equity", params={"symbol": clean})

        if data is None:
            return None

        info = data.get("info", {})
        metadata = data.get("metadata", {})
        security_info = data.get("securityInfo", {})

        return {
            "symbol": symbol.upper(),
            "name": info.get("companyName", metadata.get("companyName", clean)),
            "sector": metadata.get("industry", metadata.get("sector")),
            "industry": metadata.get("industry"),
            "exchange": "NSE",
            "market": "india",
            "description": None,  # NSE doesn't provide descriptions
            "website": None,
            "metrics": {
                "market_cap": None,
                "pe_ratio": metadata.get("pdSymbolPe"),
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

    async def search(self, query: str) -> List[Dict[str, Any]]:
        """Search NSE stocks. Uses the search autocomplete endpoint."""
        data = await _session.get("search/autocomplete", params={"q": query})
        if data is None:
            return []

        results = []
        for item in data.get("symbols", []):
            results.append({
                "symbol": f"{item.get('symbol', '')}.NS",
                "name": item.get("symbol_info", item.get("symbol", "")),
                "exchange": "NSE",
                "market": "india",
                "sector": None,
            })
        return results

    async def health_check(self) -> bool:
        """Quick health check."""
        try:
            data = await _session.get("allIndices")
            return data is not None and "data" in data
        except Exception:
            return False


# ── Module-level singleton ──────────────────────────────────────
nse_adapter = NSEAdapter()
