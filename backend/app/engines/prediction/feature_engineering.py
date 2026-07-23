"""
Feature Engineering for XGBoost Prediction Model.

Builds a feature matrix from market data for 5-day forward return prediction.
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
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from app.core.logging import get_logger
from app.data.market_data_provider import market_data, DataStatus


logger = get_logger(__name__)


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
    """Builds feature vectors from historical + fundamental data."""

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
        history_result = await market_data.get_history(symbol, period=period, interval='1d')
        if not history_result.available:
            reason = history_result.reason or 'Data unavailable'
            raise ValueError(f'Historical data unavailable for {symbol}: {reason}')
        hist = history_result.data  # This is already a normalized DataFrame

        fund_result = await market_data.get_fundamentals(symbol)
        info = fund_result.data if fund_result.available else {}

        if hist is None or hist.empty or len(hist) < 30:
            raise ValueError(f"Insufficient data for {symbol}: need 30+ daily bars")

        # No need to flatten — MarketDataProvider returns standardized columns
        df = hist.copy()

        # ── Price features ──
        df["return_1d"] = df["Close"].pct_change(1)
        df["return_5d"] = df["Close"].pct_change(5)
        df["return_20d"] = df["Close"].pct_change(20)
        df["volatility_20d"] = df["return_1d"].rolling(20).std()
        df["gap"] = (df["Open"] - df["Close"].shift(1)) / df["Close"].shift(1).replace(0, np.nan)

        # ── Technical features ──
        df["rsi_14"] = self._compute_rsi(df["Close"], 14)
        df["macd_signal"] = self._compute_macd_signal(df["Close"])
        df["bb_position"] = self._compute_bb_position(df["Close"], 20)

        # ── Volume features ──
        vol_sma20 = df["Volume"].rolling(20).mean()
        df["volume_ratio_20d"] = df["Volume"] / vol_sma20.replace(0, np.nan)
        df["volume_trend_5d"] = df["Volume"].pct_change(5)

        # ── Fundamental features (static, broadcast) ──
        pe = _safe(info.get('pe_ratio'), np.nan)
        # pb_ratio: Neither TwelveData nor NSE free tier provides Price-to-Book ratio.
        # book_value (per-share dollar amount) is NOT the same as priceToBook (valuation ratio).
        # Using book_value here would silently corrupt feature scale. Use NaN honestly.
        pb = np.nan  # P/B ratio unavailable from current providers
        mc = _safe(info.get('market_cap'), 0)
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
        # Replace inf with NaN, THEN drop NaN rows.
        # CRITICAL: dropna() does NOT remove inf — XGBoost crashes on inf values.
        feature_cols = self.FEATURE_NAMES
        df_features = df[feature_cols + ["target_5d"]]
        df_features = df_features.replace([np.inf, -np.inf], np.nan).dropna()

        if len(df_features) < 20:
            raise ValueError(f"Too few complete rows for {symbol}: {len(df_features)}")

        X = df_features[feature_cols]
        y = df_features["target_5d"]

        return X, y

    async def build_live_features(self, symbol: str) -> Dict[str, float]:
        """Build feature vector for the most recent trading day (for prediction).

        Returns a dict of feature_name -> value for model input.
        """
        history_result = await market_data.get_history(symbol, period='3mo', interval='1d')
        if not history_result.available:
            reason = history_result.reason or 'Data unavailable'
            raise ValueError(f'Historical data unavailable for {symbol}: {reason}')
        hist = history_result.data

        fund_result = await market_data.get_fundamentals(symbol)
        info = fund_result.data if fund_result.available else {}

        if hist is None or hist.empty or len(hist) < 25:
            raise ValueError(f"Insufficient recent data for {symbol}")

        # No need to flatten — MarketDataProvider returns standardized columns
        df = hist.copy()

        # Compute all features on last 3mo, take the last row
        df["return_1d"] = df["Close"].pct_change(1)
        df["return_5d"] = df["Close"].pct_change(5)
        df["return_20d"] = df["Close"].pct_change(20)
        df["volatility_20d"] = df["return_1d"].rolling(20).std()
        df["gap"] = (df["Open"] - df["Close"].shift(1)) / df["Close"].shift(1).replace(0, np.nan)
        df["rsi_14"] = self._compute_rsi(df["Close"], 14)
        df["macd_signal"] = self._compute_macd_signal(df["Close"])
        df["bb_position"] = self._compute_bb_position(df["Close"], 20)

        vol_sma20 = df["Volume"].rolling(20).mean()
        df["volume_ratio_20d"] = df["Volume"] / vol_sma20.replace(0, np.nan)
        df["volume_trend_5d"] = df["Volume"].pct_change(5)

        pe = _safe(info.get('pe_ratio'), np.nan)
        # pb_ratio: Not available from current providers (see build_features comment)
        pb = np.nan
        mc = _safe(info.get('market_cap'), 0)

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
