# ARTH — Milestone M2.5 Data Foundation & M1 Indicator Patch Remediation Report

**Document Version:** 1.0.0  
**Status:** Complete — Local Verification Passed  
**Branch:** `feature/stage2-m1-canonical-indicators`  
**Base Commit:** `3c9aed6` on `main`  
**Date:** 15 November 2026  
**Auditor / Implementer:** Antigravity AI Engineering  

---

## 1. Executive Summary & Purpose

Following the M0–M2 quantitative foundation audit across the ARTH codebase, critical foundational defects were identified in market data ingestion, instrument identity resolution, exchange calendar bounds, benchmark cohort specification, and technical indicator semantics. 

Because ARTH is an autonomous financial intelligence platform, quantitative correctness of historical prices, corporate actions, exchange sessions, indicators, and feature representations is a non-negotiable prerequisite to training predictive models (M3) or generating trading signals (M4).

This report documents the full implementation, mathematical verification, and test execution for:
- **Milestone M2.5: Data Foundation Hardening** (M2.5.1 through M2.5.7)
- **Milestone M1: Canonical Indicator Engine Patches** (M1.1 through M1.7)

All remediations were completed strictly within local branch `feature/stage2-m1-canonical-indicators` without modifying production secrets or deploying migrations.

---

## 2. Summary of Remediations

### 2.1 M2.5.1 — ARTH-50 Benchmark Cohort Decision & Correction
- **Finding:** The repository previously contained conflicting cohort specifications (an older 50-stock Indian-only cohort vs a 25 Indian + 25 US dual-market specification in research documents).
- **Remediation:** 
  - Standardized `backend/app/core/arth50.py` to the canonical dual-market cohort: **25 Indian large caps (NSE)** + **25 US mega/large caps (NYSE/NASDAQ)** = **50 equities**.
  - Pinned literal SHA-256 fingerprint fixture:
    `"e4a8efc14cbe1a8fbb9c7db48dd578ce658f50fd7c1440eb1766fdfef37da2c3"`.
  - Enforced explicit product governance: `restricted_product_universe: False`. The cohort is strictly a benchmarking, walk-forward validation, and model bakeoff reference set; user queries are never restricted to this cohort.

### 2.2 M2.5.2 — Tata Motors Identity Transition & Demerger Handling
- **Finding:** Tata Motors demerged into Commercial Vehicles (`TMCV.NS`) and Passenger Vehicles (`TMPV.NS`) effective 24 October 2025. Historical prices prior to this date represent the combined entity and produce a false price cliff if stitched directly to `TMPV.NS`.
- **Remediation:**
  - Added `CorporateActionMetadata` structure in `backend/app/core/instrument_resolver.py`.
  - Registered transition for `TATAMOTORS` / `TATAMOTORS.NS`:
    - Canonical symbol: `TMPV.NS`
    - Demerged peer: `TMCV.NS`
    - Effective date: `2025-10-24`
    - Discontinuity quarantine window: `2025-09-01` to `2025-11-30`.
    - Listing status: `ListingStatus.HISTORICAL_ALIAS`.
  - Quarantined Tata Motors from the fixed ARTH-50 benchmarking cohort to prevent contaminated backtest metrics.

### 2.3 M2.5.3 — Canonical Instrument Resolver
- **Finding:** Bare symbols lacked authoritative resolution, leading to silent defaulting to US equities, symbol collision across markets (e.g. `HAL`), and unhandled index aliases (`NIFTY`, `BANKNIFTY`, `SENSEX`, `SPX`).
- **Remediation:**
  - Built `backend/app/core/instrument_resolver.py` providing `resolve_instrument(symbol: str) -> ResolvedInstrument`.
  - Unifies index aliases: `NIFTY` -> `^NSEI`, `BANKNIFTY` -> `^NSEBANK`, `SENSEX` -> `^BSESN`, `SPX` -> `^GSPC`, `COMP`/`NASDAQ` -> `^IXIC`.
  - Enforces cross-market ambiguity resolution: bare `HAL` is flagged as `is_ambiguous=True` with explicit prompt requiring exchange disambiguation (Hindustan Aeronautics `HAL.NS` vs Halliburton `HAL`).
  - Refactored `backend/app/core/symbols.py` to delegate canonical resolution to `instrument_resolver.py`.

### 2.4 M2.5.4 — Exchange Calendar Hardening
- **Finding:** Calendars mixed confirmed and provisional holidays, lacked fail-closed coverage checks, and did not model special exchange sessions (e.g. Diwali Muhurat trading).
- **Remediation:**
  - Segregated `NSE_CONFIRMED_HOLIDAYS_2026` from `NSE_PROVISIONAL_HOLIDAYS_2027` in `market_calendar.py` and `exchange_calendar.py`.
  - Added `CalendarCoverageError` and fail-closed coverage checks (`fail_closed=True`) rejecting dates outside covered bounds (NSE: 2026-01-01 to 2026-12-31; NYSE: 2026-01-01 to 2027-12-31).
  - Modeled special session support: Diwali Muhurat trading on `2026-11-08` (18:15 to 19:15 IST).
  - Enforced timezone conversions prior to date extraction (`TZ_IST` for NSE, `TZ_ET` for NYSE).

### 2.5 M2.5.5 — Provider Historical Adjustment Audit
- **Finding:** TwelveData `/time_series` defaults to `splits` adjustment when `adjust` is omitted, while Upstox `/v3/historical-candle` returns raw exchange candles (`RAW`). Mixing adjusted and unadjusted candles creates false signals.
- **Remediation:**
  - Verified Upstox v3 candle API has no adjustment parameter.
  - Standardized `normalize_ohlcv` to accept and record explicit `adjustment_mode` in `df.attrs['adjustment_mode']` (e.g. `SPLIT_ADJUSTED`, `RAW_EXCHANGE`).
  - Preserved metadata throughout the pipeline for downstream model awareness.

### 2.6 M2.5.6 — Index Resolution & Provider Support
- **Finding:** The system did not distinguish between valid symbol syntax, resolvable symbols, and provider-supported feeds. Direct index feeds for `^GSPC` on TwelveData fail on the free tier.
- **Remediation:**
  - `INDEX_PROVIDER_SUPPORT` explicitly maps provider capabilities:
    - Indian indices (`^NSEI`, `^BSESN`, `^NSEBANK`) -> `is_supported=True` via Upstox index instrument keys (`NSE_INDEX|Nifty 50`).
    - US indices (`^GSPC`, `^IXIC`, `^DJI`) -> `is_supported=False` on free tier, with explicit ETF proxy guidance (`SPY`, `QQQ`, `DIA`).
  - Alert validation blocks unsupported indices with informative error messages.

### 2.7 M2.5.7 — Unified OHLCV Normalization & Batch Routing
- **Finding:** DataFrames previously bypassed normalization checks while lists went through partial validation. Physical OHLC consistency was not verified. Furthermore, `get_batch_quotes` checked `s.endswith(('.NS', '.BO'))`, misclassifying Indian indices (`^NSEI`, `^BSESN`) as US equities and routing them to TwelveData.
- **Remediation:**
  - Unified `normalize_ohlcv`: DataFrames, dicts, and lists now pass through the exact same normalization and validation pipeline.
  - Enforced physical OHLC consistency:
    - `High >= Low - 1e-6`
    - `High >= Open - 1e-6`
    - `High >= Close - 1e-6`
    - `Low <= Open + 1e-6`
    - `Low <= Close + 1e-6`
  - Validated price positivity (`Open > 0`, `High > 0`, `Low > 0`, `Close > 0`) and volume non-negativity (`Volume >= 0`).
  - Chronological sort ascending by DatetimeIndex, deduplicating timestamps keeping the latest record.
  - Fixed `get_batch_quotes` routing via `is_indian_symbol`: Indian indices and equities are dispatched to Upstox/NSE; US symbols to TwelveData.

---

### 2.8 Milestone M1 Indicator & Feature Patches

| Patch | Issue | Remediation |
|---|---|---|
| **M1.1 Lookback Parity** | Live prediction requested 30–60 bars while training used 2y (~500 bars), causing indicator warm-up drift. | `build_live_features` updated to request `1y` (~252 trading days) lookback. |
| **M1.2 No Silent Imputation** | `_safe(val, 0.0)` converted missing RSI/MACD/BB into 0.0, which corresponds to extreme oversold signals. | Explicit abstention: raises `ValueError` on missing or unwarmed core technical features. No silent zero substitution. |
| **M1.3 Rolling Daily VWAP** | Session VWAP on daily bars was degenerate (`VWAP = Typical Price`). | Updated `market/indicators.py` to compute 20-bar rolling VWAP (`vwap_20d`) for daily bars while preserving `vwap` alias. |
| **M1.4 Zero-Line MACD** | `interpret_macd` only evaluated histogram sign, missing the zero-line trend regime. | Classifies into: `bullish_above_zero`, `bullish_crossover_below_zero`, `bearish_below_zero`, `bearish_crossover_above_zero`, `neutral`. |
| **M1.5 Scale-Invariant Features** | Unscaled `macd_signal` caused distribution shift between low-price and high-price stocks. | Introduced `FEATURE_NAMES_V2` with `macd_signal_norm = macd_signal / Close`. |
| **M1.6 Gap-Resilient Smoothing** | Wilder RMA and EMA restarted from a single raw value after NaN/Inf gaps. | Reset consecutive valid count on any gap; require exactly `period` consecutive valid bars to reseed arithmetic mean. |
| **M1.7 Alert Validation & Regex** | Alert regex allowed embedded carets (`REL^IANCE`) and accepted invalid/unsupported symbols. | Updated regex to `^\^?[A-Z0-9][A-Z0-9._&-]{0,19}$` and enforced `resolve_instrument` before alert creation. |

---

## 3. Verification & Test Execution Results

All remediations were validated against both newly authored comprehensive unit suites and the full historical regression test suites.

### 3.1 Suite Breakdown

| Test Suite File | Tests | Status | Execution Time | Coverage Scope |
|---|---|---|---|---|
| `backend/tests/test_canonical_indicators.py` | 27 | **PASS** | 3.50s | Wilder RMA, EMA, RSI, MACD, BB (ddof=0), ATR, RVOL, VWAP, consumer parity, gap resets |
| `backend/tests/test_exchange_calendar_and_symbols.py` | 20 | **PASS** | 4.40s | ARTH-50 dual cohort, SHA-256 literal fixture, exchange sessions, coverage bounds, aliases, demerger |
| `backend/tests/test_m25_data_foundation.py` | 8 | **PASS** | 13.00s | Unified normalization parity, physical invariants, batch index routing, feature abstention |
| `backend/tests/test_g1_production_hardening.py` | 39 | **PASS** | 14.45s | Holiday fixtures, session hours, rate limits, quota governor, invite hashing, error sanitization |
| `backend/tests/` (Full Backend Suite) | **337** | **PASS** | 62.76s | Entire backend pytest suite (zero failures, zero regressions) |
| `test_integration.py` | 86 | **PASS** | 14.12s | Risk engine DataFrame contracts, multi-provider routing, cache roundtrip |
| `test_stabilization.py` | 88 | **PASS** | 18.25s | yfinance import enforcement, NSE circuit breaker, provider capability checks |
| `test_phase3.py` | 91 | **PASS** | 2.52s | Trust layer, sliding-window rate limiting, outcome tracker, cache eviction |
| `test_adversarial_auth.py` | Pass | **PASS** | 9.00s | Auth edge cases and token security |
| `test_cors.py` | 12 | **PASS** | 0.01s | CORS headers and origin restrictions |
| **Total Test Count** | **614** | **100% PASS** | — | **Zero regressions across entire ARTH platform** |

---

## 4. Git State & Cleanliness

- **Branch:** `feature/stage2-m1-canonical-indicators`
- **Tracked Modifications:**
  - `backend/app/api/v1/alerts.py`
  - `backend/app/core/market_calendar.py`
  - `backend/app/core/symbols.py`
  - `backend/app/data/market_data_provider.py`
  - `backend/app/engines/market/indicators.py`
  - `backend/app/engines/prediction/feature_engineering.py`
  - `backend/tests/test_v32_hardening.py`
  - `test_integration.py`
- **New Files Added:**
  - `backend/app/core/arth50.py`
  - `backend/app/core/exchange_calendar.py`
  - `backend/app/core/indicators.py`
  - `backend/app/core/instrument_resolver.py`
  - `backend/tests/test_canonical_indicators.py`
  - `backend/tests/test_exchange_calendar_and_symbols.py`
  - `backend/tests/test_m25_data_foundation.py`
  - `docs/stage2/02_5_data_foundation_remediation.md`
- **Secrets & Credentials:** None added, exposed, or committed.
- **Production Status:** Ready for code review and PR.
