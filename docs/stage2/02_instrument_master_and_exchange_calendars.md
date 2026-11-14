# ARTH — Milestone M2 Verification & Audit Report: Instrument Master & Exchange Calendars

**Document Version:** 1.0.0  
**Target Milestone:** Milestone M2 — Instrument Master & Exchange Calendars  
**Target Gate:** Stage 2 / Gate G2 — Feature Hardening  
**Repository:** `Chandradeep05/arth`  
**Active Branch:** `feature/stage2-m1-canonical-indicators`  
**Base Commit:** `3c9aed6` (Merge PR #6: Native Redis test coverage & stabilization)  
**Status:** **PASS** (100% Green, 322 backend tests + 306 root integration tests = 628/628 passing)  
**Execution Date:** 14 November 2026  

---

## 1. Milestone Identity & Status

| Milestone | Description | Controlling Section | Status |
| :--- | :--- | :--- | :--- |
| **M2** | Instrument Master, Index Support, Exchange Calendars & ARTH-50 Cohort | Section 4 of Master Spec | **PASS** |

Milestone M2 establishes the canonical exchange calendars for multi-market trading schedules, index pattern support (accepting leading `^` across alert schemas and symbol normalizers), and defines the deterministic, versioned ARTH-50 research benchmark cohort.

---

## 2. Executive Summary

Prior to Milestone M2:
1. Symbol validation in `backend/app/api/v1/alerts.py` (`_SYMBOL_RE = re.compile(r"^[A-Z0-9._&-]{1,20}$")`) strictly rejected index tickers containing `^` (e.g. `^NSEI`, `^BSESN`, `^GSPC`, `^IXIC`).
2. `backend/app/core/symbols.py` did not recognize index symbols starting with `^` as indices, and lacked explicit currency/market routing for indices (e.g. `^NSEI` was classified as US with `$` currency).
3. The codebase lacked an authoritative `ExchangeCalendar` engine with point-in-time trading day validation, multi-session date arithmetic, and forward horizon session date resolution (`get_horizon_session(as_of, n)`).
4. No standardized, versioned research cohort existed for model bakeoffs and walk-forward validation.

**Milestone M2 delivers:**
- Updated symbol regex in `backend/app/api/v1/alerts.py` to allow `^` (`^[\^A-Z0-9._&-]{1,20}$`).
- Enhanced `backend/app/core/symbols.py` with `is_index_symbol`, index preservation in `normalize_symbol` (never appending `.NS` to `^` indices), and correct currency mapping (`₹` for Indian indices like `^NSEI`, `$` for US indices like `^GSPC`).
- Authoritative `ExchangeCalendar` in `backend/app/core/exchange_calendar.py` providing `is_trading_day`, `get_trading_days`, `get_horizon_session` (forward and backward, skipping weekends and exchange holidays), and localized session hours (NSE: 09:15-15:30 IST; NYSE: 09:30-16:00 ET, early close at 13:00 ET).
- Canonical ARTH-50 research benchmark cohort in `backend/app/core/arth50.py` with version `v1.0.0` and deterministic SHA-256 fingerprint:
  `6e86f5c531d0413555562d98df67140fbc9871e843c089f9ca544b6c38ce8f49`
- 15 dedicated unit and integration tests in `backend/tests/test_exchange_calendar_and_symbols.py`.
- 100% green test suite: 322 backend tests + 306 root integration tests = **628 passing tests**, zero regressions.

---

## 3. Product Governance: Market Coverage vs. Research Cohort

> [!IMPORTANT]
> **Broad Market Coverage Preservation (Section 4.1):**
> ARTH product coverage is NOT restricted to the ARTH-50 cohort.
> ARTH supports quotes, indicators, alerts, and predictions across all valid Indian (NSE/BSE) equities, US equities, cryptocurrencies, and market indices.
> The ARTH-50 list is strictly an offline research and benchmarking cohort used for:
> - Quantitative feature evaluation and selection
> - Model bakeoffs (Ridge, Logistic Regression, Random Forest, XGBoost, LightGBM)
> - Purged walk-forward cross-validation
> - Backtesting and calibration tracking
> 
> The ARTH-50 cohort is **NEVER** used as an allowlist or input validation filter for user queries or live data requests.

---

## 4. Architecture & Component Details

### 4.1 Symbol & Index Validation (`backend/app/core/symbols.py` & `backend/app/api/v1/alerts.py`)
- Regex in `alerts.py`: Updated from `^[A-Z0-9._&-]{1,20}$` to `^[\^A-Z0-9._&-]{1,20}$`.
- `is_index_symbol(symbol: str) -> bool`: Identifies index tickers starting with `^` or aliases (`NIFTY`, `BANKNIFTY`).
- `is_indian_symbol(symbol: str) -> bool`: Accurately classifies Indian indices (`^NSEI`, `^BSESN`, `^NSEBANK`, `^CNXIT`) as Indian instruments.
- `normalize_symbol(symbol: str) -> str`: Preserves `^` index symbols as-is (e.g. `^NSEI` -> `^NSEI`, `^GSPC` -> `^GSPC`).
- `get_symbol_currency(symbol: str) -> str`: Returns `₹` for Indian equities and indices, `$` for US equities and indices.

### 4.2 Authoritative Exchange Calendar (`backend/app/core/exchange_calendar.py`)
- **Supported Exchanges:**
  - `NSE` / `BSE` (Timezone: `Asia/Kolkata`, IST, UTC+5:30)
  - `NYSE` / `NASDAQ` (Timezone: `America/New_York`, US Eastern Time)
- **Key Methods:**
  - `is_trading_day(dt, exchange)`: Returns `True` only if weekday $< 5$ and date is not an official exchange holiday.
  - `get_trading_days(start_date, end_date, exchange)`: Generates sorted list of active trading dates.
  - `get_horizon_session(as_of, n_sessions, exchange)`: Resolves forward ($n > 0$) or backward ($n < 0$) trading session dates, skipping weekends and exchange holidays. For $n=0$, returns the date if a trading session, or advances to the next trading session.
  - `get_session_open_close(dt, exchange)`: Returns timezone-aware session boundaries (including NYSE early close at 13:00 ET).
  - `exchange_calendar`: Thread-safe global singleton instance.

### 4.3 Versioned ARTH-50 Cohort (`backend/app/core/arth50.py`)
- **Version:** `v1.0.0`
- **Total Count:** Exactly 50 liquid large-cap Indian equities.
- **SHA-256 Fingerprint:**
  `hashlib.sha256(json.dumps(ARTH_50_SYMBOLS, sort_keys=True).encode("utf-8")).hexdigest()`
  Hash: `6e86f5c531d0413555562d98df67140fbc9871e843c089f9ca544b6c38ce8f49`
- **Cohort Symbols:**
  `ADANIENT.NS`, `ADANIPORTS.NS`, `APOLLOHOSP.NS`, `ASIANPAINT.NS`, `AXISBANK.NS`,
  `BAJAJ-AUTO.NS`, `BAJAJFINSV.NS`, `BAJFINANCE.NS`, `BEL.NS`, `BHARTIARTL.NS`,
  `BPCL.NS`, `BRITANNIA.NS`, `CIPLA.NS`, `COALINDIA.NS`, `DIVISLAB.NS`,
  `DRREDDY.NS`, `EICHERMOT.NS`, `GRASIM.NS`, `HAL.NS`, `HCLTECH.NS`,
  `HDFCBANK.NS`, `HDFCLIFE.NS`, `HEROMOTOCO.NS`, `HINDUNILVR.NS`, `ICICIBANK.NS`,
  `INFY.NS`, `ITC.NS`, `JSWSTEEL.NS`, `KOTAKBANK.NS`, `LT.NS`,
  `M&M.NS`, `MARUTI.NS`, `NESTLEIND.NS`, `NTPC.NS`, `POWERGRID.NS`,
  `RELIANCE.NS`, `SBILIFE.NS`, `SBIN.NS`, `SHREECEM.NS`, `SUNPHARMA.NS`,
  `TATACONSUM.NS`, `TATAMOTORS.NS`, `TATASTEEL.NS`, `TCS.NS`, `TECHM.NS`,
  `TITAN.NS`, `TRENT.NS`, `ULTRACEMCO.NS`, `VBL.NS`, `WIPRO.NS`

---

## 5. Verification & Test Results

### 5.1 Test Suite Breakdown

| Suite | Tests Ran | Status | Time |
| :--- | :--- | :--- | :--- |
| `backend/tests/test_exchange_calendar_and_symbols.py` | 15 | **PASS** | 3.66s |
| `backend/tests/test_canonical_indicators.py` (M1) | 25 | **PASS** | 2.37s |
| `backend/tests/` (Full Backend Suite) | 322 | **PASS** | 68.49s |
| Root Integration Suites (`test_integration`, `test_stabilization`, `test_phase3`, `test_adversarial_auth`, `test_cors`) | 306 | **PASS** | Standalone |
| **Total Test Suite** | **628** | **PASS (100%)** | — |

### 5.2 Key Invariants Verified

| Invariant | Test | Verification Status |
| :--- | :--- | :--- |
| Index Symbol Recognition | `^NSEI`, `^BSESN`, `^GSPC`, `^IXIC` identified | **VERIFIED** |
| Index Normalization | `^NSEI` preserved as `^NSEI` without `.NS` | **VERIFIED** |
| Currency Mapping | `^NSEI` -> `₹`, `^GSPC` -> `$` | **VERIFIED** |
| Alert Request Validator | Accepts `^NSEI` and `^GSPC`, rejects invalid scripts | **VERIFIED** |
| Weekend Filtering | Saturday and Sunday are not trading days | **VERIFIED** |
| Holiday Filtering | NSE Republic Day (Jan 26) not a trade day on NSE | **VERIFIED** |
| Horizon Session Forward | Fri Jan 23 + 1 session on NSE -> Tue Jan 27 (skips Mon holiday) | **VERIFIED** |
| Horizon Session Backward | Tue Jan 27 - 1 session on NSE -> Fri Jan 23 | **VERIFIED** |
| ARTH-50 Integrity | Exactly 50 unique symbols, all ending in `.NS` | **VERIFIED** |
| ARTH-50 SHA-256 Fingerprint | Deterministic hash matches canonical JSON encoding | **VERIFIED** |

---

## 6. Git State & Inventory

- **Branch:** `feature/stage2-m1-canonical-indicators`
- **Modified:**
  - `backend/app/api/v1/alerts.py`
  - `backend/app/core/symbols.py`
  - `backend/app/engines/market/indicators.py`
  - `backend/app/engines/prediction/feature_engineering.py`
- **Added:**
  - `backend/app/core/indicators.py`
  - `backend/app/core/exchange_calendar.py`
  - `backend/app/core/arth50.py`
  - `backend/tests/test_canonical_indicators.py`
  - `backend/tests/test_exchange_calendar_and_symbols.py`
  - `docs/stage2/01_canonical_indicators.md`
  - `docs/stage2/02_instrument_master_and_exchange_calendars.md`

---

## 7. Next Steps (Milestone M3)

With Milestones M1 and M2 fully completed and audited:
- **Milestone M3: Point-in-Time Data Foundation & Provider Standardization**
  - Standardize TwelveData and Upstox schemas with strict DatetimeIndex alignment and column normalization (`Open`, `High`, `Low`, `Close`, `Volume`).
  - Zero-Fabrication enforcement: strictly assert `adj_close: None` when not supplied by upstream data providers; never manufacture fake adjusted prices.
  - Implement point-in-time timestamp cutoffs ($t \le \text{as\_of}$) preventing lookahead bias.
