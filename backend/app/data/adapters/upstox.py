"""
Upstox adapter - Data source for Indian stocks.
"""
from __future__ import annotations

import asyncio
import gzip
import json
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx

from app.core.logging import get_logger
from app.data.adapters.base import BaseDataAdapter

logger = get_logger(__name__)

BASE_URL = "https://api.upstox.com"
_CACHE_TTL_QUOTE = 120       # 2 min for quotes
_CACHE_TTL_OHLCV = 600       # 10 min for OHLCV  
_CACHE_TTL_FUNDAMENTALS = 86400  # 24 hours
_CACHE_TTL_NEWS = 1800       # 30 min
_CACHE_TTL_INSTRUMENTS = 86400  # 24 hours

_request_semaphore = asyncio.Semaphore(5)

_cache: Dict[str, tuple] = {}

_http_client: Optional[httpx.AsyncClient] = None

# Static index map
_STATIC_INDEX_MAP = {
    "^NSEI": "NSE_INDEX|Nifty 50",
    "^NSEBANK": "NSE_INDEX|Nifty Bank",
    "^BSESN": "BSE_INDEX|SENSEX",
}

def _get_client() -> httpx.AsyncClient:
    global _http_client
    if _http_client is None or _http_client.is_closed:
        _http_client = httpx.AsyncClient(timeout=15.0)
    return _http_client

def _get_token() -> str:
    from app.config import get_settings
    settings = get_settings()
    return settings.upstox_analytics_token

class UpstoxAdapter(BaseDataAdapter):
    adapter_name = "upstox"

    def __init__(self):
        super().__init__()
        self._symbol_to_key: Dict[str, str] = {}
        self._key_to_symbol: Dict[str, str] = {}
        self._symbol_to_isin: Dict[str, str] = {}
        self._instruments_loaded = False
        self._instruments_last_load = 0.0
        
        for sym, key in _STATIC_INDEX_MAP.items():
            self._symbol_to_key[sym] = key
            self._key_to_symbol[key] = sym
            
    def _cache_get(self, key: str) -> Optional[Any]:
        if key in _cache:
            data, expiry = _cache[key]
            if time.time() < expiry:
                return data
            del _cache[key]
        return None

    def _cache_set(self, key: str, data: Any, ttl: int) -> None:
        _cache[key] = (data, time.time() + ttl)

    async def _load_instruments(self) -> None:
        now = time.time()
        if self._instruments_loaded and (now - self._instruments_last_load < _CACHE_TTL_INSTRUMENTS):
            return
            
        try:
            client = _get_client()
            for exchange in ["NSE", "BSE"]:
                url = f"https://assets.upstox.com/market-quote/instruments/exchange/{exchange}.json.gz"
                resp = await client.get(url)
                if resp.status_code == 200:
                    data = gzip.decompress(resp.content)
                    instruments = json.loads(data)
                    for inst in instruments:
                        symbol = inst.get("trading_symbol") or inst.get("tradingsymbol")
                        if not symbol:
                            continue
                        # Only process equity instruments
                        inst_type = inst.get("instrument_type", "")
                        if inst_type and inst_type not in ("EQ", ""):
                            continue
                            
                        std_symbol = f"{symbol}.NS" if exchange == "NSE" else f"{symbol}.BO"
                        key = inst.get("instrument_key")
                        isin = inst.get("isin")
                        
                        if key:
                            self._symbol_to_key[std_symbol] = key
                            self._key_to_symbol[key] = std_symbol
                        if isin:
                            self._symbol_to_isin[std_symbol] = isin
                            
            self._instruments_loaded = True
            self._instruments_last_load = now
            logger.info("upstox_instruments_loaded")
        except Exception as e:
            logger.error("upstox_instrument_load_failed", error=str(e))

    async def _get_instrument_key(self, symbol: str) -> Optional[str]:
        if symbol in _STATIC_INDEX_MAP:
            return _STATIC_INDEX_MAP[symbol]
        await self._load_instruments()
        return self._symbol_to_key.get(symbol.upper())

    async def _get_isin(self, symbol: str) -> Optional[str]:
        await self._load_instruments()
        return self._symbol_to_isin.get(symbol.upper())

    async def _throttled_request(
        self,
        method: str,
        endpoint: str,
        params: Optional[Dict[str, Any]] = None,
        cache_key: Optional[str] = None,
        cache_ttl: int = 0,
    ) -> Optional[Dict[str, Any]]:
        
        if cache_key and cache_ttl > 0:
            cached = self._cache_get(cache_key)
            if cached is not None:
                return cached
                
        token = _get_token()
        if not token:
            return None
            
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        }
        
        client = _get_client()
        url = f"{BASE_URL}{endpoint}"
        
        try:
            async with _request_semaphore:
                if method.upper() == "GET":
                    resp = await client.get(url, headers=headers, params=params)
                else:
                    resp = await client.request(method, url, headers=headers, params=params)
                    
                if resp.status_code == 429:
                    logger.warning("upstox_rate_limited", endpoint=endpoint)
                    self._circuit.record_failure()
                    return None
                    
                if resp.status_code != 200:
                    logger.warning("upstox_api_error", endpoint=endpoint, status=resp.status_code)
                    return None
                    
                data = resp.json()
                
                if cache_key and cache_ttl > 0:
                    self._cache_set(cache_key, data, cache_ttl)
                    
                return data
        except httpx.HTTPError as e:
            logger.error("upstox_http_error", endpoint=endpoint, error=str(e))
            return None
        except Exception as e:
            logger.error("upstox_request_error", endpoint=endpoint, error=str(e))
            return None

    async def get_quote(self, symbol: str) -> Optional[Dict[str, Any]]:
        async def _fetch():
            key = await self._get_instrument_key(symbol)
            if not key:
                return None
                
            data = await self._throttled_request(
                "GET",
                "/v3/market-quote/ltp",
                params={"instrument_key": key},
                cache_key=f"upstox:quote:{symbol}",
                cache_ttl=_CACHE_TTL_QUOTE,
            )
            
            if not data or "data" not in data:
                return None
                
            quote_data = None
            for k, v in data["data"].items():
                if isinstance(v, dict) and v.get("instrument_token") == key:
                    quote_data = v
                    break
                    
            if not quote_data:
                # Fallback: try first value in data dict
                quote_data = next(iter(data["data"].values()), None)
                
            if not quote_data or not isinstance(quote_data, dict):
                return None
                
            last_price = quote_data.get("last_price", 0.0)
            # In LTP endpoint, previous close is 'cp' (closing price)
            prev_close = quote_data.get("cp", quote_data.get("previous_close", last_price))
            volume = quote_data.get("volume", 0)
            
            if not last_price:
                return None
            
            change = round(last_price - prev_close, 2) if prev_close else 0.0
            change_percent = round((change / prev_close) * 100, 2) if prev_close else 0.0
            
            return {
                "symbol": symbol,
                "name": symbol,
                "price": last_price,
                "change": change,
                "change_percent": change_percent,
                "volume": volume,
                "high": quote_data.get("high", last_price),
                "low": quote_data.get("low", last_price),
                "open": quote_data.get("open", prev_close),
                "previous_close": prev_close,
                "market_cap": None,
                "pe_ratio": None,
                "timestamp": datetime.now(timezone.utc),
                "exchange": "BSE" if symbol.endswith(".BO") else "NSE",
                "market": "india",
                "currency": "INR",
            }

        return await self.execute_with_resilience(_fetch)

    async def get_ohlcv(
        self, symbol: str, period: str = "1mo", interval: str = "1d"
    ) -> Optional[Dict[str, Any]]:
        async def _fetch():
            key = await self._get_instrument_key(symbol)
            if not key:
                return None
                
            # Map period to from/to dates using timedelta (no dateutil dependency)
            from datetime import timedelta

            to_date_dt = datetime.now(timezone.utc)
            period_map = {
                "1d": timedelta(days=1),
                "5d": timedelta(days=5),
                "1mo": timedelta(days=30),
                "3mo": timedelta(days=90),
                "6mo": timedelta(days=180),
                "1y": timedelta(days=365),
                "2y": timedelta(days=730),
                "max": timedelta(days=7300),
            }
            from_date_dt = to_date_dt - period_map.get(period, timedelta(days=30))

            to_date = to_date_dt.strftime("%Y-%m-%d")
            from_date = from_date_dt.strftime("%Y-%m-%d")

            # Map interval to Upstox V3 unit/interval params (API uses PLURAL units)
            interval_map = {
                "1d": ("days", "1"),
                "1wk": ("weeks", "1"),
                "1mo": ("months", "1"),
                "1h": ("hours", "1"),
                "5min": ("minutes", "5"),
                "15min": ("minutes", "15"),
                "30min": ("minutes", "30"),
            }
            unit, interval_str = interval_map.get(interval, ("days", "1"))
                
            endpoint = f"/v3/historical-candle/{key}/{unit}/{interval_str}/{to_date}/{from_date}"
            
            data = await self._throttled_request(
                "GET",
                endpoint,
                cache_key=f"upstox:ohlcv:{symbol}:{period}:{interval}",
                cache_ttl=_CACHE_TTL_OHLCV,
            )
            
            if not data or "data" not in data or "candles" not in data["data"]:
                return None
                
            candles = data["data"]["candles"]
            # Candles are in reverse chronological order, need to reverse
            candles = list(reversed(candles))
            
            bars = []
            for c in candles:
                try:
                    # c = [timestamp, open, high, low, close, volume, oi]
                    ts = c[0]
                    # Parse timestamp format (could be ISO format)
                    if isinstance(ts, str):
                        try:
                            # 2024-03-22T00:00:00+05:30
                            ts_dt = datetime.fromisoformat(ts)
                            ts_int = int(ts_dt.timestamp())
                        except ValueError:
                            ts_int = 0
                    else:
                        ts_int = int(ts)
                        
                    bars.append({
                        "time": ts_int,
                        "open": float(c[1]),
                        "high": float(c[2]),
                        "low": float(c[3]),
                        "close": float(c[4]),
                        "volume": int(c[5])
                    })
                except (IndexError, ValueError):
                    continue
                    
            return {"bars": bars}

        return await self.execute_with_resilience(_fetch)

    async def get_company_info(self, symbol: str) -> Optional[Dict[str, Any]]:
        async def _fetch():
            isin = await self._get_isin(symbol)
            if not isin:
                return None
                
            data = await self._throttled_request(
                "GET",
                f"/v2/fundamentals/{isin}/profile",
                cache_key=f"upstox:info:{symbol}",
                cache_ttl=_CACHE_TTL_FUNDAMENTALS,
            )
            
            if not data or "data" not in data:
                return None
                
            profile = data["data"]
            
            return {
                "symbol": symbol,
                "name": profile.get("company_name", symbol),
                "sector": profile.get("sector"),
                "industry": profile.get("industry"),
                "exchange": "BSE" if symbol.endswith(".BO") else "NSE",
                "market": "india",
                "description": profile.get("company_profile"),
                "website": None,
                "metrics": {},
            }
            
        return await self.execute_with_resilience(_fetch)

    async def get_fundamentals(self, symbol: str) -> Optional[Dict[str, Any]]:
        async def _fetch():
            isin = await self._get_isin(symbol)
            if not isin:
                return None
                
            data = await self._throttled_request(
                "GET",
                f"/v2/fundamentals/{isin}/key-ratios",
                cache_key=f"upstox:ratios:{symbol}",
                cache_ttl=_CACHE_TTL_FUNDAMENTALS,
            )
            
            if not data or "data" not in data:
                return None
                
            ratios = data["data"]
            # Upstox returns array like: [{"name": "P/E", "company_value": "24.15", "sector_value": "18.46"}, ...]
            ratio_map = {}
            if isinstance(ratios, list):
                for r in ratios:
                    name = (r.get("name") or "").strip()
                    val_str = r.get("company_value")
                    if name and val_str:
                        try:
                            # Strip % suffix if present
                            clean = str(val_str).replace("%", "").strip()
                            ratio_map[name] = float(clean)
                        except (ValueError, TypeError):
                            ratio_map[name] = val_str
            elif isinstance(ratios, dict):
                ratio_map = ratios
                
            return {
                "pe_ratio": ratio_map.get("P/E"),
                "pb_ratio": ratio_map.get("P/B"),
                "roe": ratio_map.get("ROE"),
                "roa": ratio_map.get("ROA"),
                "roce": ratio_map.get("ROCE"),
                "ev_ebitda": ratio_map.get("EV/EBITDA"),
                "debt_to_equity": ratio_map.get("Debt/Equity", ratio_map.get("D/E")),
                "dividend_yield": ratio_map.get("Dividend Yield"),
                "current_ratio": ratio_map.get("Current Ratio"),
            }
            
        return await self.execute_with_resilience(_fetch)

    async def get_financial_statements(self, symbol: str) -> Optional[Dict[str, Any]]:
        async def _fetch():
            isin = await self._get_isin(symbol)
            if not isin:
                return None
                
            async def fetch_stmt(stmt_type):
                return await self._throttled_request(
                    "GET",
                    f"/v2/fundamentals/{isin}/{stmt_type}",
                    cache_key=f"upstox:stmt:{stmt_type}:{symbol}",
                    cache_ttl=_CACHE_TTL_FUNDAMENTALS,
                )
                
            statements = await asyncio.gather(
                fetch_stmt("income-statement"),
                fetch_stmt("balance-sheet"),
                fetch_stmt("cash-flow")
            )
            
            return {
                "income_statement": statements[0].get("data") if statements[0] else None,
                "balance_sheet": statements[1].get("data") if statements[1] else None,
                "cash_flow": statements[2].get("data") if statements[2] else None,
            }
            
        return await self.execute_with_resilience(_fetch)

    async def get_news(self, symbol: str, count: int = 15) -> Optional[List[Dict[str, Any]]]:
        async def _fetch():
            key = await self._get_instrument_key(symbol)
            if not key:
                return None
                
            data = await self._throttled_request(
                "GET",
                "/v2/news",
                params={"category": "instrument_keys", "instrument_keys": key},
                cache_key=f"upstox:news:{symbol}",
                cache_ttl=_CACHE_TTL_NEWS,
            )
            
            if not data or "data" not in data:
                return None
                
            # Upstox returns news keyed by instrument_key: {"NSE_EQ|INE002A01018": [articles]}
            all_articles = []
            news_data = data["data"]
            if isinstance(news_data, dict):
                for _key, articles in news_data.items():
                    if isinstance(articles, list):
                        all_articles.extend(articles)
            elif isinstance(news_data, list):
                all_articles = news_data
                
            result = []
            for item in all_articles[:count]:
                # Timestamp is in epoch milliseconds
                ts_ms = item.get("timestamp", 0)
                ts = ts_ms / 1000.0 if ts_ms > 1e10 else ts_ms  # Handle both ms and seconds
                result.append({
                    "headline": item.get("headline", ""),
                    "summary": item.get("summary", ""),
                    "url": item.get("article_link", ""),
                    "source": "Upstox News",
                    "datetime": ts,
                    "image": item.get("thumbnail"),
                })
                
            return result
            
        return await self.execute_with_resilience(_fetch)

    async def search(self, query: str) -> List[Dict[str, Any]]:
        async def _fetch():
            await self._load_instruments()
            
            results = []
            q = query.upper()
            
            # Simple prefix search
            for symbol, key in self._symbol_to_key.items():
                if symbol.startswith(q) or q in symbol:
                    results.append({
                        "symbol": symbol,
                        "name": symbol,
                        "exchange": "BSE" if symbol.endswith(".BO") else "NSE",
                        "market": "india",
                    })
                    if len(results) >= 10:
                        break
                        
            return results
            
        res = await self.execute_with_resilience(_fetch)
        return res or []

    async def health_check(self) -> bool:
        try:
            quote = await self.get_quote("RELIANCE.NS")
            return quote is not None
        except Exception:
            return False

upstox_adapter = UpstoxAdapter()
