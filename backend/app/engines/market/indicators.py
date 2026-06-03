"""
Technical indicator computation engine.

Computes RSI, MACD, Bollinger Bands, VWAP, and moving averages
from OHLCV data. Each indicator includes an interpretive signal
(e.g., "overbought", "bullish_crossover") for the frontend.

Uses pandas-ta for robust calculations.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

import numpy as np
import pandas as pd

from app.core.logging import get_logger

logger = get_logger(__name__)


def compute_indicators(ohlcv_data: list[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """
    Compute technical indicators from OHLCV data.

    Args:
        ohlcv_data: List of OHLCV bars from the data adapter

    Returns:
        Dict with all computed indicators and interpretive signals
    """
    if not ohlcv_data or len(ohlcv_data) < 26:
        logger.warning("insufficient_data_for_indicators", bars=len(ohlcv_data) if ohlcv_data else 0)
        return None

    try:
        df = pd.DataFrame(ohlcv_data)
        df["close"] = df["close"].astype(float)
        df["high"] = df["high"].astype(float)
        df["low"] = df["low"].astype(float)
        df["open"] = df["open"].astype(float)
        df["volume"] = df["volume"].astype(float)

        result: Dict[str, Any] = {}

        # ── RSI (14-period) ──
        rsi = _compute_rsi(df["close"], period=14)
        result["rsi_14"] = round(rsi, 2) if rsi is not None else None
        result["rsi_signal"] = _interpret_rsi(rsi)

        # ── MACD (12, 26, 9) ──
        macd_val, signal_val, hist_val = _compute_macd(df["close"])
        if macd_val is not None:
            result["macd"] = {
                "value": round(macd_val, 4),
                "signal": round(signal_val, 4),
                "histogram": round(hist_val, 4),
            }
            result["macd_signal_type"] = _interpret_macd(macd_val, signal_val, hist_val)
        else:
            result["macd"] = None
            result["macd_signal_type"] = None

        # ── Bollinger Bands (20, 2) ──
        bb_upper, bb_middle, bb_lower = _compute_bollinger(df["close"])
        if bb_upper is not None:
            last_close = float(df["close"].iloc[-1])
            result["bollinger_bands"] = {
                "upper": round(bb_upper, 2),
                "middle": round(bb_middle, 2),
                "lower": round(bb_lower, 2),
            }
            result["bb_position"] = _interpret_bollinger(last_close, bb_upper, bb_lower)
        else:
            result["bollinger_bands"] = None
            result["bb_position"] = None

        # ── VWAP ──
        vwap = _compute_vwap(df)
        result["vwap"] = round(vwap, 2) if vwap is not None else None

        # ── Moving Averages ──
        result["sma_20"] = _sma(df["close"], 20)
        result["sma_50"] = _sma(df["close"], 50)

        return result

    except Exception as e:
        logger.error("indicator_computation_failed", error=str(e))
        return None


# ── RSI ──
def _compute_rsi(closes: pd.Series, period: int = 14) -> Optional[float]:
    """Compute Relative Strength Index."""
    if len(closes) < period + 1:
        return None
    delta = closes.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    avg_gain = gain.rolling(window=period, min_periods=period).mean()
    avg_loss = loss.rolling(window=period, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    val = rsi.iloc[-1]
    return float(val) if not pd.isna(val) else None


def _interpret_rsi(rsi: Optional[float]) -> Optional[str]:
    if rsi is None:
        return None
    if rsi >= 70:
        return "overbought"
    elif rsi <= 30:
        return "oversold"
    return "neutral"


# ── MACD ──
def _compute_macd(
    closes: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9
) -> tuple[Optional[float], Optional[float], Optional[float]]:
    """Compute MACD, Signal, and Histogram."""
    if len(closes) < slow + signal:
        return None, None, None
    ema_fast = closes.ewm(span=fast, adjust=False).mean()
    ema_slow = closes.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    histogram = macd_line - signal_line
    return (
        float(macd_line.iloc[-1]),
        float(signal_line.iloc[-1]),
        float(histogram.iloc[-1]),
    )


def _interpret_macd(macd: float, signal: float, histogram: float) -> str:
    if histogram > 0 and macd > signal:
        return "bullish"
    elif histogram < 0 and macd < signal:
        return "bearish"
    return "neutral"


# ── Bollinger Bands ──
def _compute_bollinger(
    closes: pd.Series, period: int = 20, std_dev: int = 2
) -> tuple[Optional[float], Optional[float], Optional[float]]:
    """Compute Bollinger Bands."""
    if len(closes) < period:
        return None, None, None
    sma = closes.rolling(window=period).mean()
    std = closes.rolling(window=period).std()
    upper = sma + (std * std_dev)
    lower = sma - (std * std_dev)
    return float(upper.iloc[-1]), float(sma.iloc[-1]), float(lower.iloc[-1])


def _interpret_bollinger(price: float, upper: float, lower: float) -> str:
    if price >= upper:
        return "above_upper"
    elif price <= lower:
        return "below_lower"
    return "middle"


# ── VWAP ──
def _compute_vwap(df: pd.DataFrame) -> Optional[float]:
    """Compute Volume Weighted Average Price."""
    try:
        typical_price = (df["high"] + df["low"] + df["close"]) / 3
        vwap = (typical_price * df["volume"]).cumsum() / df["volume"].cumsum()
        val = vwap.iloc[-1]
        return float(val) if not pd.isna(val) else None
    except Exception:
        return None


# ── Simple Moving Average ──
def _sma(closes: pd.Series, period: int) -> Optional[float]:
    if len(closes) < period:
        return None
    val = closes.rolling(window=period).mean().iloc[-1]
    return round(float(val), 2) if not pd.isna(val) else None
