"""
ARTH Canonical Mathematical Indicator Engine (Milestone M1 & M2.5 Remediation).

Single authoritative implementation of core quantitative and technical indicators
used across market analysis, prediction feature pipelines, and Dossier synthesis.

Mathematical Conventions & Correctness Guarantees:
- Chronologically ordered input series (oldest observation first).
- Strictly point-in-time: no calculation looks forward past observation index t.
- Gap-Resilient Wilder's Smoothing (RMA):
    - Initialized with the arithmetic mean (SMA) of the first `period` consecutive valid observations.
    - Subsequent observations follow: RMA_t = RMA_{t-1} + (x_t - RMA_{t-1}) / period
    - Gap Handling (M1.6): Any non-finite value (NaN, Inf, -Inf) resets the valid accumulation.
      After a gap, RMA outputs NaN until a complete new `period`-bar window is available to reseed.
      Never restarts smoothing from a single raw observation.
- Gap-Resilient EMA:
    - Initialized with the arithmetic mean of `period` consecutive valid observations; alpha = 2 / (period + 1).
    - After any NaN/Inf gap, requires a full `period`-bar window to reseed.
- RSI:
    - Default 14 periods with gap-resilient Wilder RMA.
    - Flat series -> 50.0; pure rally -> 100.0; pure crash -> 0.0; warm-up/gap -> NaN.
- MACD:
    - Fast=12, slow=26, signal=9. Both EMAs use SMA seeding with full gap protection.
    - Zero-line aware interpretation (M1.4): distinguishes crossovers above vs below zero.
- Bollinger Bands:
    - Default period=20, num_std=2.0 using population standard deviation (ddof=0).
- Realized Volatility:
    - Rolling sample standard deviation (ddof=1) over daily log returns, annualized by sqrt(252).
- Relative Volume (RVOL):
    - Strictly prior bar volume baseline: Volume_t / SMA_{period}(Volume_{t-1}).
- Rolling VWAP & Session VWAP:
    - Multi-day rolling 20-bar VWAP vs intraday cumulative session VWAP.
"""

from __future__ import annotations

import math
from typing import Optional, Tuple, Union

import numpy as np
import pandas as pd


# ─────────────────────────────────────────────────────────────────────────────
# 1. Gap-Resilient Wilder's Smoothing / RMA (Running Moving Average)
# ─────────────────────────────────────────────────────────────────────────────

def wilder_rma(series: Union[pd.Series, np.ndarray], period: int) -> pd.Series:
    """
    Compute Welles Wilder's Running Moving Average (RMA / SMMA) with gap resilience.

    Initialized with the simple average (SMA) of `period` consecutive valid observations.
    Subsequent observations follow the recurrence:
        RMA_t = (RMA_{t-1} * (period - 1) + x_t) / period

    Gap Handling:
    - Non-finite values (NaN, +Inf, -Inf) are treated as invalid.
    - An invalid bar breaks continuity and resets the valid observation counter.
    - Output remains NaN until `period` consecutive valid bars are available to reseed.
    - Never restarts from a single raw value.

    Args:
        series: Input numeric series or array.
        period: Smoothing lookback period (positive integer >= 1).

    Returns:
        pd.Series aligned with input index, with NaN during warm-up and gap recovery.
    """
    if period < 1:
        raise ValueError(f"Period must be a positive integer >= 1, got {period}")

    if isinstance(series, pd.Series):
        s_index = series.index
        values = series.to_numpy(dtype=np.float64, copy=True)
    else:
        values = np.asarray(series, dtype=np.float64)
        s_index = pd.RangeIndex(len(values))

    n = len(values)
    out = np.full(n, np.nan, dtype=np.float64)
    if n < period:
        return pd.Series(out, index=s_index)

    factor = float(period - 1)
    denom = float(period)
    consecutive_valid = 0

    for i in range(n):
        val = values[i]
        # Treat Inf, -Inf, and NaN as invalid
        if np.isnan(val) or np.isinf(val):
            out[i] = np.nan
            consecutive_valid = 0
        else:
            consecutive_valid += 1
            if consecutive_valid < period:
                out[i] = np.nan
            elif consecutive_valid == period:
                # Reseed with arithmetic mean of the last `period` consecutive valid values
                seed_vals = values[i - period + 1 : i + 1]
                out[i] = np.mean(seed_vals)
            else:
                prev = out[i - 1]
                if np.isnan(prev):
                    # Safety check: if prev was somehow NaN, force full reseeding
                    consecutive_valid = 1
                    out[i] = np.nan
                else:
                    out[i] = (prev * factor + val) / denom

    return pd.Series(out, index=s_index)


# ─────────────────────────────────────────────────────────────────────────────
# 2. Relative Strength Index (Wilder RSI)
# ─────────────────────────────────────────────────────────────────────────────

def compute_rsi(closes: pd.Series, period: int = 14) -> pd.Series:
    """
    Compute Wilder Relative Strength Index (RSI).

    Returns a full pandas Series aligned with input closes.
    Edge Cases (ARTH Convention):
      - Average loss == 0 and average gain > 0  -> 100.0
      - Average gain == 0 and average loss > 0  -> 0.0
      - Average gain == 0 and average loss == 0 -> 50.0
      - Insufficient observations / gap recovery -> NaN
    """
    if len(closes) < period + 1:
        return pd.Series(np.nan, index=closes.index, dtype=np.float64)

    delta = closes.diff()
    gain = delta.clip(lower=0.0)
    loss = (-delta).clip(lower=0.0)

    avg_gain = wilder_rma(gain, period)
    avg_loss = wilder_rma(loss, period)

    ag = avg_gain.to_numpy(dtype=np.float64)
    al = avg_loss.to_numpy(dtype=np.float64)
    out = np.full(len(closes), np.nan, dtype=np.float64)

    valid = ~np.isnan(ag) & ~np.isnan(al)

    # Normal case: al > 0
    normal = valid & (al > 0.0)
    rs = np.divide(ag, al, out=np.zeros_like(ag), where=normal)
    out[normal] = 100.0 - (100.0 / (1.0 + rs[normal]))

    # Edge cases
    all_gain = valid & (al == 0.0) & (ag > 0.0)
    out[all_gain] = 100.0

    all_loss = valid & (ag == 0.0) & (al > 0.0)
    out[all_loss] = 0.0

    flat = valid & (ag == 0.0) & (al == 0.0)
    out[flat] = 50.0

    return pd.Series(out, index=closes.index, dtype=np.float64)


def compute_rsi_scalar(closes: pd.Series, period: int = 14) -> Optional[float]:
    """Compute latest scalar RSI value. Returns None if ungradable / insufficient data."""
    s = compute_rsi(closes, period=period)
    if s.empty:
        return None
    val = s.iloc[-1]
    return float(val) if not pd.isna(val) else None


def interpret_rsi(rsi: Optional[float]) -> Optional[str]:
    """Interpret scalar RSI level as overbought, oversold, or neutral."""
    if rsi is None or pd.isna(rsi):
        return None
    if rsi >= 70.0:
        return "overbought"
    elif rsi <= 30.0:
        return "oversold"
    return "neutral"


# ─────────────────────────────────────────────────────────────────────────────
# 3. Gap-Resilient Exponential Moving Average (EMA) & MACD
# ─────────────────────────────────────────────────────────────────────────────

def compute_ema(series: pd.Series, period: int) -> pd.Series:
    """
    Compute Exponential Moving Average (EMA) with gap resilience.

    Alpha parameter: 2 / (period + 1).
    Initial value is the arithmetic mean of `period` consecutive valid bars.
    Any NaN or Inf breaks continuity and requires a full `period`-bar reseeding.
    """
    if period < 1:
        raise ValueError(f"EMA period must be >= 1, got {period}")

    values = series.to_numpy(dtype=np.float64, copy=True)
    n = len(values)
    out = np.full(n, np.nan, dtype=np.float64)
    if n < period:
        return pd.Series(out, index=series.index)

    alpha = 2.0 / (period + 1.0)
    one_minus_alpha = 1.0 - alpha
    consecutive_valid = 0

    for i in range(n):
        val = values[i]
        if np.isnan(val) or np.isinf(val):
            out[i] = np.nan
            consecutive_valid = 0
        else:
            consecutive_valid += 1
            if consecutive_valid < period:
                out[i] = np.nan
            elif consecutive_valid == period:
                seed_vals = values[i - period + 1 : i + 1]
                out[i] = np.mean(seed_vals)
            else:
                prev = out[i - 1]
                if np.isnan(prev):
                    consecutive_valid = 1
                    out[i] = np.nan
                else:
                    out[i] = alpha * val + one_minus_alpha * prev

    return pd.Series(out, index=series.index)


def compute_macd(
    closes: pd.Series,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> Tuple[pd.Series, pd.Series, pd.Series]:
    """
    Compute canonical MACD line, signal line, and histogram Series.

    Fast EMA: SMA-seeded over `fast` bars.
    Slow EMA: SMA-seeded over `slow` bars.
    MACD Line = Fast EMA - Slow EMA (valid from `slow - 1` onward).
    Signal Line = SMA-seeded EMA of valid MACD line over `signal` periods.
    Histogram = MACD Line - Signal Line.

    Returns:
        (macd_line, signal_line, histogram)
    """
    if len(closes) < slow + signal - 1:
        nan_s = pd.Series(np.nan, index=closes.index, dtype=np.float64)
        return nan_s, nan_s, nan_s

    fast_ema = compute_ema(closes, fast)
    slow_ema = compute_ema(closes, slow)
    macd_line = fast_ema - slow_ema

    # Signal line is EMA over valid MACD points
    signal_line = compute_ema(macd_line, signal)
    histogram = macd_line - signal_line

    return macd_line, signal_line, histogram


def compute_macd_scalar(
    closes: pd.Series,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> Tuple[Optional[float], Optional[float], Optional[float]]:
    """Compute latest scalar (macd, signal, histogram). Returns (None, None, None) on insufficient data."""
    m, s, h = compute_macd(closes, fast=fast, slow=slow, signal=signal)
    if m.empty or pd.isna(m.iloc[-1]) or pd.isna(s.iloc[-1]) or pd.isna(h.iloc[-1]):
        return None, None, None
    return float(m.iloc[-1]), float(s.iloc[-1]), float(h.iloc[-1])


def interpret_macd(
    macd: Optional[float],
    signal: Optional[float],
    histogram: Optional[float],
) -> str:
    """
    Interpret MACD state incorporating both signal-line crossover and zero-line regime (M1.4).

    Classifications:
    - bullish_above_zero: MACD > signal and MACD > 0 (strong bullish momentum)
    - bullish_crossover_below_zero: MACD > signal and MACD <= 0 (bullish reversal / crossover in oversold regime)
    - bearish_below_zero: MACD < signal and MACD < 0 (strong bearish momentum)
    - bearish_crossover_above_zero: MACD < signal and MACD >= 0 (bearish reversal / crossover in overbought regime)
    - neutral: histogram near zero or converging
    """
    if macd is None or signal is None or histogram is None:
        return "neutral"
    if pd.isna(macd) or pd.isna(signal) or pd.isna(histogram):
        return "neutral"

    eps = 1e-5
    if abs(histogram) < eps:
        return "neutral"

    if histogram > 0.0:  # macd > signal
        if macd > 0.0:
            return "bullish_above_zero"
        else:
            return "bullish_crossover_below_zero"
    elif histogram < 0.0:  # macd < signal
        if macd < 0.0:
            return "bearish_below_zero"
        else:
            return "bearish_crossover_above_zero"

    return "neutral"


# ─────────────────────────────────────────────────────────────────────────────
# 4. Bollinger Bands (Population Standard Deviation ddof=0)
# ─────────────────────────────────────────────────────────────────────────────

def compute_bollinger_bands(
    closes: pd.Series,
    period: int = 20,
    num_std: float = 2.0,
    ddof: int = 0,
) -> Tuple[pd.Series, pd.Series, pd.Series, pd.Series, pd.Series]:
    """
    Compute Bollinger Bands using population standard deviation (ddof=0).

    Returns:
        (upper_band, middle_band, lower_band, percent_b, bandwidth)
        percent_b: (Close - Lower) / (Upper - Lower)
        bandwidth: (Upper - Lower) / Middle
    """
    if len(closes) < period:
        nan_s = pd.Series(np.nan, index=closes.index, dtype=np.float64)
        return nan_s, nan_s, nan_s, nan_s, nan_s

    middle = closes.rolling(window=period, min_periods=period).mean()
    std = closes.rolling(window=period, min_periods=period).std(ddof=ddof)

    upper = middle + (std * num_std)
    lower = middle - (std * num_std)

    band_width_diff = upper - lower
    # Protect against zero / negative division in percent_b
    valid_diff = band_width_diff.replace(0.0, np.nan)
    percent_b = (closes - lower) / valid_diff

    # Bandwidth = (upper - lower) / middle
    valid_middle = middle.replace(0.0, np.nan)
    bandwidth = band_width_diff / valid_middle

    return upper, middle, lower, percent_b, bandwidth


def compute_bollinger_scalar(
    closes: pd.Series,
    period: int = 20,
    num_std: float = 2.0,
    ddof: int = 0,
) -> Tuple[Optional[float], Optional[float], Optional[float]]:
    """Compute latest scalar (upper, middle, lower) bands."""
    u, m, l, _, _ = compute_bollinger_bands(closes, period=period, num_std=num_std, ddof=ddof)
    if u.empty or pd.isna(u.iloc[-1]) or pd.isna(m.iloc[-1]) or pd.isna(l.iloc[-1]):
        return None, None, None
    return float(u.iloc[-1]), float(m.iloc[-1]), float(l.iloc[-1])


def interpret_bollinger(price: float, upper: float, lower: float) -> str:
    """Classify current price position relative to Bollinger Bands."""
    if price >= upper:
        return "above_upper"
    elif price <= lower:
        return "below_lower"
    return "middle"


# ─────────────────────────────────────────────────────────────────────────────
# 5. True Range and Average True Range (ATR & NATR)
# ─────────────────────────────────────────────────────────────────────────────

def compute_atr(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    period: int = 14,
) -> Tuple[pd.Series, pd.Series]:
    """
    Compute True Range (TR) and Wilder smoothed Average True Range (ATR & NATR).

    TR_0 = High_0 - Low_0
    TR_t = max(High_t - Low_t, |High_t - Close_{t-1}|, |Low_t - Close_{t-1}|)
    ATR = wilder_rma(TR, period)
    NATR = 100.0 * (ATR / Close)

    Returns:
        (atr, natr)
    """
    n = len(close)
    if n < period:
        nan_s = pd.Series(np.nan, index=close.index, dtype=np.float64)
        return nan_s, nan_s

    h = high.to_numpy(dtype=np.float64)
    l = low.to_numpy(dtype=np.float64)
    c = close.to_numpy(dtype=np.float64)

    tr = np.full(n, np.nan, dtype=np.float64)
    tr[0] = h[0] - l[0]

    for i in range(1, n):
        prev_c = c[i - 1]
        hl = h[i] - l[i]
        hc = abs(h[i] - prev_c)
        lc = abs(l[i] - prev_c)
        tr[i] = max(hl, hc, lc)

    tr_series = pd.Series(tr, index=close.index)
    atr = wilder_rma(tr_series, period)

    # NATR = 100 * ATR / Close
    c_safe = close.replace(0.0, np.nan)
    natr = 100.0 * (atr / c_safe)

    return atr, natr


# ─────────────────────────────────────────────────────────────────────────────
# 6. Realized Volatility
# ─────────────────────────────────────────────────────────────────────────────

def compute_realized_volatility(
    closes: pd.Series,
    period: int = 20,
    annualization: float = 252.0,
) -> pd.Series:
    """
    Compute rolling annualized realized volatility from log returns.

    r_t = ln(Close_t / Close_{t-1})
    RV_{t,n} = sqrt(annualization) * Std(r, ddof=1)
    """
    if len(closes) < period + 1:
        return pd.Series(np.nan, index=closes.index, dtype=np.float64)

    log_returns = np.log(closes / closes.shift(1))
    rolling_std = log_returns.rolling(window=period, min_periods=period).std(ddof=1)
    rv = rolling_std * math.sqrt(annualization)
    return rv


# ─────────────────────────────────────────────────────────────────────────────
# 7. Rate of Change (ROC)
# ─────────────────────────────────────────────────────────────────────────────

def compute_roc(closes: pd.Series, period: int = 20) -> pd.Series:
    """
    Compute Rate of Change percentage: ((Close_t / Close_{t-period}) - 1) * 100.
    """
    shifted = closes.shift(period).replace(0.0, np.nan)
    roc = ((closes / shifted) - 1.0) * 100.0
    return roc


# ─────────────────────────────────────────────────────────────────────────────
# 8. Directional Movement Index & ADX (Wilder RMA Smoothed)
# ─────────────────────────────────────────────────────────────────────────────

def compute_adx(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    period: int = 14,
) -> Tuple[pd.Series, pd.Series, pd.Series]:
    """
    Compute Wilder Directional Movement (+DI, -DI) and ADX.

    Returns:
        (plus_di, minus_di, adx)
    """
    n = len(close)
    if n < period * 2:
        nan_s = pd.Series(np.nan, index=close.index, dtype=np.float64)
        return nan_s, nan_s, nan_s

    h = high.to_numpy(dtype=np.float64)
    l = low.to_numpy(dtype=np.float64)

    plus_dm = np.zeros(n, dtype=np.float64)
    minus_dm = np.zeros(n, dtype=np.float64)

    for i in range(1, n):
        up_move = h[i] - h[i - 1]
        down_move = l[i - 1] - l[i]
        if up_move > down_move and up_move > 0.0:
            plus_dm[i] = up_move
        if down_move > up_move and down_move > 0.0:
            minus_dm[i] = down_move

    atr, _ = compute_atr(high, low, close, period=period)
    atr_arr = atr.to_numpy(dtype=np.float64)

    smooth_plus_dm = wilder_rma(pd.Series(plus_dm, index=close.index), period).to_numpy(dtype=np.float64)
    smooth_minus_dm = wilder_rma(pd.Series(minus_dm, index=close.index), period).to_numpy(dtype=np.float64)

    plus_di = np.full(n, np.nan, dtype=np.float64)
    minus_di = np.full(n, np.nan, dtype=np.float64)
    dx = np.full(n, np.nan, dtype=np.float64)

    valid_atr = ~np.isnan(atr_arr) & (atr_arr > 0.0)
    plus_di[valid_atr] = 100.0 * (smooth_plus_dm[valid_atr] / atr_arr[valid_atr])
    minus_di[valid_atr] = 100.0 * (smooth_minus_dm[valid_atr] / atr_arr[valid_atr])

    sum_di = plus_di + minus_di
    valid_sum = ~np.isnan(sum_di) & (sum_di > 0.0)
    dx[valid_sum] = 100.0 * (np.abs(plus_di[valid_sum] - minus_di[valid_sum]) / sum_di[valid_sum])

    adx_s = wilder_rma(pd.Series(dx, index=close.index), period)

    return (
        pd.Series(plus_di, index=close.index),
        pd.Series(minus_di, index=close.index),
        adx_s,
    )


# ─────────────────────────────────────────────────────────────────────────────
# 9. Volume & Liquidity Proxies (OBV, MFI, RVOL, Amihud)
# ─────────────────────────────────────────────────────────────────────────────

def compute_obv(closes: pd.Series, volumes: pd.Series) -> pd.Series:
    """Compute On-Balance Volume (OBV)."""
    delta = closes.diff()
    direction = np.sign(delta).fillna(0.0)
    obv = (direction * volumes).cumsum()
    return obv


def compute_mfi(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    volume: pd.Series,
    period: int = 14,
) -> pd.Series:
    """
    Compute Money Flow Index (MFI).
    Typical Price = (High + Low + Close) / 3
    Raw Money Flow = Typical Price * Volume
    """
    tp = (high + low + close) / 3.0
    rmf = tp * volume
    tp_diff = tp.diff()

    pos_flow = rmf.where(tp_diff > 0.0, 0.0)
    neg_flow = rmf.where(tp_diff < 0.0, 0.0)

    pos_mf = pos_flow.rolling(window=period, min_periods=period).sum()
    neg_mf = neg_flow.rolling(window=period, min_periods=period).sum()

    mfi = np.full(len(close), np.nan, dtype=np.float64)
    pmf = pos_mf.to_numpy(dtype=np.float64)
    nmf = neg_mf.to_numpy(dtype=np.float64)

    valid = ~np.isnan(pmf) & ~np.isnan(nmf)
    normal = valid & (nmf > 0.0)
    mr = np.divide(pmf, nmf, out=np.zeros_like(pmf), where=normal)
    mfi[normal] = 100.0 - (100.0 / (1.0 + mr[normal]))

    all_pos = valid & (nmf == 0.0) & (pmf > 0.0)
    mfi[all_pos] = 100.0

    all_neg = valid & (pmf == 0.0) & (nmf > 0.0)
    mfi[all_neg] = 0.0

    flat = valid & (pmf == 0.0) & (nmf == 0.0)
    mfi[flat] = 50.0

    return pd.Series(mfi, index=close.index)


def compute_relative_volume(volumes: pd.Series, period: int = 20) -> pd.Series:
    """
    Compute Relative Volume (RVOL) strictly excluding the current bar:
        RVOL_t = Volume_t / SMA_{period}(Volume_{t-1})
    """
    prior_avg = volumes.shift(1).rolling(window=period, min_periods=period).mean()
    rvol = volumes / prior_avg.replace(0.0, np.nan)
    return rvol


def compute_rolling_vwap(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    volume: pd.Series,
    period: int = 20,
) -> pd.Series:
    """
    Compute Rolling Multi-Day VWAP:
        VWAP_{t,n} = sum_{i=t-n+1}^t (TP_i * V_i) / sum_{i=t-n+1}^t (V_i)
    """
    tp = (high + low + close) / 3.0
    tp_vol = tp * volume
    sum_tp_vol = tp_vol.rolling(window=period, min_periods=period).sum()
    sum_vol = volume.rolling(window=period, min_periods=period).sum()
    return sum_tp_vol / sum_vol.replace(0.0, np.nan)


def compute_session_vwap(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    volume: pd.Series,
) -> pd.Series:
    """
    Compute cumulative VWAP over the supplied intraday series (session VWAP).
    """
    tp = (high + low + close) / 3.0
    cum_tp_vol = (tp * volume).cumsum()
    cum_vol = volume.cumsum()
    return cum_tp_vol / cum_vol.replace(0.0, np.nan)


def compute_amihud_illiquidity(
    closes: pd.Series,
    volumes: pd.Series,
    period: int = 20,
) -> pd.Series:
    """
    Compute rolling Amihud illiquidity proxy:
        ILLIQ_t = |r_t| / (Price_t * Volume_t)
        ILLIQ_{t,n} = (1/n) * sum_{i=t-n+1}^t ILLIQ_i
    """
    abs_return = np.abs(closes.pct_change(1))
    dollar_vol = closes * volumes
    safe_dollar_vol = dollar_vol.replace(0.0, np.nan)
    daily_illiq = abs_return / safe_dollar_vol
    return daily_illiq.rolling(window=period, min_periods=period).mean()


# ─────────────────────────────────────────────────────────────────────────────
# 10. Simple Moving Average (SMA)
# ─────────────────────────────────────────────────────────────────────────────

def compute_sma(closes: pd.Series, period: int) -> pd.Series:
    """Compute Simple Moving Average."""
    return closes.rolling(window=period, min_periods=period).mean()


def compute_sma_scalar(closes: pd.Series, period: int) -> Optional[float]:
    """Compute latest scalar SMA rounded to 2 decimal places."""
    s = compute_sma(closes, period=period)
    if s.empty:
        return None
    val = s.iloc[-1]
    return round(float(val), 2) if not pd.isna(val) else None
