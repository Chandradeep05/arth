"""
ARTH-50 Benchmark & Research Cohort Specification.

Canonical reference cohort of 50 liquid large-cap equities (25 Indian + 25 US)
used strictly for quantitative evaluation, walk-forward cross-validation, model bakeoffs,
and baseline tracking across ARTH's dual-market architecture.

IMPORTANT PRODUCT GOVERNANCE:
- ARTH product coverage is NOT restricted to this cohort.
- ARTH supports discovery, quotes, indicators, alerts, and predictions across all
  valid Indian (NSE/BSE) equities, US equities, cryptocurrencies, and market indices.
- Under NO circumstances should this list be used to restrict or validate user queries.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Set

ARTH_50_VERSION: str = "v2.0.0"

# 25 Liquid Indian Large-Cap Equities (NSE)
ARTH_50_IN_SYMBOLS: List[str] = sorted([
    "ADANIENT.NS",
    "ADANIPORTS.NS",
    "APOLLOHOSP.NS",
    "ASIANPAINT.NS",
    "AXISBANK.NS",
    "BAJAJ-AUTO.NS",
    "BAJAJFINSV.NS",
    "BAJFINANCE.NS",
    "BEL.NS",
    "BHARTIARTL.NS",
    "BPCL.NS",
    "BRITANNIA.NS",
    "CIPLA.NS",
    "COALINDIA.NS",
    "DRREDDY.NS",
    "HCLTECH.NS",
    "HDFCBANK.NS",
    "HINDUNILVR.NS",
    "ICICIBANK.NS",
    "INFY.NS",
    "ITC.NS",
    "KOTAKBANK.NS",
    "LT.NS",
    "RELIANCE.NS",
    "TCS.NS",
])

# 25 Liquid US Mega/Large-Cap Equities (NYSE / NASDAQ)
ARTH_50_US_SYMBOLS: List[str] = sorted([
    "AAPL",
    "ABBV",
    "AMZN",
    "AVGO",
    "BAC",
    "BRK.B",
    "COST",
    "CSCO",
    "CVX",
    "GOOGL",
    "HD",
    "JNJ",
    "JPM",
    "KO",
    "MA",
    "META",
    "MRK",
    "MSFT",
    "NVDA",
    "PEP",
    "PG",
    "TSLA",
    "V",
    "WMT",
    "XOM",
])

# Combined canonical cohort (exactly 50 symbols: 25 IN, 25 US)
ARTH_50_SYMBOLS: List[str] = sorted(ARTH_50_IN_SYMBOLS + ARTH_50_US_SYMBOLS)

# Pinned literal SHA-256 fingerprint of the canonical JSON-serialized symbol list
PINNED_ARTH_50_HASH: str = "e4a8efc14cbe1a8fbb9c7db48dd578ce658f50fd7c1440eb1766fdfef37da2c3"

# Computed hash to verify integrity against pinned literal
ARTH_50_HASH: str = hashlib.sha256(
    json.dumps(ARTH_50_SYMBOLS, sort_keys=True).encode("utf-8")
).hexdigest()

_ARTH_50_SET: Set[str] = set(ARTH_50_SYMBOLS)
_ARTH_50_IN_SET: Set[str] = set(ARTH_50_IN_SYMBOLS)
_ARTH_50_US_SET: Set[str] = set(ARTH_50_US_SYMBOLS)


@dataclass(frozen=True)
class CohortConstituent:
    canonical_symbol: str
    ticker: str
    exchange: str
    market: str
    currency: str
    currency_symbol: str
    sector: str
    effective_date: str


def get_arth50_symbols() -> List[str]:
    """Return a copy of the canonical ARTH-50 symbol list (50 symbols: 25 IN + 25 US)."""
    return list(ARTH_50_SYMBOLS)


def get_arth50_indian_symbols() -> List[str]:
    """Return the 25 Indian equity symbols in the ARTH-50 cohort."""
    return list(ARTH_50_IN_SYMBOLS)


def get_arth50_us_symbols() -> List[str]:
    """Return the 25 US equity symbols in the ARTH-50 cohort."""
    return list(ARTH_50_US_SYMBOLS)


def is_arth50_symbol(symbol: str) -> bool:
    """Check whether a symbol belongs to the ARTH-50 benchmarking cohort."""
    if not symbol:
        return False
    s = symbol.strip().upper()
    if s in _ARTH_50_SET:
        return True
    # Check if bare symbol matches an Indian constituent
    if not s.endswith(".NS") and f"{s}.NS" in _ARTH_50_SET:
        return True
    return False


def get_arth50_metadata() -> Dict[str, Any]:
    """Return metadata about the ARTH-50 benchmarking cohort."""
    return {
        "version": ARTH_50_VERSION,
        "count": len(ARTH_50_SYMBOLS),
        "count_total": len(ARTH_50_SYMBOLS),
        "count_indian": len(ARTH_50_IN_SYMBOLS),
        "count_us": len(ARTH_50_US_SYMBOLS),
        "fingerprint_sha256": ARTH_50_HASH,
        "pinned_hash_match": ARTH_50_HASH == PINNED_ARTH_50_HASH,
        "purpose": "Quantitative evaluation, backtesting, model bakeoff, and calibration tracking",
        "restricted_product_universe": False,
    }
