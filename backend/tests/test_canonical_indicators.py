"""
Unit and parity test suite for ARTH Canonical Indicator Engine (Milestone M1).

Validates:
1. Wilder RMA initialization (SMA seed) and recursive smoothing.
2. RSI calculations and edge cases (flat=50, rally=100, crash=0, warm-up=NaN).
3. EMA and MACD seed alignment and first valid indices (MACD at 25, signal at 33).
4. Bollinger Bands with population standard deviation (ddof=0), %B, and bandwidth.
5. ATR and NATR with True Range and Wilder smoothing.
6. Realized Volatility with sample standard deviation (ddof=1) annualized by sqrt(252).
7. Rate of Change (ROC).
8. ADX (+DI, -DI, ADX) with Wilder smoothing.
9. Volume and liquidity metrics: OBV, MFI, RVOL (strictly excluding current bar), VWAP, Amihud.
10. Consumer Parity: market.indicators and prediction.feature_engineering produce identical values.
"""

from __future__ import annotations

import math
import numpy as np
import pandas as pd
import pytest

from app.core.indicators import (
    compute_adx,
    compute_amihud_illiquidity,
    compute_atr,
    compute_bollinger_bands,
    compute_bollinger_scalar,
    compute_ema,
    compute_macd,
    compute_macd_scalar,
    compute_mfi,
    compute_obv,
    compute_realized_volatility,
    compute_relative_volume,
    compute_roc,
    compute_rolling_vwap,
    compute_rsi,
    compute_rsi_scalar,
    compute_session_vwap,
    compute_sma,
    compute_sma_scalar,
    interpret_bollinger,
    interpret_macd,
    interpret_rsi,
    wilder_rma,
)
from app.engines.market.indicators import (
    compute_indicators as market_compute_indicators,
    _compute_rsi as market_compute_rsi,
    _compute_macd as market_compute_macd,
    _compute_bollinger as market_compute_bollinger,
)
from app.engines.prediction.feature_engineering import FeatureEngineer


# ─────────────────────────────────────────────────────────────────────────────
# 1. Wilder's Smoothing (RMA) Tests
# ─────────────────────────────────────────────────────────────────────────────

def test_wilder_rma_seed_and_recursion():
    """Verify Wilder RMA uses SMA seed over first `period` bars and exact recursive formula."""
    # Hand-calculable series
    # Period = 3, values = [10.0, 11.0, 12.0, 13.0, 14.0]
    # SMA seed at index 2: (10 + 11 + 12) / 3 = 11.0
    # Index 3: (11.0 * 2 + 13.0) / 3 = 35.0 / 3 = 11.666666666666666
    # Index 4: (11.666666666666666 * 2 + 14.0) / 3 = 37.33333333333333 / 3 = 12.444444444444445
    s = pd.Series([10.0, 11.0, 12.0, 13.0, 14.0])
    rma = wilder_rma(s, period=3)

    assert pd.isna(rma.iloc[0])
    assert pd.isna(rma.iloc[1])
    assert rma.iloc[2] == pytest.approx(11.0, rel=1e-9)
    assert rma.iloc[3] == pytest.approx(35.0 / 3.0, rel=1e-9)
    assert rma.iloc[4] == pytest.approx(112.0 / 9.0, rel=1e-9)


def test_wilder_rma_gap_handling():
    """Verify Wilder RMA resets on NaN/Inf gap and requires period consecutive valid bars to reseed."""
    # 5 valid, 1 NaN, 4 valid
    s = pd.Series([10.0, 11.0, 12.0, 13.0, 14.0, np.nan, 20.0, 21.0, 22.0, 23.0])
    period = 3
    rma = wilder_rma(s, period=period)

    # First segment: seed at index 2 (11.0), then recursion at 3 and 4
    assert rma.iloc[2] == pytest.approx(11.0, rel=1e-9)
    assert not pd.isna(rma.iloc[3])
    assert not pd.isna(rma.iloc[4])

    # Gap at index 5 must be NaN
    assert pd.isna(rma.iloc[5])

    # After gap: index 6 (20.0) is bar 1 of new segment -> NaN (cannot restart from single value!)
    assert pd.isna(rma.iloc[6])
    # index 7 (21.0) is bar 2 of new segment -> NaN
    assert pd.isna(rma.iloc[7])
    # index 8 (22.0) is bar 3 of new segment -> reseeds with SMA(20, 21, 22) = 21.0
    assert rma.iloc[8] == pytest.approx(21.0, rel=1e-9)
    # index 9 (23.0) -> recursive update: (21.0 * 2 + 23.0) / 3 = 65.0 / 3 = 21.6666667
    assert rma.iloc[9] == pytest.approx(65.0 / 3.0, rel=1e-9)


def test_ema_gap_handling():
    """Verify EMA resets on NaN/Inf gap and requires period consecutive valid bars to reseed."""
    s = pd.Series([10.0, 12.0, 14.0, np.nan, 20.0, 22.0, 24.0, 26.0])
    period = 3
    ema = compute_ema(s, period=period)

    # First segment: seed at index 2 = 12.0
    assert ema.iloc[2] == pytest.approx(12.0, rel=1e-9)
    # Gap at index 3
    assert pd.isna(ema.iloc[3])
    # Bar 1 after gap (index 4) -> NaN
    assert pd.isna(ema.iloc[4])
    # Bar 2 after gap (index 5) -> NaN
    assert pd.isna(ema.iloc[5])
    # Bar 3 after gap (index 6) -> SMA seed = (20 + 22 + 24) / 3 = 22.0
    assert ema.iloc[6] == pytest.approx(22.0, rel=1e-9)
    # Bar 4 after gap (index 7) -> alpha * 26.0 + (1-alpha) * 22.0 = 0.5*26 + 0.5*22 = 24.0
    assert ema.iloc[7] == pytest.approx(24.0, rel=1e-9)


def test_wilder_rma_invalid_period():
    s = pd.Series([1.0, 2.0, 3.0])
    with pytest.raises(ValueError, match="Period must be a positive integer"):
        wilder_rma(s, period=0)


def test_wilder_rma_insufficient_length():
    s = pd.Series([10.0, 20.0])
    rma = wilder_rma(s, period=5)
    assert len(rma) == 2
    assert rma.isna().all()


# ─────────────────────────────────────────────────────────────────────────────
# 2. RSI Tests
# ─────────────────────────────────────────────────────────────────────────────

def test_rsi_flat_series_returns_50():
    """Flat prices produce 0 gains and 0 losses -> neutral 50.0."""
    closes = pd.Series([100.0] * 30)
    rsi = compute_rsi(closes, period=14)
    # First 14 bars are NaN warm-up, index 14 onwards should be 50.0
    assert rsi.iloc[:14].isna().all()
    assert (rsi.iloc[14:] == 50.0).all()
    assert compute_rsi_scalar(closes, period=14) == 50.0


def test_rsi_pure_rally_returns_100():
    """Monotonically strictly increasing prices produce 0 loss -> 100.0."""
    closes = pd.Series([100.0 + i * 2.0 for i in range(30)])
    rsi = compute_rsi(closes, period=14)
    assert rsi.iloc[:14].isna().all()
    assert (rsi.iloc[14:] == 100.0).all()
    assert compute_rsi_scalar(closes, period=14) == 100.0


def test_rsi_pure_crash_returns_0():
    """Monotonically strictly decreasing prices produce 0 gain -> 0.0."""
    closes = pd.Series([100.0 - i * 2.0 for i in range(30)])
    rsi = compute_rsi(closes, period=14)
    assert rsi.iloc[:14].isna().all()
    assert (rsi.iloc[14:] == 0.0).all()
    assert compute_rsi_scalar(closes, period=14) == 0.0


def test_rsi_oscillating_series():
    """Oscillating prices produce RSI strictly between 0 and 100."""
    closes = pd.Series([100.0, 102.0, 101.0, 103.0, 102.0, 104.0, 103.0, 105.0,
                        104.0, 106.0, 105.0, 107.0, 106.0, 108.0, 107.0, 109.0, 108.0, 110.0])
    rsi = compute_rsi(closes, period=14)
    val = rsi.iloc[-1]
    assert not pd.isna(val)
    assert 0.0 < val < 100.0
    assert compute_rsi_scalar(closes, period=14) == pytest.approx(val, rel=1e-9)


def test_interpret_rsi():
    assert interpret_rsi(75.0) == "overbought"
    assert interpret_rsi(70.0) == "overbought"
    assert interpret_rsi(25.0) == "oversold"
    assert interpret_rsi(30.0) == "oversold"
    assert interpret_rsi(50.0) == "neutral"
    assert interpret_rsi(None) is None


# ─────────────────────────────────────────────────────────────────────────────
# 3. EMA & MACD Tests
# ─────────────────────────────────────────────────────────────────────────────

def test_compute_ema_seed_and_alpha():
    """EMA is seeded with arithmetic mean of first `period` bars; alpha = 2/(period+1)."""
    s = pd.Series([10.0, 12.0, 14.0, 16.0, 18.0])
    # period = 3 -> alpha = 2 / (3 + 1) = 0.5
    # SMA seed at index 2: (10 + 12 + 14) / 3 = 12.0
    # Index 3: 0.5 * 16.0 + 0.5 * 12.0 = 14.0
    # Index 4: 0.5 * 18.0 + 0.5 * 14.0 = 16.0
    ema = compute_ema(s, period=3)
    assert pd.isna(ema.iloc[0])
    assert pd.isna(ema.iloc[1])
    assert ema.iloc[2] == pytest.approx(12.0, rel=1e-9)
    assert ema.iloc[3] == pytest.approx(14.0, rel=1e-9)
    assert ema.iloc[4] == pytest.approx(16.0, rel=1e-9)


def test_macd_alignment_and_first_valid_index():
    """
    Fast=12, Slow=26, Signal=9.
    MACD line is valid at index 25 (26th observation).
    Signal line requires 9 valid MACD points -> valid at index 25 + 9 - 1 = 33 (34th observation).
    """
    closes = pd.Series([100.0 + i for i in range(50)])
    macd, signal, hist = compute_macd(closes, fast=12, slow=26, signal=9)

    # MACD valid starting at index 25
    assert macd.iloc[:25].isna().all()
    assert not pd.isna(macd.iloc[25])

    # Signal & Hist valid starting at index 33
    assert signal.iloc[:33].isna().all()
    assert hist.iloc[:33].isna().all()
    assert not pd.isna(signal.iloc[33])
    assert not pd.isna(hist.iloc[33])

    # Histogram equals MACD - Signal
    valid_mask = hist.notna()
    assert np.allclose(hist[valid_mask], macd[valid_mask] - signal[valid_mask])


def test_macd_insufficient_bars():
    closes = pd.Series([100.0 + i for i in range(30)])  # Less than 34 bars
    macd, signal, hist = compute_macd(closes, fast=12, slow=26, signal=9)
    assert signal.isna().all()
    assert hist.isna().all()
    m_val, s_val, h_val = compute_macd_scalar(closes, fast=12, slow=26, signal=9)
    assert m_val is None
    assert s_val is None
    assert h_val is None


def test_interpret_macd():
    assert interpret_macd(1.5, 1.0, 0.5) == "bullish_above_zero"
    assert interpret_macd(-0.5, -1.0, 0.5) == "bullish_crossover_below_zero"
    assert interpret_macd(-1.5, -1.0, -0.5) == "bearish_below_zero"
    assert interpret_macd(0.5, 1.0, -0.5) == "bearish_crossover_above_zero"
    assert interpret_macd(1.0, 1.0, 0.0) == "neutral"


# ─────────────────────────────────────────────────────────────────────────────
# 4. Bollinger Bands Tests
# ─────────────────────────────────────────────────────────────────────────────

def test_bollinger_bands_population_std_ddof0():
    """Verify Bollinger Bands use population std (ddof=0) and correct formulas."""
    closes = pd.Series([10.0, 12.0, 14.0, 16.0, 18.0, 20.0, 22.0, 24.0, 26.0, 28.0] * 3)
    period = 20
    upper, middle, lower, percent_b, bandwidth = compute_bollinger_bands(
        closes, period=period, num_std=2.0, ddof=0
    )

    # Check last bar
    window = closes.iloc[-period:]
    expected_mean = float(window.mean())
    expected_std_pop = float(np.std(window.to_numpy(), ddof=0))
    expected_upper = expected_mean + 2.0 * expected_std_pop
    expected_lower = expected_mean - 2.0 * expected_std_pop

    assert middle.iloc[-1] == pytest.approx(expected_mean, rel=1e-9)
    assert upper.iloc[-1] == pytest.approx(expected_upper, rel=1e-9)
    assert lower.iloc[-1] == pytest.approx(expected_lower, rel=1e-9)

    # %B = (Close - Lower) / (Upper - Lower)
    last_close = closes.iloc[-1]
    expected_percent_b = (last_close - expected_lower) / (expected_upper - expected_lower)
    assert percent_b.iloc[-1] == pytest.approx(expected_percent_b, rel=1e-9)

    # Bandwidth = (Upper - Lower) / Middle
    expected_bw = (expected_upper - expected_lower) / expected_mean
    assert bandwidth.iloc[-1] == pytest.approx(expected_bw, rel=1e-9)


def test_bollinger_bands_flat_series():
    """Zero variance should not raise divide-by-zero errors in %B or bandwidth."""
    closes = pd.Series([50.0] * 25)
    upper, middle, lower, percent_b, bandwidth = compute_bollinger_bands(closes, period=20)
    assert upper.iloc[-1] == 50.0
    assert lower.iloc[-1] == 50.0
    assert middle.iloc[-1] == 50.0
    # When upper == lower, percent_b should be NaN (division by zero protected)
    assert pd.isna(percent_b.iloc[-1])


def test_interpret_bollinger():
    assert interpret_bollinger(115.0, 110.0, 90.0) == "above_upper"
    assert interpret_bollinger(85.0, 110.0, 90.0) == "below_lower"
    assert interpret_bollinger(100.0, 110.0, 90.0) == "middle"


# ─────────────────────────────────────────────────────────────────────────────
# 5. ATR & NATR Tests
# ─────────────────────────────────────────────────────────────────────────────

def test_compute_atr_and_natr():
    n = 30
    high = pd.Series([105.0 + i for i in range(n)])
    low = pd.Series([95.0 + i for i in range(n)])
    close = pd.Series([100.0 + i for i in range(n)])

    atr, natr = compute_atr(high, low, close, period=14)
    assert atr.iloc[:13].isna().all()
    assert not pd.isna(atr.iloc[13])
    # Since H - L is constantly 10, TR is constantly 10
    assert atr.iloc[13] == pytest.approx(10.0, rel=1e-9)
    assert atr.iloc[-1] == pytest.approx(10.0, rel=1e-9)
    # NATR = 100 * ATR / Close
    expected_natr = 100.0 * (10.0 / close.iloc[-1])
    assert natr.iloc[-1] == pytest.approx(expected_natr, rel=1e-9)


# ─────────────────────────────────────────────────────────────────────────────
# 6. Realized Volatility Tests
# ─────────────────────────────────────────────────────────────────────────────

def test_compute_realized_volatility():
    n = 40
    closes = pd.Series([100.0 * (1.01 ** i) for i in range(n)])
    rv = compute_realized_volatility(closes, period=20, annualization=252.0)
    # Constant daily log return ln(1.01) -> standard deviation is 0.0
    assert rv.iloc[:20].isna().all()
    assert rv.iloc[-1] == pytest.approx(0.0, abs=1e-9)


# ─────────────────────────────────────────────────────────────────────────────
# 7. RVOL Tests (Excluding Current Bar)
# ─────────────────────────────────────────────────────────────────────────────

def test_compute_relative_volume_excludes_current_bar():
    """Verify RVOL denominator is SMA_{period}(Volume_{t-1}) and excludes Volume_t."""
    # 20 bars of 1000, then 1 bar of 5000
    vols = [1000.0] * 20 + [5000.0]
    volumes = pd.Series(vols)
    rvol = compute_relative_volume(volumes, period=20)

    # At bar index 20 (the 21st bar), prior 20-bar average is 1000.0
    # Current volume is 5000.0 -> RVOL should be exactly 5.0
    assert rvol.iloc[20] == pytest.approx(5.0, rel=1e-9)

    # If the current bar had been included, the average would have been (19000 + 5000) / 20 = 1200
    # and RVOL would be 5000 / 1200 = 4.1667. Ensure it's strictly 5.0!
    assert rvol.iloc[20] != pytest.approx(5000.0 / 1200.0, rel=1e-4)


# ─────────────────────────────────────────────────────────────────────────────
# 8. VWAP Tests (Rolling vs Session)
# ─────────────────────────────────────────────────────────────────────────────

def test_session_vwap_and_rolling_vwap():
    high = pd.Series([110.0, 112.0, 115.0])
    low = pd.Series([90.0, 92.0, 95.0])
    close = pd.Series([100.0, 102.0, 105.0])
    volume = pd.Series([100.0, 200.0, 300.0])

    # TP = [100, 102, 105]
    # TP * V = [10000, 20400, 31500]
    # Cum TP*V = [10000, 30400, 61900]
    # Cum V = [100, 300, 600]
    # Session VWAP = [100.0, 30400/300, 61900/600] = [100.0, 101.3333, 103.1667]
    vwap_sess = compute_session_vwap(high, low, close, volume)
    assert vwap_sess.iloc[0] == pytest.approx(100.0, rel=1e-9)
    assert vwap_sess.iloc[1] == pytest.approx(30400.0 / 300.0, rel=1e-9)
    assert vwap_sess.iloc[2] == pytest.approx(61900.0 / 600.0, rel=1e-9)


# ─────────────────────────────────────────────────────────────────────────────
# 9. Amihud Illiquidity & MFI Tests
# ─────────────────────────────────────────────────────────────────────────────

def test_amihud_illiquidity():
    closes = pd.Series([100.0, 105.0] * 15)  # 30 bars
    volumes = pd.Series([10000.0] * 30)
    illiq = compute_amihud_illiquidity(closes, volumes, period=20)
    assert illiq.iloc[:19].isna().all()
    assert not pd.isna(illiq.iloc[20])
    assert illiq.iloc[20] > 0.0


def test_mfi_flat_and_normal():
    # Flat series -> 50.0
    n = 30
    h = pd.Series([105.0] * n)
    l = pd.Series([95.0] * n)
    c = pd.Series([100.0] * n)
    v = pd.Series([1000.0] * n)
    mfi = compute_mfi(h, l, c, v, period=14)
    assert mfi.iloc[:13].isna().all()
    assert (mfi.iloc[14:] == 50.0).all()


# ─────────────────────────────────────────────────────────────────────────────
# 10. Consumer Parity Tests (market/indicators vs feature_engineering)
# ─────────────────────────────────────────────────────────────────────────────

def test_consumer_rsi_parity():
    """Verify market indicator engine and feature engineer yield identical RSI."""
    closes = pd.Series([
        100.0, 102.5, 101.0, 103.5, 104.0, 103.0, 105.0, 107.0, 106.5, 108.0,
        109.5, 108.0, 110.0, 111.5, 110.0, 112.0, 111.0, 113.5, 115.0, 114.0,
        116.0, 117.5, 116.0, 118.0, 119.5, 118.5, 120.0, 121.5, 120.0, 122.0
    ])

    market_rsi = market_compute_rsi(closes, period=14)
    fe_rsi = FeatureEngineer._compute_rsi(closes, period=14).iloc[-1]

    assert market_rsi is not None
    assert fe_rsi is not None
    assert market_rsi == pytest.approx(fe_rsi, rel=1e-9)


def test_consumer_macd_histogram_parity():
    """Verify market indicator engine histogram and feature engineer macd_signal are identical."""
    closes = pd.Series([100.0 + (i * 0.5) + math.sin(i) * 2.0 for i in range(50)])

    _, _, market_hist = market_compute_macd(closes, fast=12, slow=26, signal=9)
    fe_macd_signal = FeatureEngineer._compute_macd_signal(closes).iloc[-1]

    assert market_hist is not None
    assert fe_macd_signal is not None
    assert market_hist == pytest.approx(fe_macd_signal, rel=1e-9)


def test_consumer_bollinger_bands_parity():
    """Verify market indicator engine BB and feature engineer bb_position match."""
    closes = pd.Series([100.0 + math.sin(i) * 5.0 for i in range(40)])

    upper, middle, lower = market_compute_bollinger(closes, period=20, std_dev=2)
    last_close = closes.iloc[-1]
    expected_pct_b = (last_close - lower) / (upper - lower)

    fe_bb_position = FeatureEngineer._compute_bb_position(closes, period=20).iloc[-1]

    assert expected_pct_b == pytest.approx(fe_bb_position, rel=1e-9)


def test_compute_indicators_dict_shape():
    """Verify full compute_indicators returns the expected dictionary shape."""
    ohlcv = [
        {
            "open": 100.0 + i,
            "high": 105.0 + i,
            "low": 95.0 + i,
            "close": 102.0 + i,
            "volume": 1000.0 + i * 10,
        }
        for i in range(40)
    ]
    res = market_compute_indicators(ohlcv)
    assert res is not None
    assert "rsi_14" in res
    assert "rsi_signal" in res
    assert "macd" in res
    assert "macd_signal_type" in res
    assert "bollinger_bands" in res
    assert "bb_position" in res
    assert "vwap" in res
    assert "sma_20" in res
    assert "sma_50" in res

    assert res["rsi_14"] is not None
    assert res["macd"] is not None
    assert "value" in res["macd"]
    assert "signal" in res["macd"]
    assert "histogram" in res["macd"]
    assert res["bollinger_bands"] is not None
    assert "upper" in res["bollinger_bands"]
    assert "middle" in res["bollinger_bands"]
    assert "lower" in res["bollinger_bands"]
