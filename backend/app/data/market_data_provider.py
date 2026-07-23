from __future__ import annotations

import pandas as pd
from enum import Enum
from dataclasses import dataclass
from typing import Any, Optional
from app.core.logging import get_logger

logger = get_logger(__name__)

class DataStatus(Enum):
    SUCCESS = "SUCCESS"
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
        "fundamentals": "partial",  # free tier missing market_cap, PE
        "news": False,
        "holders": False,
    },
    "nse": {
        "quote": True,
        "history": True,
        "company_info": "partial",
        "fundamentals": "partial",
        "news": False,
        "holders": False,
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
        # Handle dictionary with 'bars' key or direct list
        if isinstance(data, dict) and 'bars' in data:
            bars = data['bars']
        elif isinstance(data, list):
            bars = data
        else:
            return None
            
        if not bars:
            return None
            
        df = pd.DataFrame(bars)
        
        # Standardize column names
        col_map = {}
        for col in df.columns:
            col_lower = col.lower()
            if col_lower in ['datetime', 'date', 'timestamp']:
                col_map[col] = 'Datetime'
            elif col_lower == 'open':
                col_map[col] = 'Open'
            elif col_lower == 'high':
                col_map[col] = 'High'
            elif col_lower == 'low':
                col_map[col] = 'Low'
            elif col_lower == 'close':
                col_map[col] = 'Close'
            elif col_lower == 'volume':
                col_map[col] = 'Volume'
                
        df = df.rename(columns=col_map)
        
        # Set DatetimeIndex
        if 'Datetime' in df.columns:
            df['Datetime'] = pd.to_datetime(df['Datetime'])
            df = df.set_index('Datetime')
        elif 'Date' in df.columns:
            df['Date'] = pd.to_datetime(df['Date'])
            df = df.set_index('Date')
            
        # Ensure all required columns exist
        required_cols = ['Open', 'High', 'Low', 'Close', 'Volume']
        for col in required_cols:
            if col not in df.columns:
                df[col] = 0.0 if col == 'Volume' else None
                
        df = df[required_cols]
        
        # Convert numeric columns
        for col in required_cols:
            df[col] = pd.to_numeric(df[col], errors='coerce')
            
        df = df.sort_index(ascending=True)
        return df
        
    except Exception as e:
        logger.error("Error normalizing OHLCV data", error=str(e), source=source)
        return None

class MarketDataProvider:
    def __init__(self, hybrid_adapter=None):
        # Import here to avoid circular imports
        from app.data.adapters.yahoo import yahoo_adapter
        self._adapter = hybrid_adapter or yahoo_adapter
    
    def _get_provider(self, symbol: str) -> str:
        """Determine which provider handles this symbol."""
        if symbol.upper().endswith(('.NS', '.BO')):
            return 'nse'
        return 'twelvedata'
    
    def _check_capability(self, symbol: str, capability: str) -> DataResult | None:
        """Return a DataResult error if the provider doesn't support this capability."""
        provider = self._get_provider(symbol)
        cap = CAPABILITIES.get(provider, {}).get(capability)
        if cap is False:
            return DataResult(
                data=None,
                status=DataStatus.UNSUPPORTED_CAPABILITY,
                source=provider,
                reason=f"{provider} does not support {capability}",
            )
        return None  # capability is supported (True or 'partial')
    
    async def get_quote(self, symbol: str) -> DataResult:
        provider = self._get_provider(symbol)
        cap_check = self._check_capability(symbol, "quote")
        if cap_check:
            return cap_check
            
        try:
            data = await self._adapter.get_quote(symbol)
            if data is None:
                return DataResult(None, DataStatus.UNAVAILABLE_PROVIDER, provider, "No quote data returned")
            return DataResult(data, DataStatus.SUCCESS, provider)
        except Exception as e:
            error_str = str(e)
            if '429' in error_str or 'rate limit' in error_str.lower():
                return DataResult(None, DataStatus.RATE_LIMITED, provider, error_str)
            return DataResult(None, DataStatus.TEMPORARY_ERROR, provider, error_str)
    
    async def get_history(self, symbol: str, period: str = '1y', interval: str = '1d') -> DataResult:
        provider = self._get_provider(symbol)
        cap_check = self._check_capability(symbol, "history")
        if cap_check:
            return cap_check
            
        try:
            data = await self._adapter.get_ohlcv(symbol, period=period, interval=interval)
            df = normalize_ohlcv(data, provider)
            if df is None or df.empty:
                return DataResult(None, DataStatus.UNAVAILABLE_PROVIDER, provider, "No history data returned or empty")
            return DataResult(df, DataStatus.SUCCESS, provider)
        except Exception as e:
            error_str = str(e)
            if '429' in error_str or 'rate limit' in error_str.lower():
                return DataResult(None, DataStatus.RATE_LIMITED, provider, error_str)
            return DataResult(None, DataStatus.TEMPORARY_ERROR, provider, error_str)
    
    async def get_company_info(self, symbol: str) -> DataResult:
        provider = self._get_provider(symbol)
        cap_check = self._check_capability(symbol, "company_info")
        if cap_check:
            return cap_check
            
        try:
            data = await self._adapter.get_company_info(symbol)
            if data is None:
                return DataResult(None, DataStatus.UNAVAILABLE_PROVIDER, provider, "No company info returned")
            return DataResult(data, DataStatus.SUCCESS, provider)
        except Exception as e:
            error_str = str(e)
            if '429' in error_str or 'rate limit' in error_str.lower():
                return DataResult(None, DataStatus.RATE_LIMITED, provider, error_str)
            return DataResult(None, DataStatus.TEMPORARY_ERROR, provider, error_str)
    
    async def get_fundamentals(self, symbol: str) -> DataResult:
        provider = self._get_provider(symbol)
        cap_check = self._check_capability(symbol, "fundamentals")
        if cap_check:
            return cap_check
            
        try:
            data = await self._adapter.get_company_info(symbol)
            if data is None:
                return DataResult(None, DataStatus.UNAVAILABLE_PROVIDER, provider, "No fundamental data returned")
            metrics = data.get('metrics', {}) if isinstance(data, dict) else {}
            return DataResult(metrics, DataStatus.SUCCESS, provider)
        except Exception as e:
            error_str = str(e)
            if '429' in error_str or 'rate limit' in error_str.lower():
                return DataResult(None, DataStatus.RATE_LIMITED, provider, error_str)
            return DataResult(None, DataStatus.TEMPORARY_ERROR, provider, error_str)
    
    async def get_news(self, symbol: str, count: int = 15) -> DataResult:
        provider = self._get_provider(symbol)
        cap_check = self._check_capability(symbol, "news")
        if cap_check:
            return cap_check
            
        return DataResult([], DataStatus.UNSUPPORTED_CAPABILITY, provider, f"{provider} does not support news")
    
    async def get_holders(self, symbol: str) -> DataResult:
        provider = self._get_provider(symbol)
        cap_check = self._check_capability(symbol, "holders")
        if cap_check:
            return cap_check
            
        return DataResult(None, DataStatus.UNSUPPORTED_CAPABILITY, provider, f"{provider} does not support holders")
    
    def get_source_label(self, symbol: str) -> str:
        """Return human-readable source label for this symbol's provider."""
        provider = self._get_provider(symbol)
        labels = {'twelvedata': 'Twelve Data', 'nse': 'NSE India'}
        return labels.get(provider, provider)

market_data = MarketDataProvider()
