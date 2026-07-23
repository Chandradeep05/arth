from __future__ import annotations

import pandas as pd
from enum import Enum
from dataclasses import dataclass
from typing import Any, Optional
from typing import Any, Optional, List
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
}

def normalize_ohlcv(data: Any, source: str) -> pd.DataFrame | None:
    """
    Takes raw data from ANY provider and returns a standardized DataFrame 
    with columns: Open, High, Low, Close, Volume, sorted ascending by DatetimeIndex.
    """
    if not data:
        return None
        
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
            elif clow in ['datetime', 'date', 't', 'timestamp']: col_map[c] = 'Datetime'
            
        df = df.rename(columns=col_map)
        
        required = ['Open', 'High', 'Low', 'Close', 'Volume']
        if not all(col in df.columns for col in required):
            return None
            
        # Parse datetime if available
        if 'Datetime' in df.columns:
            df['Datetime'] = pd.to_datetime(df['Datetime'])
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
        from app.data.adapters.twelvedata import TwelveDataAdapter
        from app.data.adapters.nse import nse_adapter
        from app.data.adapters.finnhub import finnhub_adapter
        from app.data.adapters.fmp import fmp_adapter

        self._twelve = TwelveDataAdapter()
        self._nse = nse_adapter
        self._finnhub = finnhub_adapter
        self._fmp = fmp_adapter

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
            if capability in ["quote", "history"]:
                return ["nse", "twelvedata"]
            return ["twelvedata"]

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
                    raw = await self._finnhub._throttled_get("quote", {"symbol": symbol.split(".")[0]})
                    data = {"price": raw.get("c"), "change": raw.get("d"), "percent_change": raw.get("dp")} if raw else None
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
                else:
                    data = None

                df = normalize_ohlcv(data, provider)
                if df is not None and not df.empty:
                    return DataResult(df, DataStatus.SUCCESS, provider)
            except Exception as e:
                logger.warning("history_provider_failed", provider=provider, symbol=symbol, error=str(e))

        return DataResult(None, DataStatus.UNAVAILABLE_PROVIDER, chain[0] if chain else None, "No history available")

    async def get_company_info(self, symbol: str) -> DataResult:
        chain = self._get_chain(symbol, "company_info")
        for provider in chain:
            try:
                if provider == "finnhub":
                    data = await self._finnhub.get_company_info(symbol)
                elif provider == "twelvedata":
                    data = await self._twelve.get_company_info(symbol)
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
            except Exception as e:
                logger.warning("financials_provider_failed", provider=provider, symbol=symbol, error=str(e))

        return DataResult(None, DataStatus.UNSUPPORTED_CAPABILITY, chain[0] if chain else None, "Financial statements unavailable")

    async def get_holders(self, symbol: str) -> DataResult:
        return DataResult(None, DataStatus.UNSUPPORTED_CAPABILITY, None, "Holders data unsupported")

    def get_source_label(self, symbol: str) -> str:
        provider = self._get_provider(symbol)
        labels = {'twelvedata': 'Twelve Data', 'nse': 'NSE India', 'finnhub': 'Finnhub', 'fmp': 'Financial Modeling Prep'}
        return labels.get(provider, provider)

    def _get_provider(self, symbol: str) -> str:
        if symbol.upper().endswith(('.NS', '.BO')):
            return 'nse'
        return 'twelvedata'


market_data = MarketDataProvider()
