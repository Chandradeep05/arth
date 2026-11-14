"""
Technical indicator computation engine.

Computes RSI, MACD, Bollinger Bands, VWAP, and moving averages
from OHLCV data. Each indicator includes an interpretive signal
(e.g., "overbought", "bullish_crossover") for the frontend.

Delegates core mathematical computations to the canonical indicator engine
in app.core.indicators.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

import numpy as np
import pandas as pd

from app.core.indicators import (
    compute_bollinger_scalar,
    compute_macd_scalar,
    compute_rolling_vwap,
    compute_rsi_scalar,
    compute_sma_scalar,
    interpret_bollinger,
    interpret_macd,
    interpret_rsi,
)
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
        if macd_val is not None and signal_val is not None and hist_val is not None:
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
        if bb_upper is not None and bb_middle is not None and bb_lower is not None:
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

        # ── VWAP (Rolling 20-bar VWAP for daily bars; M1.3) ──
        vwap_20d = _compute_rolling_vwap(df, period=20)
        result["vwap_20d"] = round(vwap_20d, 2) if vwap_20d is not None else None
        result["vwap"] = result["vwap_20d"]  # Preserved backwards-compatibility alias

        # ── Moving Averages ──
        result["sma_20"] = _sma(df["close"], 20)
        result["sma_50"] = _sma(df["close"], 50)

        return result

    except Exception as e:
        logger.error("indicator_computation_failed", error=str(e))
        return None


# ── RSI ──
def _compute_rsi(closes: pd.Series, period: int = 14) -> Optional[float]:
    """Compute Relative Strength Index using canonical Wilder RMA."""
    return compute_rsi_scalar(closes, period=period)


def _interpret_rsi(rsi: Optional[float]) -> Optional[str]:
    return interpret_rsi(rsi)


# ── MACD ──
def _compute_macd(
    closes: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9
) -> tuple[Optional[float], Optional[float], Optional[float]]:
    """Compute MACD, Signal, and Histogram using canonical SMA-seeded EMA."""
    return compute_macd_scalar(closes, fast=fast, slow=slow, signal=signal)


def _interpret_macd(macd: float, signal: float, histogram: float) -> str:
    return interpret_macd(macd, signal, histogram)


# ── Bollinger Bands ──
def _compute_bollinger(
    closes: pd.Series, period: int = 20, std_dev: int = 2
) -> tuple[Optional[float], Optional[float], Optional[float]]:
    """Compute Bollinger Bands using population standard deviation (ddof=0)."""
    return compute_bollinger_scalar(closes, period=period, num_std=float(std_dev), ddof=0)


def _interpret_bollinger(price: float, upper: float, lower: float) -> str:
    return interpret_bollinger(price, upper, lower)


# ── VWAP ──
def _compute_rolling_vwap(df: pd.DataFrame, period: int = 20) -> Optional[float]:
    """Compute 20-bar rolling Volume Weighted Average Price for daily bars."""
    try:
        if "volume" not in df.columns or df["volume"].sum() == 0:
            return None
        s = compute_rolling_vwap(df["high"], df["low"], df["close"], df["volume"], period=period)
        val = s.iloc[-1]
        return float(val) if not pd.isna(val) else None
    except Exception:
        return None


def _compute_vwap(df: pd.DataFrame) -> Optional[float]:
    """Backwards-compatibility alias delegating to 20-bar rolling VWAP."""
    return _compute_rolling_vwap(df, period=20)


# ── Simple Moving Average ──
def _sma(closes: pd.Series, period: int) -> Optional[float]:
    return compute_sma_scalar(closes, period=period)

