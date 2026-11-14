"""
ARTH Canonical Instrument Resolution & Identity Engine (Milestone M2.5).

Single authoritative source of truth for:
- Canonical instrument identification across exchanges (NSE, BSE, NYSE, NASDAQ)
- Asset class classification (EQUITY, INDEX, CRYPTO, UNKNOWN)
- Currency derivation (INR / USD)
- Ambiguous ticker handling (e.g. HAL.NS vs HAL NYSE)
- Historical ticker rename and corporate-action transition history (e.g. TATAMOTORS -> TMPV / TMCV)
- Index alias unification (NIFTY -> ^NSEI, BANKNIFTY -> ^NSEBANK, SENSEX -> ^BSESN)
- Provider-specific identifier mappings and capability filtering
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple


class AssetClass(str, Enum):
    EQUITY = "EQUITY"
    INDEX = "INDEX"
    CRYPTO = "CRYPTO"
    ETF = "ETF"
    UNKNOWN = "UNKNOWN"


class Exchange(str, Enum):
    NSE = "NSE"
    BSE = "BSE"
    NYSE = "NYSE"
    NASDAQ = "NASDAQ"
    UNKNOWN = "UNKNOWN"


class Market(str, Enum):
    IN = "IN"
    US = "US"
    CRYPTO = "CRYPTO"
    UNKNOWN = "UNKNOWN"


class ListingStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DELISTED = "DELISTED"
    SUSPENDED = "SUSPENDED"
    HISTORICAL_ALIAS = "HISTORICAL_ALIAS"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class CorporateActionMetadata:
    """Historical corporate action record for price continuity auditing."""
    transition_type: str
    effective_date: str
    prior_symbol: str
    canonical_symbol: str
    notes: str
    demerged_peer: Optional[str] = None
    discontinuity_window_start: Optional[str] = None
    discontinuity_window_end: Optional[str] = None


@dataclass(frozen=True)
class ResolvedInstrument:
    """Standardized representation of a financial instrument."""
    canonical_symbol: str
    raw_symbol: str
    exchange: Exchange
    market: Market
    asset_class: AssetClass
    currency: str          # "INR" or "USD"
    currency_symbol: str   # "₹" or "$"
    is_supported: bool
    is_index: bool
    is_ambiguous: bool
    ambiguity_note: Optional[str] = None
    listing_status: ListingStatus = ListingStatus.ACTIVE
    provider_tickers: Dict[str, str] = field(default_factory=dict)
    corporate_action: Optional[CorporateActionMetadata] = None


# ─────────────────────────────────────────────────────────────────────────────
# 1. Historical Corporate Action & Symbol Transition Registry
# ─────────────────────────────────────────────────────────────────────────────

# Historical ticker transition: Tata Motors Passenger Vehicles demerger (Oct 2025)
# Prior symbol: TATAMOTORS.NS -> Canonical: TMPV.NS, Demerged CV peer: TMCV.NS
TATA_MOTORS_TRANSITION = CorporateActionMetadata(
    transition_type="DEMERGER_RENAME",
    effective_date="2025-10-24",
    prior_symbol="TATAMOTORS.NS",
    canonical_symbol="TMPV.NS",
    demerged_peer="TMCV.NS",
    discontinuity_window_start="2025-09-01",
    discontinuity_window_end="2025-11-30",
    notes=(
        "Tata Motors demerged into Passenger Vehicles (TMPV.NS) and Commercial Vehicles (TMCV.NS) "
        "effective 24 Oct 2025. Historical prices prior to 2025-10-24 represent the combined entity "
        "and must NOT be stitched to TMPV without corporate-action adjustment factors."
    ),
)

SYMBOL_TRANSITIONS: Dict[str, CorporateActionMetadata] = {
    "TATAMOTORS": TATA_MOTORS_TRANSITION,
    "TATAMOTORS.NS": TATA_MOTORS_TRANSITION,
    "TMPV": TATA_MOTORS_TRANSITION,
    "TMPV.NS": TATA_MOTORS_TRANSITION,
}


# ─────────────────────────────────────────────────────────────────────────────
# 2. Canonical Index Aliases & Catalog
# ─────────────────────────────────────────────────────────────────────────────

# Canonical index definitions: alias -> canonical index symbol
INDEX_ALIASES: Dict[str, str] = {
    # Indian Indices
    "NIFTY": "^NSEI",
    "NIFTY50": "^NSEI",
    "NIFTY 50": "^NSEI",
    "^NSEI": "^NSEI",
    "BANKNIFTY": "^NSEBANK",
    "NIFTYBANK": "^NSEBANK",
    "^NSEBANK": "^NSEBANK",
    "SENSEX": "^BSESN",
    "BSE SENSEX": "^BSESN",
    "^BSESN": "^BSESN",
    "CNXIT": "^CNXIT",
    "NIFTYIT": "^CNXIT",
    "^CNXIT": "^CNXIT",
    "CNXAUTO": "^CNXAUTO",
    "^CNXAUTO": "^CNXAUTO",
    "CNXFMCG": "^CNXFMCG",
    "^CNXFMCG": "^CNXFMCG",
    # US Indices
    "SPX": "^GSPC",
    "S&P500": "^GSPC",
    "SP500": "^GSPC",
    "^GSPC": "^GSPC",
    "COMP": "^IXIC",
    "NASDAQ": "^IXIC",
    "^IXIC": "^IXIC",
    "DJIA": "^DJI",
    "DOW": "^DJI",
    "^DJI": "^DJI",
    "RUT": "^RUT",
    "RUSSELL2000": "^RUT",
    "^RUT": "^RUT",
    "VIX": "^VIX",
    "^VIX": "^VIX",
}

# Recognized Indian Indices
INDIAN_INDEX_SET: Set[str] = {
    "^NSEI", "^BSESN", "^NSEBANK", "^CNXIT", "^CNXAUTO", "^CNXFMCG",
}

# Recognized US Indices
US_INDEX_SET: Set[str] = {
    "^GSPC", "^IXIC", "^DJI", "^RUT", "^VIX",
}

# Provider capabilities for indices (Upstox supports Indian index keys; TwelveData free tier has restrictions)
INDEX_PROVIDER_SUPPORT: Dict[str, Dict[str, Any]] = {
    "^NSEI": {"supported": True, "provider": "upstox", "provider_key": "NSE_INDEX|Nifty 50", "proxy": None},
    "^NSEBANK": {"supported": True, "provider": "upstox", "provider_key": "NSE_INDEX|Nifty Bank", "proxy": None},
    "^BSESN": {"supported": True, "provider": "upstox", "provider_key": "BSE_INDEX|SENSEX", "proxy": None},
    "^CNXIT": {"supported": True, "provider": "upstox", "provider_key": "NSE_INDEX|Nifty IT", "proxy": None},
    "^CNXAUTO": {"supported": True, "provider": "upstox", "provider_key": "NSE_INDEX|Nifty Auto", "proxy": None},
    "^CNXFMCG": {"supported": True, "provider": "upstox", "provider_key": "NSE_INDEX|Nifty FMCG", "proxy": None},
    "^GSPC": {"supported": False, "provider": "twelvedata", "provider_key": None, "proxy": "SPY",
              "reason": "Direct index feeds for ^GSPC require TwelveData paid plan. Use proxy ETF SPY."},
    "^IXIC": {"supported": False, "provider": "twelvedata", "provider_key": None, "proxy": "QQQ",
              "reason": "Direct index feeds for ^IXIC require TwelveData paid plan. Use proxy ETF QQQ."},
    "^DJI": {"supported": False, "provider": "twelvedata", "provider_key": None, "proxy": "DIA",
             "reason": "Direct index feeds for ^DJI require TwelveData paid plan. Use proxy ETF DIA."},
    "^RUT": {"supported": False, "provider": "twelvedata", "provider_key": None, "proxy": "IWM",
             "reason": "Direct index feeds for ^RUT require TwelveData paid plan. Use proxy ETF IWM."},
    "^VIX": {"supported": False, "provider": "twelvedata", "provider_key": None, "proxy": "VXX",
             "reason": "Direct index feeds for ^VIX require TwelveData paid plan. Use proxy ETF VXX."},
}


# ─────────────────────────────────────────────────────────────────────────────
# 3. Known Ambiguous Tickers & Common Equities
# ─────────────────────────────────────────────────────────────────────────────

# Cross-market ticker collisions where bare symbol is ambiguous without exchange qualifier
AMBIGUOUS_TICKERS: Dict[str, str] = {
    "HAL": "Ambiguous ticker: symbol is ambiguous across exchanges: Hindustan Aeronautics (NSE: HAL.NS) vs Halliburton (NYSE: HAL). Please specify exchange suffix.",
}

# Major NSE Equities
COMMON_INDIAN_EQUITIES: Set[str] = {
    "ADANIENT", "ADANIPORTS", "APOLLOHOSP", "ASIANPAINT", "AXISBANK",
    "BAJAJ-AUTO", "BAJAJFINSV", "BAJFINANCE", "BEL", "BHARTIARTL",
    "BPCL", "BRITANNIA", "CIPLA", "COALINDIA", "DIVISLAB",
    "DRREDDY", "EICHERMOT", "ETERNAL", "GRASIM", "HCLTECH",
    "HDFCBANK", "HDFCLIFE", "HEROMOTOCO", "HINDALCO", "HINDUNILVR",
    "ICICIBANK", "INDUSINDBK", "INFY", "ITC", "JIOFIN",
    "JSWSTEEL", "KOTAKBANK", "LT", "M&M", "MARUTI",
    "NESTLEIND", "NTPC", "ONGC", "PAYTM", "POWERGRID",
    "RELIANCE", "SBILIFE", "SBIN", "SHREECEM", "SHRIRAMFIN",
    "SUNPHARMA", "TATACONSUM", "TATAMOTORS", "TATASTEEL", "TCS",
    "TECHM", "TITAN", "TMPV", "TMCV", "TRENT",
    "ULTRACEMCO", "VBL", "VEDL", "WIPRO", "ZOMATO",
}

# Major US Equities
COMMON_US_EQUITIES: Set[str] = {
    "AAPL", "ABBV", "AMZN", "AVGO", "BAC", "BRK.A", "BRK.B",
    "COST", "CSCO", "CVX", "DIS", "GOOG", "GOOGL", "HD",
    "INTC", "JNJ", "JPM", "KO", "MA", "META", "MRK",
    "MSFT", "NFLX", "NVDA", "ORCL", "PEP", "PG", "QCOM",
    "TSLA", "UNH", "V", "WMT", "XOM",
}

# Crypto Assets
CRYPTO_SYMBOLS: Set[str] = {
    "BTC-USD", "ETH-USD", "SOL-USD", "BTC", "ETH", "SOL",
}


# ─────────────────────────────────────────────────────────────────────────────
# 4. Canonical Instrument Resolver Function
# ─────────────────────────────────────────────────────────────────────────────

def resolve_instrument(symbol: str) -> ResolvedInstrument:
    """
    Resolve an arbitrary user or provider symbol into its canonical instrument identity.

    Guarantees:
    - Never defaults unknown tickers to US.
    - Never assumes every leading '^' is a valid index.
    - Resolves historical ticker renames (e.g. TATAMOTORS -> TMPV.NS with metadata).
    - Unifies index aliases (e.g. NIFTY and ^NSEI resolve to ^NSEI).
    - Distinguishes provider-supported vs unsupported indices.
    - Flags ambiguous cross-market tickers (e.g. bare HAL).
    """
    if not symbol or not isinstance(symbol, str):
        return ResolvedInstrument(
            canonical_symbol="",
            raw_symbol=str(symbol or ""),
            exchange=Exchange.UNKNOWN,
            market=Market.UNKNOWN,
            asset_class=AssetClass.UNKNOWN,
            currency="USD",
            currency_symbol="$",
            is_supported=False,
            is_index=False,
            is_ambiguous=False,
        )

    clean = symbol.strip().upper()

    # ── Check Ambiguity ──
    if clean in AMBIGUOUS_TICKERS:
        note = AMBIGUOUS_TICKERS[clean]
        return ResolvedInstrument(
            canonical_symbol=clean,
            raw_symbol=symbol,
            exchange=Exchange.UNKNOWN,
            market=Market.UNKNOWN,
            asset_class=AssetClass.EQUITY,
            currency="USD",
            currency_symbol="$",
            is_supported=False,
            is_index=False,
            is_ambiguous=True,
            ambiguity_note=note,
        )

    # ── Check Indices (Carets and Aliases) ──
    if clean in INDEX_ALIASES:
        canonical_idx = INDEX_ALIASES[clean]
        is_in = canonical_idx in INDIAN_INDEX_SET
        market = Market.IN if is_in else Market.US
        exchange = Exchange.NSE if is_in else (Exchange.NYSE if canonical_idx in ("^GSPC", "^DJI") else Exchange.NASDAQ)
        currency = "INR" if is_in else "USD"
        curr_sym = "\u20b9" if is_in else "$"

        support_meta = INDEX_PROVIDER_SUPPORT.get(canonical_idx, {"supported": False, "provider": "unknown"})
        is_supp = support_meta.get("supported", False)
        provider_key = support_meta.get("provider_key")
        prov_dict = {support_meta.get("provider", "unknown"): provider_key} if provider_key else {}

        return ResolvedInstrument(
            canonical_symbol=canonical_idx,
            raw_symbol=symbol,
            exchange=exchange,
            market=market,
            asset_class=AssetClass.INDEX,
            currency=currency,
            currency_symbol=curr_sym,
            is_supported=is_supp,
            is_index=True,
            is_ambiguous=False,
            provider_tickers=prov_dict,
        )

    # ── Unknown caret ticker (not a recognized index) ──
    if clean.startswith("^"):
        return ResolvedInstrument(
            canonical_symbol=clean,
            raw_symbol=symbol,
            exchange=Exchange.UNKNOWN,
            market=Market.UNKNOWN,
            asset_class=AssetClass.UNKNOWN,
            currency="USD",
            currency_symbol="$",
            is_supported=False,
            is_index=True,
            is_ambiguous=False,
            ambiguity_note=f"Unrecognized or unsupported index ticker '{clean}'.",
        )

    # ── Check Crypto ──
    if clean in CRYPTO_SYMBOLS:
        canon_crypto = clean if "-" in clean else f"{clean}-USD"
        return ResolvedInstrument(
            canonical_symbol=canon_crypto,
            raw_symbol=symbol,
            exchange=Exchange.UNKNOWN,
            market=Market.CRYPTO,
            asset_class=AssetClass.CRYPTO,
            currency="USD",
            currency_symbol="$",
            is_supported=True,
            is_index=False,
            is_ambiguous=False,
        )

    # ── Check Corporate Action / Transition Aliases ──
    corp_action = None
    if clean in SYMBOL_TRANSITIONS:
        corp_action = SYMBOL_TRANSITIONS[clean]
        # Map to canonical target
        target_sym = corp_action.canonical_symbol
        return ResolvedInstrument(
            canonical_symbol=target_sym,
            raw_symbol=symbol,
            exchange=Exchange.NSE,
            market=Market.IN,
            asset_class=AssetClass.EQUITY,
            currency="INR",
            currency_symbol="\u20b9",
            is_supported=True,
            is_index=False,
            is_ambiguous=False,
            listing_status=ListingStatus.HISTORICAL_ALIAS if clean != target_sym else ListingStatus.ACTIVE,
            corporate_action=corp_action,
        )

    # ── Explicit Indian Exchange Suffix (.NS, .BO) ──
    if clean.endswith(".NS"):
        return ResolvedInstrument(
            canonical_symbol=clean,
            raw_symbol=symbol,
            exchange=Exchange.NSE,
            market=Market.IN,
            asset_class=AssetClass.EQUITY,
            currency="INR",
            currency_symbol="\u20b9",
            is_supported=True,
            is_index=False,
            is_ambiguous=False,
        )

    if clean.endswith(".BO"):
        return ResolvedInstrument(
            canonical_symbol=clean,
            raw_symbol=symbol,
            exchange=Exchange.BSE,
            market=Market.IN,
            asset_class=AssetClass.EQUITY,
            currency="INR",
            currency_symbol="\u20b9",
            is_supported=True,
            is_index=False,
            is_ambiguous=False,
        )

    # ── Bare Indian Equities from Known Universe ──
    if clean in COMMON_INDIAN_EQUITIES:
        return ResolvedInstrument(
            canonical_symbol=f"{clean}.NS",
            raw_symbol=symbol,
            exchange=Exchange.NSE,
            market=Market.IN,
            asset_class=AssetClass.EQUITY,
            currency="INR",
            currency_symbol="\u20b9",
            is_supported=True,
            is_index=False,
            is_ambiguous=False,
        )

    # ── Known US Equities ──
    if clean in COMMON_US_EQUITIES:
        # Determine likely exchange
        nasdaq_known = {"AAPL", "MSFT", "GOOG", "GOOGL", "AMZN", "META", "NVDA", "TSLA", "PEP", "COST", "CSCO", "AVGO", "INTC", "QCOM", "NFLX"}
        ex = Exchange.NASDAQ if clean in nasdaq_known else Exchange.NYSE
        return ResolvedInstrument(
            canonical_symbol=clean,
            raw_symbol=symbol,
            exchange=ex,
            market=Market.US,
            asset_class=AssetClass.EQUITY,
            currency="USD",
            currency_symbol="$",
            is_supported=True,
            is_index=False,
            is_ambiguous=False,
        )

    # ── Valid General US Equity Ticker Pattern ──
    # Single-token alphanumeric with dot/hyphen (e.g. BRK.B, BF.B)
    import re
    if re.match(r"^[A-Z]{1,5}(\.[A-Z]{1,2})?$", clean):
        return ResolvedInstrument(
            canonical_symbol=clean,
            raw_symbol=symbol,
            exchange=Exchange.NYSE,
            market=Market.US,
            asset_class=AssetClass.EQUITY,
            currency="USD",
            currency_symbol="$",
            is_supported=True,
            is_index=False,
            is_ambiguous=False,
        )

    # ── Unsupported / Unknown Instrument ──
    return ResolvedInstrument(
        canonical_symbol=clean,
        raw_symbol=symbol,
        exchange=Exchange.UNKNOWN,
        market=Market.UNKNOWN,
        asset_class=AssetClass.UNKNOWN,
        currency="USD",
        currency_symbol="$",
        is_supported=False,
        is_index=False,
        is_ambiguous=False,
        ambiguity_note=f"Unknown or unsupported instrument identifier '{clean}'.",
    )
