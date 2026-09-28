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
_CACHE_MAX_ENTRIES = 500

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
        self._symbol_to_isin: Dict[str, str] = {}
        self._loaded_exchanges: set[str] = set()
        self._instruments_last_load: Dict[str, float] = {}
        self._instruments_lock = asyncio.Lock()
        
        for sym, key in _STATIC_INDEX_MAP.items():
            self._symbol_to_key[sym] = key

    def _cache_get(self, key: str) -> Optional[Any]:
        if key in _cache:
            data, expiry = _cache[key]
            if time.time() < expiry:
                return data
            del _cache[key]
        return None

    def _cache_set(self, key: str, data: Any, ttl: int) -> None:
        now = time.time()
        if len(_cache) >= _CACHE_MAX_ENTRIES:
            # Purge expired items first
            expired = [k for k, (_, exp) in _cache.items() if now >= exp]
            for k in expired:
                _cache.pop(k, None)
            # If still over limit, drop oldest entries
            if len(_cache) >= _CACHE_MAX_ENTRIES:
                for k in list(_cache.keys())[: max(1, _CACHE_MAX_ENTRIES // 10)]:
                    _cache.pop(k, None)
        _cache[key] = (data, now + ttl)

    @staticmethod
    def _parse_instruments_gzip(content: bytes) -> List[dict]:
        data = gzip.decompress(content)
        return json.loads(data)

    async def _load_instruments(self, target_exchange: str = "NSE") -> None:
        now = time.time()
        if target_exchange in self._loaded_exchanges and (now - self._instruments_last_load.get(target_exchange, 0) < _CACHE_TTL_INSTRUMENTS):
            return

        async with self._instruments_lock:
            # Re-check after acquiring lock
            now = time.time()
            if target_exchange in self._loaded_exchanges and (now - self._instruments_last_load.get(target_exchange, 0) < _CACHE_TTL_INSTRUMENTS):
                return

            try:
                client = _get_client()
                url = f"https://assets.upstox.com/market-quote/instruments/exchange/{target_exchange}.json.gz"
                resp = await client.get(url)
                if resp.status_code == 200:
                    instruments = await asyncio.to_thread(self._parse_instruments_gzip, resp.content)
                    for inst in instruments:
                        symbol = inst.get("trading_symbol") or inst.get("tradingsymbol")
                        if not symbol:
                            continue
                        # Only process equity cash instruments (filter out derivatives/options/futures)
                        inst_type = inst.get("instrument_type", "")
                        if inst_type and inst_type not in ("EQ", ""):
                            continue
                        segment = inst.get("segment", "")
                        if segment and segment not in ("NSE_EQ", "BSE_EQ"):
                            continue

                        std_symbol = f"{symbol}.NS" if target_exchange == "NSE" else f"{symbol}.BO"
                        key = inst.get("instrument_key")
                        isin = inst.get("isin")

                        if key:
                            self._symbol_to_key[std_symbol] = key
                        if isin:
                            self._symbol_to_isin[std_symbol] = isin

                    self._loaded_exchanges.add(target_exchange)
                    self._instruments_last_load[target_exchange] = now
                    logger.info("upstox_exchange_loaded", exchange=target_exchange, symbols=len(instruments))
                else:
                    self._instruments_last_load[target_exchange] = now - _CACHE_TTL_INSTRUMENTS + 300
                    logger.warning("upstox_instrument_download_failed", exchange=target_exchange, status=resp.status_code)
            except Exception as e:
                self._instruments_last_load[target_exchange] = now - _CACHE_TTL_INSTRUMENTS + 300
                logger.error("upstox_instrument_load_failed", exchange=target_exchange, error=str(e))

    async def _get_instrument_key(self, symbol: str) -> Optional[str]:
        if symbol in _STATIC_INDEX_MAP:
            return _STATIC_INDEX_MAP[symbol]
        target_exchange = "BSE" if symbol.upper().endswith(".BO") else "NSE"
        await self._load_instruments(target_exchange)
        return self._symbol_to_key.get(symbol.upper())

    async def _get_isin(self, symbol: str) -> Optional[str]:
        target_exchange = "BSE" if symbol.upper().endswith(".BO") else "NSE"
        await self._load_instruments(target_exchange)
        return self._symbol_to_isin.get(symbol.upper())

    async def _throttled_request(
        self,
        method: str,
        endpoint: str,
        params: Optional[Dict[str, Any]] = None,
        cache_key: Optional[str] = None,
        cache_ttl: int = 0,
    ) -> Optional[Dict[str, Any]]:
        """
        Make a rate-limited request to Upstox API.
        
        IMPORTANT: This method RAISES exceptions on failures so that
        execute_with_resilience() can properly track failures in the
        circuit breaker. Catching errors here and returning None would
        make the circuit breaker think every failed call was a success.
        """
        if cache_key and cache_ttl > 0:
            cached = self._cache_get(cache_key)
            if cached is not None:
                return cached
                
        token = _get_token()
        if not token:
            raise RuntimeError("Upstox token not configured")
            
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        }
        
        client = _get_client()
        url = f"{BASE_URL}{endpoint}"
        
        async with _request_semaphore:
            if method.upper() == "GET":
                resp = await client.get(url, headers=headers, params=params)
            else:
                resp = await client.request(method, url, headers=headers, params=params)
                
            if resp.status_code == 429:
                logger.warning("upstox_rate_limited", endpoint=endpoint)
                raise RuntimeError(f"Upstox rate limited on {endpoint}")
                
            if resp.status_code != 200:
                logger.warning("upstox_api_error", endpoint=endpoint, status=resp.status_code)
                raise RuntimeError(f"Upstox API error {resp.status_code} on {endpoint}")
                
            data = resp.json()
            
            if cache_key and cache_ttl > 0:
                self._cache_set(cache_key, data, cache_ttl)
                
            return data

    async def get_quote(self, symbol: str) -> Optional[Dict[str, Any]]:
        async def _fetch():
            key = await self._get_instrument_key(symbol)
            if not key:
                return None
                
            # Use OHLC endpoint which provides genuine OHLC, last_price, and previous close
            data = await self._throttled_request(
                "GET",
                "/v3/market-quote/ohlc",
                params={"instrument_key": key, "interval": "1d"},
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
                
            last_price = self._safe_num(quote_data.get("last_price")) or 0.0
            ohlc = quote_data.get("ohlc", {})
            if isinstance(ohlc, dict):
                prev_close = self._safe_num(ohlc.get("close", quote_data.get("cp", quote_data.get("previous_close", last_price)))) or last_price
                high = self._safe_num(ohlc.get("high", quote_data.get("high")))
                low = self._safe_num(ohlc.get("low", quote_data.get("low")))
                open_price = self._safe_num(ohlc.get("open", quote_data.get("open")))
            else:
                prev_close = self._safe_num(quote_data.get("cp", quote_data.get("previous_close", last_price))) or last_price
                high = self._safe_num(quote_data.get("high"))
                low = self._safe_num(quote_data.get("low"))
                open_price = self._safe_num(quote_data.get("open"))
            
            volume = int(self._safe_num(quote_data.get("volume")) or 0)
            
            if not last_price:
                return None
            
            change = round(last_price - prev_close, 2) if prev_close else 0.0
            change_percent = round((change / prev_close) * 100, 2) if prev_close else 0.0
            
            return {
                "symbol": symbol,
                "name": symbol,
                "price": round(float(last_price), 2),
                "change": round(float(change), 2),
                "change_percent": round(float(change_percent), 2),
                "volume": volume,
                "high": round(float(high), 2) if high is not None else None,
                "low": round(float(low), 2) if low is not None else None,
                "open": round(float(open_price), 2) if open_price is not None else None,
                "previous_close": round(float(prev_close), 2) if prev_close is not None else None,
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

    def _parse_key_ratios(self, ratios_data: Any) -> Dict[str, Any]:
        """Parse Upstox key-ratios array/dict into canonical metrics dictionary."""
        if not ratios_data:
            return {}
        ratios = ratios_data.get("data", ratios_data) if isinstance(ratios_data, dict) else ratios_data
        ratio_map = {}
        if isinstance(ratios, list):
            for r in ratios:
                name = (r.get("name") or "").strip()
                val_str = r.get("company_value")
                if name and val_str is not None:
                    try:
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

            # Merge fundamentals into metrics so Risk & Research engines have key ratios
            metrics = {}
            try:
                ratios_data = await self._throttled_request(
                    "GET",
                    f"/v2/fundamentals/{isin}/key-ratios",
                    cache_key=f"upstox:ratios:{symbol}",
                    cache_ttl=_CACHE_TTL_FUNDAMENTALS,
                )
                if ratios_data:
                    metrics = self._parse_key_ratios(ratios_data)
            except Exception as e:
                logger.debug("upstox_metrics_enrich_skipped", symbol=symbol, error=str(e))
            
            roe_val = metrics.get("roe")
            roa_val = metrics.get("roa")
            div_val = metrics.get("dividend_yield")

            return {
                "symbol": symbol,
                "name": profile.get("company_name", symbol),
                "sector": profile.get("sector"),
                "industry": profile.get("industry"),
                "exchange": "BSE" if symbol.endswith(".BO") else "NSE",
                "market": "india",
                "description": profile.get("company_profile"),
                "website": None,
                "metrics": metrics,
                # Direct canonical fields for DocumentProcessor / RAG
                "trailingPE": metrics.get("pe_ratio"),
                "priceToBook": metrics.get("pb_ratio"),
                "returnOnEquity": (roe_val / 100.0) if isinstance(roe_val, (int, float)) else None,
                "returnOnAssets": (roa_val / 100.0) if isinstance(roa_val, (int, float)) else None,
                "debtToEquity": metrics.get("debt_to_equity"),
                "currentRatio": metrics.get("current_ratio"),
                "dividendYield": (div_val / 100.0) if isinstance(div_val, (int, float)) else None,
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
                
            return self._parse_key_ratios(data)
            
        return await self.execute_with_resilience(_fetch)

    @staticmethod
    def _safe_num(val: Any) -> Optional[float]:
        """Safely convert Upstox values (including formatted strings) to float."""
        if val is None or val == "":
            return None
        try:
            if isinstance(val, (int, float)):
                return float(val)
            clean = str(val).replace(",", "").replace("%", "").strip()
            return float(clean)
        except (ValueError, TypeError):
            return None

    def _parse_upstox_periods(self, raw_data: Any) -> List[Dict[str, Any]]:
        """
        Parse Upstox financial statement response into canonical list of periods:
        [{"period": "Mar 2025", "items": {"Total Revenue": 950000.0, ...}}, ...]
        Sorted in reverse-chronological order (most recent first).

        Upstox API structure:
        data:
          full_statement: [
            {"particular": "Total Revenue", "history": [{"period": "Mar 2025", "value": ...}, ...]}
          ]
          income_statement: [
            {"category": "revenue", "history": [{"period": "Mar 2025", "value": ...}, ...]}
          ]
          history: [
            {"period": "Mar 2025", "total_asset": 1200000.0, "total_liability": 500000.0}
          ]
        """
        if not raw_data or not isinstance(raw_data, dict):
            return []

        data = raw_data.get("data", raw_data)
        if not isinstance(data, dict):
            if isinstance(data, list):
                res = []
                for row in data:
                    if isinstance(row, dict):
                        period = str(row.get("period", row.get("year", "Unknown")))
                        items = {k: self._safe_num(v) for k, v in row.items() if k not in ("period", "year")}
                        res.append({"period": period, "items": items})
                return res
            return []

        # If data already has "annual" / "quarterly" list
        if "annual" in data or "quarterly" in data:
            return data.get("annual", []) or data.get("quarterly", [])

        periods_map: Dict[str, Dict[str, Optional[float]]] = {}

        # 1. Parse `full_statement` (Upstox primary documentation)
        full_statement = data.get("full_statement") or []
        if isinstance(full_statement, list):
            for row in full_statement:
                if not isinstance(row, dict):
                    continue
                particular = (row.get("particular") or row.get("category") or "").strip()
                if not particular:
                    continue
                history = row.get("history") or []
                if isinstance(history, list):
                    for entry in history:
                        if isinstance(entry, dict):
                            period = str(entry.get("period") or entry.get("year") or "").strip()
                            if period:
                                val = self._safe_num(entry.get("value"))
                                if period not in periods_map:
                                    periods_map[period] = {}
                                periods_map[period][particular] = val

        # 2. Parse summary `income_statement` or `history` (summary records)
        summary_records = data.get("income_statement") or data.get("history") or []
        if isinstance(summary_records, list):
            for row in summary_records:
                if not isinstance(row, dict):
                    continue
                # If row has "category" and "history" (e.g. category="revenue")
                cat = (row.get("category") or "").strip()
                hist = row.get("history")
                if cat and isinstance(hist, list):
                    for entry in hist:
                        if isinstance(entry, dict):
                            period = str(entry.get("period") or entry.get("year") or "").strip()
                            if period:
                                val = self._safe_num(entry.get("value"))
                                if period not in periods_map:
                                    periods_map[period] = {}
                                if cat not in periods_map[period]:
                                    periods_map[period][cat] = val
                # If row is a direct summary dict with "period" (e.g. balance sheet summary)
                period = str(row.get("period") or row.get("year") or "").strip()
                if period and not hist:
                    if period not in periods_map:
                        periods_map[period] = {}
                    for k, v in row.items():
                        if k not in ("period", "year", "time_period", "type"):
                            val = self._safe_num(v)
                            periods_map[period][k] = val
                            _name_map = {
                                "total_asset": "Total Assets",
                                "total_liability": "Total Liabilities Net Minority Interest",
                                "total_equity": "Total Stockholders Equity",
                                "revenue": "Total Revenue",
                                "net_profit": "Net Income",
                            }
                            if k in _name_map and _name_map[k] not in periods_map[period]:
                                periods_map[period][_name_map[k]] = val

        periods_list = [{"period": p, "items": items} for p, items in periods_map.items()]

        # Sort reverse-chronologically (latest periods first)
        def _sort_key(item):
            p = item["period"]
            import re
            m = re.search(r'\d{4}', p)
            return int(m.group(0)) if m else 0

        periods_list.sort(key=_sort_key, reverse=True)
        return periods_list

    def _normalize_statement(self, raw_data: Any) -> Dict[str, List[Dict[str, Any]]]:
        """
        Normalize a statement payload into {'annual': [...], 'quarterly': [...]}.
        Provides backward compatibility and single-statement normalization.
        """
        if not raw_data:
            return {"annual": [], "quarterly": []}
        time_period = ""
        if isinstance(raw_data, dict):
            data = raw_data.get("data", raw_data)
            if isinstance(data, dict):
                time_period = data.get("time_period", "")
        parsed = self._parse_upstox_periods(raw_data)
        if time_period == "quarterly":
            return {"annual": [], "quarterly": parsed}
        else:
            return {"annual": parsed, "quarterly": []}

    async def get_financial_statements(self, symbol: str) -> Optional[Dict[str, Any]]:
        async def _fetch():
            isin = await self._get_isin(symbol)
            if not isin:
                return None
                
            async def fetch_stmt(stmt_type: str, time_period: str = "yearly"):
                try:
                    return await self._throttled_request(
                        "GET",
                        f"/v2/fundamentals/{isin}/{stmt_type}",
                        params={"time_period": time_period},
                        cache_key=f"upstox:stmt:{stmt_type}:{time_period}:{symbol}",
                        cache_ttl=_CACHE_TTL_FUNDAMENTALS,
                    )
                except Exception as e:
                    logger.debug("upstox_stmt_fetch_error", stmt=stmt_type, time_period=time_period, error=str(e))
                    return None
                
            inc_yr, inc_qtr, bs_yr, bs_qtr, cf_yr, cf_qtr = await asyncio.gather(
                fetch_stmt("income-statement", "yearly"),
                fetch_stmt("income-statement", "quarterly"),
                fetch_stmt("balance-sheet", "yearly"),
                fetch_stmt("balance-sheet", "quarterly"),
                fetch_stmt("cash-flow", "yearly"),
                fetch_stmt("cash-flow", "quarterly"),
            )
            
            return {
                "income_statement": {
                    "annual": self._parse_upstox_periods(inc_yr),
                    "quarterly": self._parse_upstox_periods(inc_qtr),
                },
                "balance_sheet": {
                    "annual": self._parse_upstox_periods(bs_yr),
                    "quarterly": self._parse_upstox_periods(bs_qtr),
                },
                "cash_flow": {
                    "annual": self._parse_upstox_periods(cf_yr),
                    "quarterly": self._parse_upstox_periods(cf_qtr),
                },
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
                    # Canonical field names expected by DocumentProcessor / RAG
                    "title": item.get("heading", item.get("headline", "")),
                    "headline": item.get("heading", item.get("headline", "")),
                    "summary": item.get("summary", ""),
                    "description": item.get("summary", ""),
                    "link": item.get("article_link", ""),
                    "url": item.get("article_link", ""),
                    "publisher": "Upstox News",
                    "source": "Upstox News",
                    "providerPublishTime": ts,
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
