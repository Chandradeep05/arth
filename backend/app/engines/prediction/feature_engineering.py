"""
Feature Engineering for XGBoost Prediction Model.

Builds a feature matrix from yfinance data for 5-day forward return prediction.
All features are derived from existing data sources — no additional APIs needed.

Feature groups:
  Price:     returns (1d, 5d, 20d), volatility (20d), gap
  Technical: RSI, MACD signal, BB position, VWAP deviation
  Volume:    volume ratio to 20d avg, volume trend
  Fundamental: PE, PB, market cap (log)
  Sentiment: sentiment score (from engine), news count
  Market:    NIFTY/S&P return (1d)
"""

from __future__ import annotations

import asyncio
import math
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import yfinance as yf

from app.core.logging import get_logger

logger = get_logger(__name__)
_executor = ThreadPoolExecutor(max_workers=2)


def _safe(val, default=0.0) -> float:
    """Convert to float, replacing NaN/Inf/None with default."""
    if val is None:
        return default
    try:
        f = float(val)
        return default if (math.isnan(f) or math.isinf(f)) else f
    except (TypeError, ValueError):
        return default


class FeatureEngineer:
    """Builds feature vectors from yfinance historical + fundamental data."""

    FEATURE_NAMES = [
        "return_1d", "return_5d", "return_20d",
        "volatility_20d", "gap",
        "rsi_14", "macd_signal", "bb_position",
        "volume_ratio_20d", "volume_trend_5d",
        "pe_ratio", "pb_ratio", "market_cap_log",
        "day_of_week", "month",
    ]

    async def build_features(
        self,
        symbol: str,
        period: str = "2y",
    ) -> Tuple[pd.DataFrame, pd.Series]:
        """Build feature matrix and 5-day forward return target.

        Returns:
            (X, y) — feature DataFrame and target Series, both aligned by date.
            Rows with NaN in target (last 5 days) are excluded.
        """
        loop = asyncio.get_running_loop()

        # Fetch historical data in executor (yfinance is sync)
        def _fetch():
            ticker = yf.Ticker(symbol)
            hist = ticker.history(period=period, interval="1d")
            info = ticker.info
            return hist, info

        hist, info = await loop.run_in_executor(_executor, _fetch)

        if hist is None or hist.empty or len(hist) < 30:
            raise ValueError(f"Insufficient data for {symbol}: need 30+ daily bars")

        df = hist.copy()

        # ── Price features ──
        df["return_1d"] = df["Close"].pct_change(1)
        df["return_5d"] = df["Close"].pct_change(5)
        df["return_20d"] = df["Close"].pct_change(20)
        df["volatility_20d"] = df["return_1d"].rolling(20).std()
        df["gap"] = (df["Open"] - df["Close"].shift(1)) / df["Close"].shift(1)

        # ── Technical features ──
        df["rsi_14"] = self._compute_rsi(df["Close"], 14)
        df["macd_signal"] = self._compute_macd_signal(df["Close"])
        df["bb_position"] = self._compute_bb_position(df["Close"], 20)

        # ── Volume features ──
        vol_sma20 = df["Volume"].rolling(20).mean()
        df["volume_ratio_20d"] = df["Volume"] / vol_sma20.replace(0, np.nan)
        df["volume_trend_5d"] = df["Volume"].pct_change(5)

        # ── Fundamental features (static, broadcast) ──
        pe = _safe(info.get("trailingPE"), np.nan)
        pb = _safe(info.get("priceToBook"), np.nan)
        mc = _safe(info.get("marketCap"), 0)
        mc_log = math.log10(mc) if mc > 0 else np.nan

        df["pe_ratio"] = pe
        df["pb_ratio"] = pb
        df["market_cap_log"] = mc_log

        # ── Calendar features ──
        df["day_of_week"] = df.index.dayofweek
        df["month"] = df.index.month

        # ── Target: 5-day forward return ──
        df["target_5d"] = df["Close"].pct_change(5).shift(-5)

        # Select feature columns and drop NaN rows
        feature_cols = self.FEATURE_NAMES
        df_features = df[feature_cols + ["target_5d"]].dropna()

        if len(df_features) < 20:
            raise ValueError(f"Too few complete rows for {symbol}: {len(df_features)}")

        X = df_features[feature_cols]
        y = df_features["target_5d"]

        return X, y

    async def build_live_features(self, symbol: str) -> Dict[str, float]:
        """Build feature vector for the most recent trading day (for prediction).

        Returns a dict of feature_name -> value for model input.
        """
        loop = asyncio.get_running_loop()

        def _fetch():
            ticker = yf.Ticker(symbol)
            hist = ticker.history(period="3mo", interval="1d")
            info = ticker.info
            return hist, info

        hist, info = await loop.run_in_executor(_executor, _fetch)

        if hist is None or hist.empty or len(hist) < 25:
            raise ValueError(f"Insufficient recent data for {symbol}")

        df = hist.copy()

        # Compute all features on last 3mo, take the last row
        df["return_1d"] = df["Close"].pct_change(1)
        df["return_5d"] = df["Close"].pct_change(5)
        df["return_20d"] = df["Close"].pct_change(20)
        df["volatility_20d"] = df["return_1d"].rolling(20).std()
        df["gap"] = (df["Open"] - df["Close"].shift(1)) / df["Close"].shift(1)
        df["rsi_14"] = self._compute_rsi(df["Close"], 14)
        df["macd_signal"] = self._compute_macd_signal(df["Close"])
        df["bb_position"] = self._compute_bb_position(df["Close"], 20)

        vol_sma20 = df["Volume"].rolling(20).mean()
        df["volume_ratio_20d"] = df["Volume"] / vol_sma20.replace(0, np.nan)
        df["volume_trend_5d"] = df["Volume"].pct_change(5)

        pe = _safe(info.get("trailingPE"), np.nan)
        pb = _safe(info.get("priceToBook"), np.nan)
        mc = _safe(info.get("marketCap"), 0)

        df["pe_ratio"] = pe
        df["pb_ratio"] = pb
        df["market_cap_log"] = math.log10(mc) if mc > 0 else np.nan
        df["day_of_week"] = df.index.dayofweek
        df["month"] = df.index.month

        last = df.iloc[-1]
        features = {}
        for col in self.FEATURE_NAMES:
            features[col] = _safe(last.get(col), 0.0)

        return features

    # ── Technical indicator helpers ──

    @staticmethod
    def _compute_rsi(close: pd.Series, period: int = 14) -> pd.Series:
        """Compute RSI (0-100)."""
        delta = close.diff()
        gain = delta.where(delta > 0, 0.0).rolling(period).mean()
        loss = (-delta.where(delta < 0, 0.0)).rolling(period).mean()
        rs = gain / loss.replace(0, np.nan)
        return 100 - (100 / (1 + rs))

    @staticmethod
    def _compute_macd_signal(close: pd.Series) -> pd.Series:
        """MACD signal line crossover value (MACD - Signal)."""
        ema12 = close.ewm(span=12, adjust=False).mean()
        ema26 = close.ewm(span=26, adjust=False).mean()
        macd = ema12 - ema26
        signal = macd.ewm(span=9, adjust=False).mean()
        return macd - signal

    @staticmethod
    def _compute_bb_position(close: pd.Series, period: int = 20) -> pd.Series:
        """Position within Bollinger Bands (0 = lower, 1 = upper)."""
        sma = close.rolling(period).mean()
        std = close.rolling(period).std()
        upper = sma + 2 * std
        lower = sma - 2 * std
        width = (upper - lower).replace(0, np.nan)
        return (close - lower) / width
