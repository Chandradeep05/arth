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

from app.core.indicators import compute_bollinger_bands, compute_macd, compute_rsi
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

    FEATURE_NAMES_V1 = [
        "return_1d", "return_5d", "return_20d",
        "volatility_20d", "gap",
        "rsi_14", "macd_signal", "bb_position",
        "volume_ratio_20d", "volume_trend_5d",
        "pe_ratio", "pb_ratio", "market_cap_log",
        "day_of_week", "month",
    ]
    FEATURE_NAMES = FEATURE_NAMES_V1

    # V2 features with scale-invariant normalized technical signals (M1.5)
    FEATURE_NAMES_V2 = FEATURE_NAMES_V1 + ["macd_signal_norm"]

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

        # ── Fundamental features ──
        # IMPORTANT: Historical fundamentals are NOT available from current providers.
        # Broadcasting today's P/E, P/B, or market cap across 2 years of historical rows
        # is look-ahead leakage — the model sees future-state data during training.
        # XGBoost handles NaN natively (splits learn to route missing values optimally),
        # so NaN is both safe and honest.
        pb = np.nan
        df["pe_ratio"] = np.nan
        df["pb_ratio"] = pb
        df["market_cap_log"] = np.nan

        # ── Calendar features ──
        df["day_of_week"] = df.index.dayofweek
        df["month"] = df.index.month

        # ── Target: 5-day forward return ──
        df["target_5d"] = df["Close"].pct_change(5).shift(-5)

        # Select feature columns and drop NaN rows
        # Replace inf with NaN, THEN drop NaN rows.
        # CRITICAL: dropna() does NOT remove inf — XGBoost crashes on inf values.
        # CRITICAL: Exclude pb_ratio/pe_ratio/market_cap_log from dropna subset, as they are NaN
        # when provider fundamentals are unavailable. XGBoost handles NaN natively.
        feature_cols = self.FEATURE_NAMES
        _always_nan = {"pb_ratio", "pe_ratio", "market_cap_log"}
        dropna_cols = [c for c in feature_cols if c not in _always_nan] + ["target_5d"]
        df_features = df[feature_cols + ["target_5d"]]
        df_features = df_features.replace([np.inf, -np.inf], np.nan).dropna(subset=dropna_cols)

        if len(df_features) < 20:
            raise ValueError(f"Too few complete rows for {symbol}: {len(df_features)}")

        X = df_features[feature_cols]
        y = df_features["target_5d"]

        return X, y

    async def build_live_features(self, symbol: str) -> Dict[str, float]:
        """Build feature vector for the most recent trading day (for prediction).

        Returns a dict of feature_name -> value for model input.
        Enforces:
        - 1-year lookback (250+ bars) for train/serve indicator warm-up parity (M1.1)
        - Explicit abstention on missing/unwarmed technical indicators (M1.2)
        - Scale-invariant feature compatibility (M1.5)
        """
        # M1.1: 1y lookback (~252 trading days) ensures parity with training indicator convergence
        history_result = await market_data.get_history(symbol, period='1y', interval='1d')
        if not history_result.available:
            reason = history_result.reason or 'Data unavailable'
            raise ValueError(f'Historical data unavailable for {symbol}: {reason}')
        hist = history_result.data

        if hist is None or hist.empty or len(hist) < 35:
            raise ValueError(f"Insufficient recent data for {symbol}: need 35+ daily bars for indicator warm-up")

        # No need to flatten — MarketDataProvider returns standardized columns
        df = hist.copy()

        # Compute all features on history, take the last row
        df["return_1d"] = df["Close"].pct_change(1)
        df["return_5d"] = df["Close"].pct_change(5)
        df["return_20d"] = df["Close"].pct_change(20)
        df["volatility_20d"] = df["return_1d"].rolling(20).std()
        df["gap"] = (df["Open"] - df["Close"].shift(1)) / df["Close"].shift(1).replace(0, np.nan)
        df["rsi_14"] = self._compute_rsi(df["Close"], 14)
        df["macd_signal"] = self._compute_macd_signal(df["Close"])
        df["bb_position"] = self._compute_bb_position(df["Close"], 20)
        df["macd_signal_norm"] = df["macd_signal"] / df["Close"].replace(0, np.nan)

        vol_sma20 = df["Volume"].rolling(20).mean()
        df["volume_ratio_20d"] = df["Volume"] / vol_sma20.replace(0, np.nan)
        df["volume_trend_5d"] = df["Volume"].pct_change(5)

        # ── Fundamental features — match training behavior ──
        df["pe_ratio"] = np.nan
        df["pb_ratio"] = np.nan
        df["market_cap_log"] = np.nan
        df["day_of_week"] = df.index.dayofweek
        df["month"] = df.index.month

        last = df.iloc[-1]
        features = {}

        # M1.2: Core price and technical features where missing values indicate insufficient warm-up
        # Must ABSTAIN rather than silently converting to 0.0 false signals
        _REQUIRED_PRICE_TECH_FEATURES = {
            "return_1d", "return_5d", "return_20d", "volatility_20d", "gap",
            "rsi_14", "macd_signal", "bb_position", "volume_ratio_20d"
        }
        _NAN_PRESERVE_COLS = {"pe_ratio", "pb_ratio", "market_cap_log"}

        for col in self.FEATURE_NAMES:
            val = last.get(col)
            if col in _NAN_PRESERVE_COLS:
                features[col] = np.nan  # Always NaN — match training
            elif col in _REQUIRED_PRICE_TECH_FEATURES:
                if val is None or pd.isna(val) or np.isinf(val):
                    raise ValueError(
                        f"Feature '{col}' could not be computed for {symbol} (insufficient history or incomplete warm-up). "
                        f"Abstaining from prediction."
                    )
                features[col] = float(val)
            else:
                features[col] = _safe(val, 0.0)

        # Also store normalized MACD feature for V2 consumers
        features["macd_signal_norm"] = float(last.get("macd_signal_norm", np.nan))

        return features

    # ── Technical indicator helpers ──

    @staticmethod
    def _compute_rsi(close: pd.Series, period: int = 14) -> pd.Series:
        """Compute RSI (0-100) using canonical Wilder RMA."""
        return compute_rsi(close, period=period)

    @staticmethod
    def _compute_macd_signal(close: pd.Series) -> pd.Series:
        """MACD signal line crossover value (MACD - Signal) using canonical SMA-seeded EMA."""
        _, _, hist = compute_macd(close, fast=12, slow=26, signal=9)
        return hist

    @staticmethod
    def _compute_bb_position(close: pd.Series, period: int = 20) -> pd.Series:
        """Position within Bollinger Bands (0 = lower, 1 = upper) using population std (ddof=0)."""
        _, _, _, percent_b, _ = compute_bollinger_bands(close, period=period, num_std=2.0, ddof=0)
        return percent_b


# Module-level aliases for direct import
FEATURE_NAMES_V1 = FeatureEngineer.FEATURE_NAMES_V1
FEATURE_NAMES_V2 = FeatureEngineer.FEATURE_NAMES_V2
FEATURE_NAMES = FeatureEngineer.FEATURE_NAMES
