"""
Financial Modeling Prep (FMP) adapter — API key authenticated source for financial statements and ratios.

Free tier: 250 requests/day.
Endpoints used:
- /income-statement/            → get_income_statement
- /balance-sheet-statement/      → get_balance_sheet
- /cash-flow-statement/          → get_cash_flow
- /ratios/                       → get_ratios
- /profile/                      → get_company_profile
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Dict, List, Optional
import httpx

from app.core.logging import get_logger
from app.data.adapters.base import BaseDataAdapter

logger = get_logger(__name__)

_request_semaphore = asyncio.Semaphore(1)
_MIN_REQUEST_INTERVAL = 0.5
_last_request_time = [0.0]

_cache: Dict[str, tuple] = {}
_CACHE_TTL_STATEMENTS = 86400  # 24 hours
_CACHE_TTL_RATIOS = 86400      # 24 hours

_http_client: Optional[httpx.AsyncClient] = None

BASE_URL = "https://financialmodelingprep.com/api/v3"


def _get_client() -> httpx.AsyncClient:
    global _http_client
    if _http_client is None or _http_client.is_closed:
        _http_client = httpx.AsyncClient(timeout=15.0)
    return _http_client


def _get_api_key() -> str:
    from app.config import get_settings
    settings = get_settings()
    key = settings.fmp_api_key
    if not key or key == "YOUR_FMP_KEY":
        return ""
    return key


class FMPAdapter(BaseDataAdapter):
    """Adapter for Financial Modeling Prep REST API."""

    adapter_name = "fmp"

    def __init__(self):
        super().__init__()

    async def _throttled_get(self, endpoint: str, params: Optional[Dict[str, Any]] = None) -> Optional[Any]:
        api_key = _get_api_key()
        if not api_key:
            logger.warning("fmp_key_missing", endpoint=endpoint)
            return None

        if params is None:
            params = {}

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
            full_params = {**params, "apikey": api_key}

            try:
                resp = await client.get(f"{BASE_URL}/{endpoint}", params=full_params)
                if resp.status_code == 429:
                    logger.warning("fmp_rate_limited", endpoint=endpoint)
                    return None
                if resp.status_code != 200:
                    logger.warning("fmp_api_error", code=resp.status_code, endpoint=endpoint)
                    return None

                data = resp.json()
                _cache[cache_key] = (data, now + _CACHE_TTL_STATEMENTS)
                return data

            except Exception as e:
                logger.error("fmp_request_failed", endpoint=endpoint, error=str(e))
                return None

    @staticmethod
    def _normalize_periods(raw_records: list) -> list:
        """Convert raw FMP JSON records to canonical {period, items} format.

        FMP returns: [{"date": "2024-12-31", "revenue": 123, ...}, ...]
        StatementParser expects: [{"period": "2024-12-31", "items": {"Total Revenue": 123, ...}}, ...]
        """
        # FMP camelCase → canonical line-item names
        KEY_MAP = {
            # Income statement
            "revenue": "Total Revenue",
            "costOfRevenue": "Cost Of Revenue",
            "grossProfit": "Gross Profit",
            "operatingIncome": "Operating Income",
            "netIncome": "Net Income",
            "operatingExpenses": "Operating Expenses",
            "ebitda": "EBITDA",
            "eps": "Basic EPS",
            "epsdiluted": "Diluted EPS",
            "interestExpense": "Interest Expense",
            "incomeBeforeTax": "Income Before Tax",
            "incomeTaxExpense": "Tax Provision",
            "researchAndDevelopmentExpenses": "Research And Development",
            # Balance sheet
            "totalAssets": "Total Assets",
            "totalLiabilities": "Total Liabilities",
            "totalStockholdersEquity": "Total Stockholders Equity",
            "totalCurrentAssets": "Current Assets",
            "totalCurrentLiabilities": "Current Liabilities",
            "cashAndCashEquivalents": "Cash And Cash Equivalents",
            "totalDebt": "Total Debt",
            "netDebt": "Net Debt",
            "longTermDebt": "Long Term Debt",
            "shortTermDebt": "Short Term Debt",
            "inventory": "Inventory",
            "totalNonCurrentAssets": "Total Non Current Assets",
            "totalNonCurrentLiabilities": "Total Non Current Liabilities",
            # Cash flow
            "operatingCashFlow": "Operating Cash Flow",
            "capitalExpenditure": "Capital Expenditure",
            "freeCashFlow": "Free Cash Flow",
            "dividendsPaid": "Dividends Paid",
            "netCashUsedForInvestingActivites": "Cash From Investing",
            "netCashUsedProvidedByFinancingActivities": "Cash From Financing",
            "netChangeInCash": "Net Change In Cash",
        }

        periods = []
        for record in (raw_records or []):
            period_date = record.get("date", record.get("fiscalDateEnding", "unknown"))
            items = {}
            for fmp_key, canonical_name in KEY_MAP.items():
                val = record.get(fmp_key)
                if val is not None:
                    try:
                        items[canonical_name] = float(val)
                    except (ValueError, TypeError):
                        items[canonical_name] = None
            periods.append({"period": period_date, "items": items})
        return periods

    async def get_financial_statements(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Fetch income statement, balance sheet, and cash flow for symbol."""
        clean_symbol = symbol.split(".")[0].upper()

        inc = await self._throttled_get(f"income-statement/{clean_symbol}", {"limit": 4})
        bal = await self._throttled_get(f"balance-sheet-statement/{clean_symbol}", {"limit": 4})
        cf = await self._throttled_get(f"cash-flow-statement/{clean_symbol}", {"limit": 4})

        if not inc and not bal and not cf:
            return None

        return {
            "symbol": symbol.upper(),
            "income_statement": {"annual": self._normalize_periods(inc)},
            "balance_sheet": {"annual": self._normalize_periods(bal)},
            "cash_flow": {"annual": self._normalize_periods(cf)},
        }

    async def get_ratios(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Fetch financial ratios for symbol."""
        clean_symbol = symbol.split(".")[0].upper()
        raw = await self._throttled_get(f"ratios/{clean_symbol}", {"limit": 1})
        if not raw or not isinstance(raw, list) or len(raw) == 0:
            return None
        return raw[0]


    async def get_quote(self, symbol: str) -> Optional[Dict[str, Any]]:
        return None

    async def get_ohlcv(self, symbol: str, period: str = "1mo", interval: str = "1d") -> Optional[List[Dict[str, Any]]]:
        return None

    async def get_company_info(self, symbol: str) -> Optional[Dict[str, Any]]:
        clean_symbol = symbol.split(".")[0].upper()
        raw = await self._throttled_get(f"profile/{clean_symbol}")
        if not raw or not isinstance(raw, list) or len(raw) == 0:
            return None
        item = raw[0]
        return {
            "symbol": symbol.upper(),
            "name": item.get("companyName", ""),
            "exchange": item.get("exchangeShortName", ""),
            "industry": item.get("industry", ""),
            "market_cap": item.get("mktCap"),
            "description": item.get("description", ""),
        }

    async def search(self, query: str) -> List[Dict[str, Any]]:
        return []

    async def health_check(self) -> bool:
        return _get_api_key() != ""


fmp_adapter = FMPAdapter()
