"""
Symbol normalization and market classification module.

Single authoritative source of truth for:
- Canonicalizing user-provided ticker symbols across ARTH
- Distinguishing Indian (NSE/BSE) equities and indices from US equities
- Determining display currency ($ vs ₹)
"""
from __future__ import annotations

from typing import Set

COMMON_INDIAN_SYMBOLS: Set[str] = {
    "ADANIENT", "ADANIPORTS", "APOLLOHOSP", "ASIANPAINT", "AXISBANK",
    "BAJAJ-AUTO", "BAJAJFINSV", "BAJFINANCE", "BANKNIFTY", "BEL",
    "BHARTIARTL", "BPCL", "BRITANNIA", "CIPLA", "COALINDIA",
    "DIVISLAB", "DRREDDY", "EICHERMOT", "ETERNAL", "GRASIM",
    "HAL", "HCLTECH", "HDFCBANK", "HDFCLIFE", "HEROMOTOCO",
    "HINDALCO", "HINDUNILVR", "ICICIBANK", "INDUSINDBK", "INFY",
    "ITC", "JIOFIN", "JSWSTEEL", "KOTAKBANK", "LT",
    "M&M", "MARUTI", "NESTLEIND", "NIFTY", "NTPC",
    "ONGC", "PAYTM", "POWERGRID", "RELIANCE", "SBILIFE",
    "SBIN", "SHRIRAMFIN", "SUNPHARMA", "TATACONSUM", "TATAMOTORS",
    "TATASTEEL", "TCS", "TITAN", "TRENT", "ULTRACEMCO",
    "VBL", "VEDL", "WIPRO", "ZOMATO",
}


def is_indian_symbol(symbol: str) -> bool:
    """Return True if symbol corresponds to an Indian market equity/index."""
    if not symbol or not isinstance(symbol, str):
        return False
    s = symbol.strip().upper()
    if s.endswith((".NS", ".BO")):
        return True
    if s in ("INDIA", "NSE", "BSE"):
        return True
    clean = s.split(".")[0]
    return clean in COMMON_INDIAN_SYMBOLS


def normalize_symbol(symbol: str) -> str:
    """
    Canonicalize symbol across ARTH:
    - Bare Indian symbols ('RELIANCE', 'TCS', 'INFY') -> 'RELIANCE.NS', 'TCS.NS', 'INFY.NS'
    - Suffix-bearing Indian symbols ('RELIANCE.NS') -> 'RELIANCE.NS'
    - US symbols ('AAPL', 'TSLA', 'MSFT') -> 'AAPL', 'TSLA', 'MSFT'
    """
    if not symbol or not isinstance(symbol, str):
        return symbol or ""
    s = symbol.strip().upper()
    if s.endswith((".NS", ".BO")):
        return s
    clean = s.split(".")[0]
    if clean in COMMON_INDIAN_SYMBOLS or s in COMMON_INDIAN_SYMBOLS:
        return f"{clean}.NS"
    return s


def get_symbol_currency(symbol: str) -> str:
    """Derive display currency: '₹' for Indian equities, '$' for US/others."""
    canonical = normalize_symbol(symbol)
    if canonical.endswith((".NS", ".BO")):
        return "₹"
    return "$"
