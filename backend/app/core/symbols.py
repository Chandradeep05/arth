"""
Symbol normalization and market classification module.

Single authoritative source of truth for:
- Canonicalizing user-provided ticker symbols across ARTH
- Distinguishing Indian (NSE/BSE) equities and indices from US equities
- Determining display currency ($ vs Rs.)
"""
from __future__ import annotations

from typing import Set

# Stage 1 controlled instrument universe: 59 Nifty-50 / major NSE tickers.
#
# LIMITATION: Bare symbols (without .NS/.BO suffix) are classified as Indian
# ONLY if they appear in this list. Legitimate NSE stocks outside the list
# (e.g. PIDILITIND, DMART, IRCTC, ZEEL) will be treated as US symbols.
# Users must provide explicit .NS/.BO suffix for Indian stocks outside this list.
#
# KNOWN AMBIGUITY: HAL is in this list (HAL.NS on NSE). Bare "HAL" normalizes
# to HAL.NS. Users intending Halliburton (NYSE) must provide the full ticker
# "HAL" only without the .NS suffix — but since bare HAL resolves to HAL.NS,
# the Halliburton use-case requires explicit scoping outside Stage 1.
#
# TODO (Stage 2): Replace with a full instrument master (NSE/BSE/NYSE/NASDAQ)
# to eliminate the allowlist boundary entirely.
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
    Canonicalize symbol across ARTH.

    SUPPORTED UNIVERSE (Stage 1):
    - Bare symbols in COMMON_INDIAN_SYMBOLS -> appended with .NS
      e.g. RELIANCE -> RELIANCE.NS, TCS -> TCS.NS, INFY -> INFY.NS
    - Explicit .NS/.BO suffix -> returned as-is
      e.g. RELIANCE.NS -> RELIANCE.NS, TCS.BO -> TCS.BO
    - All other bare symbols -> returned as-is (treated as US for routing)
      e.g. AAPL -> AAPL, TSLA -> TSLA, MSFT -> MSFT

    LIMITATION: Bare symbols NOT in COMMON_INDIAN_SYMBOLS that are legitimate
    NSE/BSE stocks will be misrouted as US. Users should use explicit .NS/.BO
    suffix for Indian stocks outside the known Stage 1 universe (59 symbols).

    TODO (Stage 2): Replace with instrument master for full NSE/BSE/NASDAQ/NYSE
    coverage, eliminating this allowlist boundary.
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
    """Derive display currency: Rs. (Indian Rupee) for Indian equities, $ for US/others."""
    canonical = normalize_symbol(symbol)
    if canonical.endswith((".NS", ".BO")):
        return "\u20b9"  # Indian Rupee sign (Rs.)
    return "$"
