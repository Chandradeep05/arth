from __future__ import annotations

import pandas as pd
from datetime import datetime, timezone
from enum import Enum
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Union
from app.core.logging import get_logger

logger = get_logger(__name__)

class DataStatus(Enum):
    SUCCESS = "SUCCESS"
    EMPTY_DATA = "EMPTY_DATA"
    UNAVAILABLE_PROVIDER = "UNAVAILABLE_PROVIDER"
    UNSUPPORTED_CAPABILITY = "UNSUPPORTED_CAPABILITY"
    SYMBOL_NOT_FOUND = "SYMBOL_NOT_FOUND"
    RATE_LIMITED = "RATE_LIMITED"
    TEMPORARY_ERROR = "TEMPORARY_ERROR"

@dataclass
class DataResult:
    data: Any | None
    status: DataStatus
    source: str | None = None
    reason: str | None = None

    @property
    def available(self) -> bool:
        return self.status == DataStatus.SUCCESS and self.data is not None

CAPABILITIES = {
    "twelvedata": {
        "quote": True,
        "history": True,
        "company_info": True,
        "fundamentals": "partial",
        "news": False,
        "holders": False,
        "financials": False,
    },
    "nse": {
        "quote": True,
        "history": True,
        "company_info": "partial",
        "fundamentals": "partial",
        "news": False,
        "holders": False,
        "financials": False,
    },
    "finnhub": {
        "quote": True,
        "history": False,
        "company_info": True,
        "fundamentals": True,
        "news": True,
        "holders": False,
        "financials": False,
    },
    "fmp": {
        "quote": False,
        "history": False,
        "company_info": False,
        "fundamentals": True,
        "news": False,
        "holders": False,
        "financials": True,
    },
    "upstox": {
        "quote": True,
        "history": True,
        "company_info": True,
        "fundamentals": True,
        "news": True,
        "holders": False,
        "financials": True,
    },
}

def normalize_ohlcv(data: Any, source: str) -> pd.DataFrame | None:
    """
    Takes raw data from ANY provider and returns a standardized DataFrame 
    with columns: Open, High, Low, Close, Volume, sorted ascending by DatetimeIndex.
    """
    if data is None:
        return None
    if isinstance(data, pd.DataFrame):
        if data.empty:
            return None
        return data  # Already a DataFrame, return as-is
        
    try:
        if isinstance(data, dict) and 'bars' in data:
            bars = data['bars']
        elif isinstance(data, list):
            bars = data
        else:
            return None
            
        if not bars:
            return None
            
        df = pd.DataFrame(bars)
        
        # Standardize column names (map lowercase or variation to TitleCase)
        col_map = {}
        for c in df.columns:
            clow = str(c).lower()
            if clow in ['open', 'o']: col_map[c] = 'Open'
            elif clow in ['high', 'h']: col_map[c] = 'High'
            elif clow in ['low', 'l']: col_map[c] = 'Low'
            elif clow in ['close', 'c']: col_map[c] = 'Close'
            elif clow in ['volume', 'v', 'vol']: col_map[c] = 'Volume'
            elif clow in ['datetime', 'date', 't', 'timestamp', 'time']: col_map[c] = 'Datetime'
            
        df = df.rename(columns=col_map)
        
        required = ['Open', 'High', 'Low', 'Close', 'Volume']
        if not all(col in df.columns for col in required):
            return None
            
        # Parse datetime if available
        if 'Datetime' in df.columns:
            import numpy as np
            valid_dt = df['Datetime'].dropna()
            sample = valid_dt.iloc[0] if not valid_dt.empty else None
            if isinstance(sample, (int, float, np.integer, np.floating)):
                unit = 'ms' if sample > 1e11 else 's'
                df['Datetime'] = pd.to_datetime(df['Datetime'], unit=unit, utc=True)
            else:
                df['Datetime'] = pd.to_datetime(df['Datetime'], utc=True)
            df = df.set_index('Datetime')
            
        # Sort ascending
        df = df.sort_index(ascending=True)
        
        # Select only required columns
        df = df[required]

        # Numeric conversions
        for col in required:
            df[col] = pd.to_numeric(df[col], errors='coerce')

        return df.dropna(subset=['Close'])
    except Exception as e:
        logger.error("ohlcv_normalization_failed", source=source, error=str(e))
        return None


class MarketDataProvider:
    """Unified interface for market data."""

    def __init__(self):
        from app.data.adapters.twelvedata import twelvedata_adapter
        from app.data.adapters.nse import nse_adapter
        from app.data.adapters.finnhub import finnhub_adapter
        from app.data.adapters.fmp import fmp_adapter

        self._twelve = twelvedata_adapter  # Use singleton — not a new instance
        self._nse = nse_adapter
        self._finnhub = finnhub_adapter
        self._fmp = fmp_adapter
        
        try:
            from app.config import get_settings
            if get_settings().upstox_enabled:
                from app.data.adapters.upstox import upstox_adapter
                self._upstox = upstox_adapter
            else:
                self._upstox = None
        except Exception:
            self._upstox = None

    def _get_upstox(self):
        if self._upstox is None:
            try:
                from app.config import get_settings
                if get_settings().upstox_enabled:
                    from app.data.adapters.upstox import upstox_adapter
                    self._upstox = upstox_adapter
            except Exception:
                self._upstox = None
        return self._upstox

    def _check_capability(self, symbol: str, capability: str) -> DataResult | None:
        provider = self._get_provider(symbol)
        cap = CAPABILITIES.get(provider, {}).get(capability, False)
        if not cap:
            return DataResult(
                data=None,
                status=DataStatus.UNSUPPORTED_CAPABILITY,
                source=provider,
                reason=f"{provider} does not support {capability}",
            )
        return None

    def _get_chain(self, symbol: str, capability: str) -> List[str]:
        is_indian = symbol.upper().endswith(('.NS', '.BO'))
        if is_indian:
            chain = []
            upstox = self._get_upstox()
            # Upstox is primary if enabled and has capability
            if upstox and CAPABILITIES.get("upstox", {}).get(capability):
                chain.append("upstox")
            # NSE as fallback for quote/history
            if capability in ["quote", "history"]:
                chain.append("nse")
            return chain

        # US Stocks provider chain
        chains = {
            "quote": ["twelvedata", "finnhub"],
            "history": ["twelvedata"],
            "company_info": ["finnhub", "twelvedata"],
            "fundamentals": ["finnhub", "fmp", "twelvedata"],
            "news": ["finnhub"],
            "financials": ["fmp"],
            "holders": [],
        }
        return chains.get(capability, ["twelvedata"])

    async def get_quote(self, symbol: str) -> DataResult:
        chain = self._get_chain(symbol, "quote")
        for provider in chain:
            try:
                if provider == "twelvedata":
                    data = await self._twelve.get_quote(symbol)
                elif provider == "nse":
                    data = await self._nse.get_quote(symbol)
                elif provider == "finnhub":
                    clean_sym = symbol.split(".")[0]
                    raw = await self._finnhub._throttled_get("quote", {"symbol": clean_sym})
                    if raw and raw.get("c"):
                        data = {
                            "symbol": symbol,
                            "price": raw.get("c"),
                            "change": raw.get("d"),
                            "percent_change": raw.get("dp"),
                            "change_percent": raw.get("dp"),
                            "open": raw.get("o"),
                            "high": raw.get("h"),
                            "low": raw.get("l"),
                            "previous_close": raw.get("pc"),
                            "volume": None,
                            "market_cap": None,
                            "pe_ratio": None,
                            "timestamp": datetime.now(timezone.utc),
                            "exchange": "US",
                            "market": "us",
                            "currency": "USD",
                        }
                    else:
                        data = None
                elif provider == "upstox":
                    upstox = self._get_upstox()
                    data = await upstox.get_quote(symbol) if upstox else None
                else:
                    data = None

                if data:
                    return DataResult(data, DataStatus.SUCCESS, provider)
            except Exception as e:
                logger.warning("quote_provider_failed", provider=provider, symbol=symbol, error=str(e))

        return DataResult(None, DataStatus.UNAVAILABLE_PROVIDER, chain[0] if chain else None, "No quote available")

    async def get_history(self, symbol: str, period: str = '1y', interval: str = '1d') -> DataResult:
        chain = self._get_chain(symbol, "history")
        for provider in chain:
            try:
                if provider == "twelvedata":
                    data = await self._twelve.get_ohlcv(symbol, period=period, interval=interval)
                elif provider == "nse":
                    data = await self._nse.get_ohlcv(symbol, period=period)
                elif provider == "upstox":
                    upstox = self._get_upstox()
                    data = await upstox.get_ohlcv(symbol, period=period, interval=interval) if upstox else None
                else:
                    data = None

                df = normalize_ohlcv(data, provider)
                if df is not None and not df.empty:
                    return DataResult(df, DataStatus.SUCCESS, provider)
            except Exception as e:
                logger.warning("history_provider_failed", provider=provider, symbol=symbol, error=str(e))

        return DataResult(None, DataStatus.UNAVAILABLE_PROVIDER, chain[0] if chain else None, "No history available")

    async def get_ohlcv(self, symbol: str, period: str = '1y', interval: str = '1d') -> DataResult:
        """Alias for get_history to match adapter interface conventions."""
        return await self.get_history(symbol, period=period, interval=interval)

    async def get_company_info(self, symbol: str) -> DataResult:
        chain = self._get_chain(symbol, "company_info")
        for provider in chain:
            try:
                if provider == "finnhub":
                    data = await self._finnhub.get_company_info(symbol)
                elif provider == "twelvedata":
                    data = await self._twelve.get_company_info(symbol)
                elif provider == "upstox":
                    upstox = self._get_upstox()
                    data = await upstox.get_company_info(symbol) if upstox else None
                else:
                    data = None

                if data:
                    return DataResult(data, DataStatus.SUCCESS, provider)
            except Exception as e:
                logger.warning("company_info_failed", provider=provider, symbol=symbol, error=str(e))

        return DataResult(None, DataStatus.UNAVAILABLE_PROVIDER, chain[0] if chain else None, "No company info available")

    async def get_fundamentals(self, symbol: str) -> DataResult:
        chain = self._get_chain(symbol, "fundamentals")
        for provider in chain:
            try:
                if provider == "finnhub":
                    data = await self._finnhub.get_fundamentals(symbol)
                elif provider == "fmp":
                    data = await self._fmp.get_ratios(symbol)
                elif provider == "twelvedata":
                    raw = await self._twelve.get_company_info(symbol)
                    data = raw.get('metrics', {}) if isinstance(raw, dict) else {}
                elif provider == "upstox":
                    upstox = self._get_upstox()
                    data = await upstox.get_fundamentals(symbol) if upstox else None
                else:
                    data = None

                if data:
                    return DataResult(data, DataStatus.SUCCESS, provider)
            except Exception as e:
                logger.warning("fundamentals_failed", provider=provider, symbol=symbol, error=str(e))

        return DataResult(None, DataStatus.UNAVAILABLE_PROVIDER, chain[0] if chain else None, "No fundamentals available")

    async def get_news(self, symbol: str, count: int = 15) -> DataResult:
        chain = self._get_chain(symbol, "news")
        for provider in chain:
            try:
                if provider == "finnhub":
                    articles = await self._finnhub.get_news(symbol, count)
                    if articles:
                        return DataResult(articles, DataStatus.SUCCESS, provider)
                elif provider == "upstox":
                    upstox = self._get_upstox()
                    articles = await upstox.get_news(symbol, count) if upstox else None
                    if articles:
                        return DataResult(articles, DataStatus.SUCCESS, provider)
            except Exception as e:
                logger.warning("news_provider_failed", provider=provider, symbol=symbol, error=str(e))

        return DataResult([], DataStatus.UNSUPPORTED_CAPABILITY, chain[0] if chain else None, "News unsupported or empty")

    async def get_financial_statements(self, symbol: str) -> DataResult:
        chain = self._get_chain(symbol, "financials")
        for provider in chain:
            try:
                if provider == "fmp":
                    data = await self._fmp.get_financial_statements(symbol)
                    if data:
                        return DataResult(data, DataStatus.SUCCESS, provider)
                elif provider == "upstox":
                    upstox = self._get_upstox()
                    data = await upstox.get_financial_statements(symbol) if upstox else None
                    if data:
                        return DataResult(data, DataStatus.SUCCESS, provider)
            except Exception as e:
                logger.warning("financials_provider_failed", provider=provider, symbol=symbol, error=str(e))

        return DataResult(None, DataStatus.UNSUPPORTED_CAPABILITY, chain[0] if chain else None, "Financial statements unavailable")

    async def get_holders(self, symbol: str) -> DataResult:
        return DataResult(None, DataStatus.UNSUPPORTED_CAPABILITY, None, "Holders data unsupported")

    async def search(self, query: str) -> List[Dict[str, Any]]:
        """Search across providers. Upstox/NSE for Indian names, TwelveData for US."""
        results = []
        upstox = self._get_upstox()
        if upstox:
            try:
                upstox_results = await upstox.search(query)
                if upstox_results:
                    results.extend(upstox_results)
            except Exception as e:
                logger.warning("market_data_upstox_search_failed", error=str(e))
        if not results and self._nse:
            try:
                nse_results = await self._nse.search(query)
                if nse_results:
                    results.extend(nse_results)
            except Exception as e:
                logger.warning("market_data_nse_search_failed", error=str(e))
        if self._twelve:
            try:
                td_results = await self._twelve.search(query)
                if td_results:
                    results.extend(td_results)
            except Exception as e:
                logger.warning("market_data_twelvedata_search_failed", error=str(e))
        return results

    async def get_market_indices(self) -> List[Dict[str, Any]]:
        """Combine US indices (TwelveData) + Indian indices (Upstox/NSE)."""
        results = []
        if self._twelve:
            try:
                td_indices = await self._twelve.get_market_indices()
                if td_indices:
                    results.extend(td_indices)
            except Exception as e:
                logger.warning("market_data_twelve_indices_failed", error=str(e))

        indian_indices = []
        upstox = self._get_upstox()
        if upstox:
            try:
                for idx_sym, idx_name in [("^NSEI", "NIFTY 50"), ("^BSESN", "SENSEX")]:
                    q = await upstox.get_quote(idx_sym)
                    if q and q.get("price"):
                        p = round(float(q.get("price", 0)), 2)
                        indian_indices.append({
                            "symbol": idx_sym,
                            "name": idx_name,
                            "value": p,
                            "price": p,
                            "change": round(float(q.get("change", 0)), 2),
                            "change_percent": round(float(q.get("change_percent", 0)), 2),
                            "timestamp": q.get("timestamp"),
                        })
            except Exception as e:
                logger.warning("market_data_upstox_indices_failed", error=str(e))

        if not indian_indices and self._nse:
            try:
                nse_indices = await self._nse.get_market_indices()
                if nse_indices:
                    indian_indices.extend(nse_indices)
            except Exception as e:
                logger.warning("market_data_nse_indices_failed", error=str(e))

        results.extend(indian_indices)
        return results

    async def get_batch_quotes(self, symbols: List[str]) -> List[Dict[str, Any]]:
        """Batch quotes — route Indian symbols to Upstox/NSE, US to TwelveData."""
        results = []
        us_symbols = [s for s in symbols if not s.upper().endswith(('.NS', '.BO'))]
        indian_symbols = [s for s in symbols if s.upper().endswith(('.NS', '.BO'))]

        if us_symbols and self._twelve:
            try:
                td_results = await self._twelve.get_batch_quotes(us_symbols)
                if td_results:
                    results.extend(td_results)
            except Exception as e:
                logger.warning("market_data_batch_us_failed", error=str(e))

        upstox = self._get_upstox()
        for sym in indian_symbols:
            quote = None
            if upstox:
                try:
                    quote = await upstox.get_quote(sym)
                except Exception:
                    quote = None
            if not quote and self._nse:
                try:
                    quote = await self._nse.get_quote(sym)
                except Exception:
                    quote = None
            if quote:
                results.append(quote)

        return results

    def get_health(self) -> Dict[str, Any]:
        """Aggregate health statuses across configured adapters."""
        health = {}
        upstox = self._get_upstox()
        for name, adapter in [
            ("upstox", upstox),
            ("twelvedata", self._twelve),
            ("nse", self._nse),
            ("finnhub", self._finnhub),
            ("fmp", self._fmp),
        ]:
            if adapter and hasattr(adapter, "get_health"):
                try:
                    h = adapter.get_health()
                    health[name] = h.__dict__ if hasattr(h, "__dict__") else h
                except Exception:
                    health[name] = {"is_healthy": False}
        return health

    @property
    def is_healthy(self) -> bool:
        health = self.get_health()
        return any(
            v.get("is_healthy", False) if isinstance(v, dict) else getattr(v, "is_healthy", False)
            for v in health.values()
        ) if health else False

    def get_source_label(self, symbol: str, provider: Optional[str] = None) -> str:
        prov = provider or self._get_provider(symbol)
        labels = {
            'twelvedata': 'Twelve Data',
            'nse': 'NSE India',
            'finnhub': 'Finnhub',
            'fmp': 'Financial Modeling Prep',
            'upstox': 'Upstox',
        }
        return labels.get(prov, prov)

    def _get_provider(self, symbol: str) -> str:
        if symbol.upper().endswith(('.NS', '.BO')):
            return 'upstox' if self._get_upstox() else 'nse'
        return 'twelvedata'


market_data = MarketDataProvider()
