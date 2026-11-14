"""
Unit and integration tests for ARTH Milestone M2:
1. Index symbol validation and handling in symbols.py and alerts.py.
2. Exchange Calendar session logic, holiday skipping, and horizon session resolution.
3. ARTH-50 Benchmark Cohort specification and SHA-256 fingerprint verification.
"""

from __future__ import annotations

from datetime import date, datetime, time
import pytest
from pydantic import ValidationError

from app.api.v1.alerts import CreateAlertRequest
from app.core.arth50 import (
    ARTH_50_HASH,
    ARTH_50_SYMBOLS,
    ARTH_50_VERSION,
    get_arth50_metadata,
    get_arth50_symbols,
    is_arth50_symbol,
)
from app.core.exchange_calendar import ExchangeCalendar, exchange_calendar
from app.core.instrument_resolver import (
    AssetClass,
    Exchange,
    ListingStatus,
    Market,
    resolve_instrument,
)
from app.core.market_calendar import CalendarCoverageError, TZ_ET, TZ_IST
from app.core.symbols import (
    get_symbol_currency,
    is_index_symbol,
    is_indian_symbol,
    normalize_symbol,
)


# ─────────────────────────────────────────────────────────────────────────────
# 1. Symbol & Index Validation Tests
# ─────────────────────────────────────────────────────────────────────────────

def test_index_symbol_recognition():
    assert is_index_symbol("^NSEI") is True
    assert is_index_symbol("^BSESN") is True
    assert is_index_symbol("^GSPC") is True
    assert is_index_symbol("^IXIC") is True
    assert is_index_symbol("NIFTY") is True
    assert is_index_symbol("BANKNIFTY") is True
    assert is_index_symbol("AAPL") is False
    assert is_index_symbol("RELIANCE.NS") is False


def test_is_indian_symbol_indices():
    # Indian indices
    assert is_indian_symbol("^NSEI") is True
    assert is_indian_symbol("^BSESN") is True
    assert is_indian_symbol("^NSEBANK") is True
    assert is_indian_symbol("^CNXIT") is True
    assert is_indian_symbol("NIFTY") is True

    # Indian equities
    assert is_indian_symbol("RELIANCE.NS") is True
    assert is_indian_symbol("RELIANCE") is True
    assert is_indian_symbol("TCS") is True
    assert is_indian_symbol("INFY.BO") is True

    # US symbols & indices
    assert is_indian_symbol("^GSPC") is False
    assert is_indian_symbol("^IXIC") is False
    assert is_indian_symbol("^DJI") is False
    assert is_indian_symbol("AAPL") is False
    assert is_indian_symbol("TSLA") is False


def test_normalize_symbol_preserves_indices():
    # Indices starting with ^ must NOT be appended with .NS
    assert normalize_symbol("^NSEI") == "^NSEI"
    assert normalize_symbol("^BSESN") == "^BSESN"
    assert normalize_symbol("^GSPC") == "^GSPC"
    assert normalize_symbol("^IXIC") == "^IXIC"

    # Equities follow normal rules
    assert normalize_symbol("RELIANCE") == "RELIANCE.NS"
    assert normalize_symbol("TCS") == "TCS.NS"
    assert normalize_symbol("AAPL") == "AAPL"


def test_get_symbol_currency():
    # Indian symbols & indices -> Rupee sign
    assert get_symbol_currency("^NSEI") == "\u20b9"
    assert get_symbol_currency("^BSESN") == "\u20b9"
    assert get_symbol_currency("RELIANCE.NS") == "\u20b9"
    assert get_symbol_currency("RELIANCE") == "\u20b9"
    assert get_symbol_currency("TCS") == "\u20b9"

    # US symbols & indices -> Dollar sign
    assert get_symbol_currency("^GSPC") == "$"
    assert get_symbol_currency("^IXIC") == "$"
    assert get_symbol_currency("AAPL") == "$"
    assert get_symbol_currency("MSFT") == "$"


def test_alert_request_validator_accepts_indices():
    # Supported Indian index with caret succeeds
    alert_nsei = CreateAlertRequest(symbol="^NSEI", alert_type="price_above", threshold=25000.0)
    assert alert_nsei.symbol == "^NSEI"

    # Supported Indian equity normalizes to .NS
    alert_stock = CreateAlertRequest(symbol="RELIANCE", alert_type="price_above", threshold=3000.0)
    assert alert_stock.symbol == "RELIANCE.NS"

    # Supported US equity succeeds
    alert_us = CreateAlertRequest(symbol="AAPL", alert_type="price_above", threshold=220.0)
    assert alert_us.symbol == "AAPL"

    # Supported US ETF succeeds
    alert_etf = CreateAlertRequest(symbol="SPY", alert_type="price_above", threshold=580.0)
    assert alert_etf.symbol == "SPY"

    # Direct US index (^GSPC) is rejected due to provider free-tier restriction
    with pytest.raises(ValidationError, match="not resolvable or unsupported"):
        CreateAlertRequest(symbol="^GSPC", alert_type="price_above", threshold=6000.0)

    # Ambiguous ticker without suffix (HAL) is rejected
    with pytest.raises(ValidationError, match="Ambiguous ticker"):
        CreateAlertRequest(symbol="HAL", alert_type="price_above", threshold=4000.0)

    # Caret in middle or end is rejected by regex
    with pytest.raises(ValidationError):
        CreateAlertRequest(symbol="REL^IANCE", alert_type="price_above", threshold=100.0)
    with pytest.raises(ValidationError):
        CreateAlertRequest(symbol="AAPL^", alert_type="price_above", threshold=100.0)
    with pytest.raises(ValidationError):
        CreateAlertRequest(symbol="^^NSEI", alert_type="price_above", threshold=100.0)

    # Invalid symbol with special characters outside allowed set
    with pytest.raises(ValidationError):
        CreateAlertRequest(symbol="<script>", alert_type="price_above", threshold=100.0)
    with pytest.raises(ValidationError):
        CreateAlertRequest(symbol="RELIANCE;DROP TABLE", alert_type="price_above", threshold=100.0)
    with pytest.raises(ValidationError):
        CreateAlertRequest(symbol="", alert_type="price_above", threshold=100.0)


# ─────────────────────────────────────────────────────────────────────────────
# 2. Exchange Calendar Tests
# ─────────────────────────────────────────────────────────────────────────────

def test_is_trading_day_weekends():
    cal = ExchangeCalendar()
    # 2026-02-07 is Saturday, 2026-02-08 is Sunday
    assert cal.is_trading_day(date(2026, 2, 7), exchange="NSE") is False
    assert cal.is_trading_day(date(2026, 2, 8), exchange="NSE") is False
    assert cal.is_trading_day(date(2026, 2, 7), exchange="NYSE") is False
    assert cal.is_trading_day(date(2026, 2, 8), exchange="NYSE") is False


def test_is_trading_day_official_holidays():
    cal = ExchangeCalendar()
    # Republic Day (India) 2026-01-26 is Monday
    assert cal.is_trading_day(date(2026, 1, 26), exchange="NSE") is False
    # But Republic Day is a normal trading day in the US
    assert cal.is_trading_day(date(2026, 1, 26), exchange="NYSE") is True

    # Martin Luther King Jr. Day (US) 2026-01-19 is Monday
    assert cal.is_trading_day(date(2026, 1, 19), exchange="NYSE") is False
    # But MLK Day is a normal trading day on NSE
    assert cal.is_trading_day(date(2026, 1, 19), exchange="NSE") is True


def test_exchange_calendar_coverage_error():
    """Dates outside 2026 must raise CalendarCoverageError when fail_closed=True."""
    cal = ExchangeCalendar()
    with pytest.raises(CalendarCoverageError):
        cal.is_trading_day(date(2028, 1, 1), exchange="NSE", fail_closed=True)
    with pytest.raises(CalendarCoverageError):
        cal.is_trading_day(date(2025, 12, 31), exchange="NSE", fail_closed=True)


def test_exchange_calendar_special_session():
    """Diwali Muhurat trading on 2026-11-08 is a special 1-hour session."""
    cal = ExchangeCalendar()
    muhurat_date = date(2026, 11, 8)
    assert cal.is_trading_day(muhurat_date, exchange="NSE") is True
    open_dt, close_dt = cal.get_session_open_close(muhurat_date, exchange="NSE")
    assert open_dt.time() == time(18, 15)
    assert close_dt.time() == time(19, 15)


def test_get_trading_days_range():
    cal = ExchangeCalendar()
    # Range spanning Republic Day 2026 (Mon Jan 26 is holiday)
    # Fri Jan 23 to Tue Jan 27:
    # Fri Jan 23 (Trade), Sat 24 (Weekend), Sun 25 (Weekend), Mon 26 (Holiday), Tue 27 (Trade)
    days = cal.get_trading_days(date(2026, 1, 23), date(2026, 1, 27), exchange="NSE")
    assert days == [date(2026, 1, 23), date(2026, 1, 27)]


def test_get_horizon_session_forward_skipping_holiday_and_weekend():
    cal = ExchangeCalendar()
    # On Friday Jan 23, 2026 before Indian Republic Day (Mon Jan 26)
    # +1 session forward on NSE must skip Sat, Sun, AND Mon holiday -> Tuesday Jan 27!
    next_session_nse = cal.get_horizon_session(date(2026, 1, 23), n_sessions=1, exchange="NSE")
    assert next_session_nse == date(2026, 1, 27)

    # But on NYSE, Mon Jan 26 is NOT a holiday -> Monday Jan 26!
    next_session_nyse = cal.get_horizon_session(date(2026, 1, 23), n_sessions=1, exchange="NYSE")
    assert next_session_nyse == date(2026, 1, 26)


def test_get_horizon_session_backward():
    cal = ExchangeCalendar()
    # On Tuesday Jan 27, 2026, -1 session backward on NSE must skip Mon Jan 26 (Holiday),
    # Sun Jan 25 (Weekend), Sat Jan 24 (Weekend) -> Friday Jan 23!
    prev_session = cal.get_horizon_session(date(2026, 1, 27), n_sessions=-1, exchange="NSE")
    assert prev_session == date(2026, 1, 23)


def test_get_horizon_session_zero():
    cal = ExchangeCalendar()
    # On a normal trading day, n=0 returns same day
    assert cal.get_horizon_session(date(2026, 1, 23), n_sessions=0, exchange="NSE") == date(2026, 1, 23)

    # On a Saturday, n=0 advances to next trading day
    # Sat Jan 24 -> advances past Sun 25, past Mon 26 (holiday) to Tue Jan 27!
    assert cal.get_horizon_session(date(2026, 1, 24), n_sessions=0, exchange="NSE") == date(2026, 1, 27)


def test_session_open_close_hours():
    cal = ExchangeCalendar()
    open_nse, close_nse = cal.get_session_open_close(date(2026, 2, 10), exchange="NSE")
    assert open_nse.tzinfo == TZ_IST
    assert open_nse.time() == time(9, 15)
    assert close_nse.time() == time(15, 30)

    # Normal US day
    open_nyse, close_nyse = cal.get_session_open_close(date(2026, 2, 10), exchange="NYSE")
    assert open_nyse.tzinfo == TZ_ET
    assert open_nyse.time() == time(9, 30)
    assert close_nyse.time() == time(16, 0)

    # US Early Close day: 2026-11-27 (day after Thanksgiving) closes at 13:00 ET
    _, early_close_nyse = cal.get_session_open_close(date(2026, 11, 27), exchange="NYSE")
    assert early_close_nyse.time() == time(13, 0)


# ─────────────────────────────────────────────────────────────────────────────
# 3. ARTH-50 Benchmark Cohort Tests
# ─────────────────────────────────────────────────────────────────────────────

def test_arth50_cohort_integrity():
    symbols = get_arth50_symbols()
    assert len(symbols) == 50
    # Must be sorted and all unique
    assert len(set(symbols)) == 50
    assert symbols == sorted(symbols)

    # Balanced dual-market: 25 Indian (.NS) + 25 US (no .NS)
    indian_symbols = [s for s in symbols if s.endswith(".NS")]
    us_symbols = [s for s in symbols if not s.endswith(".NS")]
    assert len(indian_symbols) == 25, f"Expected 25 Indian symbols, got {len(indian_symbols)}"
    assert len(us_symbols) == 25, f"Expected 25 US symbols, got {len(us_symbols)}"


def test_arth50_sha256_fingerprint():
    meta = get_arth50_metadata()
    assert meta["version"] == "v2.0.0"
    assert meta["count"] == 50
    assert meta["restricted_product_universe"] is False
    assert len(meta["fingerprint_sha256"]) == 64
    assert meta["fingerprint_sha256"] == ARTH_50_HASH
    # Pinned literal hash fixture assertion
    assert meta["fingerprint_sha256"] == "e4a8efc14cbe1a8fbb9c7db48dd578ce658f50fd7c1440eb1766fdfef37da2c3"


def test_is_arth50_symbol():
    # Indian members
    assert is_arth50_symbol("RELIANCE.NS") is True
    assert is_arth50_symbol("RELIANCE") is True
    assert is_arth50_symbol("TCS.NS") is True
    assert is_arth50_symbol("INFY") is True
    assert is_arth50_symbol("HDFCBANK.NS") is True
    assert is_arth50_symbol("HDFCBANK") is True

    # US members
    assert is_arth50_symbol("AAPL") is True
    assert is_arth50_symbol("NVDA") is True
    assert is_arth50_symbol("MSFT") is True

    # Quarantined / Demerger / Not in cohort
    assert is_arth50_symbol("TMPV.NS") is False
    assert is_arth50_symbol("TATAMOTORS") is False
    assert is_arth50_symbol("ZOMATO.NS") is False
    assert is_arth50_symbol("^NSEI") is False


# ─────────────────────────────────────────────────────────────────────────────
# 4. Canonical Instrument Resolver Tests
# ─────────────────────────────────────────────────────────────────────────────

def test_instrument_resolver_aliases():
    """Verify alias unification to canonical identifiers."""
    r_nifty = resolve_instrument("NIFTY")
    assert r_nifty.canonical_symbol == "^NSEI"
    assert r_nifty.is_index is True
    assert r_nifty.is_supported is True
    assert r_nifty.currency == "INR"

    r_bank = resolve_instrument("BANKNIFTY")
    assert r_bank.canonical_symbol == "^NSEBANK"
    assert r_bank.is_index is True
    assert r_bank.is_supported is True

    r_sensex = resolve_instrument("SENSEX")
    assert r_sensex.canonical_symbol == "^BSESN"
    assert r_sensex.is_index is True
    assert r_sensex.is_supported is True

    r_spx = resolve_instrument("SPX")
    assert r_spx.canonical_symbol == "^GSPC"
    assert r_spx.is_index is True
    assert r_spx.is_supported is False  # TwelveData paid plan required


def test_instrument_resolver_tatamotors_demerger():
    """Verify Tata Motors demerger transition, peer mapping, and quarantine window."""
    r_tm = resolve_instrument("TATAMOTORS")
    assert r_tm.canonical_symbol == "TMPV.NS"
    assert r_tm.listing_status == ListingStatus.HISTORICAL_ALIAS
    assert r_tm.corporate_action is not None
    assert r_tm.corporate_action.effective_date == "2025-10-24"
    assert r_tm.corporate_action.demerged_peer == "TMCV.NS"
    assert r_tm.corporate_action.discontinuity_window_start == "2025-09-01"
    assert r_tm.corporate_action.discontinuity_window_end == "2025-11-30"

    r_tmpv = resolve_instrument("TMPV.NS")
    assert r_tmpv.canonical_symbol == "TMPV.NS"
    assert r_tmpv.is_supported is True

    r_tmcv = resolve_instrument("TMCV.NS")
    assert r_tmcv.canonical_symbol == "TMCV.NS"
    assert r_tmcv.listing_status == ListingStatus.ACTIVE


def test_instrument_resolver_ambiguous_hal():
    """HAL is ambiguous without suffix (Hindustan Aeronautics vs Halliburton)."""
    r_hal = resolve_instrument("HAL")
    assert r_hal.is_ambiguous is True
    assert "Hindustan Aeronautics" in (r_hal.ambiguity_note or "")

    r_hal_ns = resolve_instrument("HAL.NS")
    assert r_hal_ns.is_ambiguous is False
    assert r_hal_ns.exchange == Exchange.NSE
    assert r_hal_ns.canonical_symbol == "HAL.NS"
