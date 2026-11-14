"""
Symbol normalization and market classification module.

Delegates core identity resolution to the canonical instrument resolver in
app.core.instrument_resolver while maintaining full backward compatibility
for existing callers and test suites across ARTH.
"""
from __future__ import annotations

from typing import Set

from app.core.instrument_resolver import (
    AssetClass,
    CorporateActionMetadata,
    Exchange,
    ListingStatus,
    Market,
    ResolvedInstrument,
    resolve_instrument,
    AMBIGUOUS_TICKERS,
    COMMON_INDIAN_EQUITIES,
    INDIAN_INDEX_SET,
    US_INDEX_SET,
    INDEX_ALIASES,
)

COMMON_INDIAN_SYMBOLS: Set[str] = set(COMMON_INDIAN_EQUITIES)
AMBIGUOUS_SYMBOLS: Set[str] = set(AMBIGUOUS_TICKERS.keys())
INDIAN_INDICES: Set[str] = set(INDIAN_INDEX_SET)
US_INDICES: Set[str] = set(US_INDEX_SET)
ALL_KNOWN_INDICES: Set[str] = INDIAN_INDICES | US_INDICES


def is_index_symbol(symbol: str) -> bool:
    """Return True if symbol corresponds to a major market index."""
    if not symbol:
        return False
    return resolve_instrument(symbol).is_index


def is_indian_symbol(symbol: str) -> bool:
    """Return True if symbol corresponds to an Indian market equity/index."""
    if not symbol or not isinstance(symbol, str):
        return False
    res = resolve_instrument(symbol)
    if res.is_ambiguous and res.raw_symbol.strip().upper() == "HAL":
        return True  # Preserves Stage 1 compatibility where bare HAL routes to HAL.NS
    return res.market == Market.IN


def normalize_symbol(symbol: str) -> str:
    """
    Canonicalize symbol across ARTH.

    - Index aliases (NIFTY, SENSEX, BANKNIFTY) -> ^NSEI, ^BSESN, ^NSEBANK
    - Caret indices (^NSEI, ^GSPC, ^IXIC) -> preserved as-is
    - Bare Indian equities (RELIANCE, TCS, INFY) -> appended with .NS
    - Bare US equities (AAPL, TSLA, MSFT) -> preserved as-is
    - Ambiguous bare ticker HAL -> HAL.NS (with Stage 1 compatibility)
    """
    if not symbol or not isinstance(symbol, str):
        return symbol or ""
    s = symbol.strip().upper()
    if s == "HAL":
        return "HAL.NS"

    res = resolve_instrument(s)
    if res.canonical_symbol:
        return res.canonical_symbol
    return s


def get_symbol_currency(symbol: str) -> str:
    """Derive display currency: Rs. (Indian Rupee) for Indian equities/indices, $ for US/others."""
    if not symbol:
        return "$"
    res = resolve_instrument(symbol)
    if res.is_ambiguous and res.raw_symbol.strip().upper() == "HAL":
        return "\u20b9"
    return res.currency_symbol
