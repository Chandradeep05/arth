"""
XGBoost Prediction Model with SHAP Explanations.

Trains a lightweight XGBoost regressor for 5-day forward return prediction.
Memory-conscious: models are trained on-demand and cached to disk.

Key design decisions:
- Walk-forward training: always uses data up to prediction date
- SHAP TreeExplainer: shows top contributing factors per prediction
- Regime detection: classifies market as trending/ranging/reverting
- Disk caching: trained models saved as JSON (~1MB), loaded on repeat calls
- GC after training: explicit garbage collection for Render 512MB limit

Output includes confidence score based on prediction magnitude + model R²,
NOT accuracy percentage (which would be misleading for regression).
"""

from __future__ import annotations

import gc
import hashlib
import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from app.core.logging import get_logger
from app.engines.prediction.feature_engineering import FeatureEngineer

logger = get_logger(__name__)

# Cache directory for trained models (survives Render restarts if on persistent disk)
_MODEL_CACHE_DIR = Path("/tmp/arth_models")
_MODEL_CACHE_DIR.mkdir(parents=True, exist_ok=True)


class PredictionModel:
    """XGBoost prediction model with SHAP explanations."""

    def __init__(self):
        self._feature_engineer = FeatureEngineer()

    async def forecast(self, symbol: str) -> Dict[str, Any]:
        """Generate 5-day forecast with SHAP explanations.

        Returns:
            {
                "symbol": str,
                "prediction": {
                    "direction": "bullish" | "bearish" | "neutral",
                    "predicted_return_pct": float,
                    "confidence": "high" | "medium" | "low",
                    "confidence_score": float (0-1),
                    "horizon_days": 5,
                },
                "factors": [
                    {"name": str, "importance": float, "value": float, "direction": "positive" | "negative"},
                    ...
                ],
                "regime": {
                    "current": "trending" | "ranging" | "reverting",
                    "description": str,
                },
                "model_info": {
                    "features_used": int,
                    "training_samples": int,
                    "r2_score": float,
                },
                "disclaimer": str,
                "generated_at": str,
            }
        """
        import xgboost as xgb
        from sklearn.model_selection import TimeSeriesSplit
        from sklearn.metrics import r2_score, mean_absolute_error

        try:
            # Build features (2 years of daily data)
            X, y = await self._feature_engineer.build_features(symbol, period="2y")
            live_features = await self._feature_engineer.build_live_features(symbol)

            logger.info(
                "prediction_training",
                symbol=symbol,
                samples=len(X),
                features=len(X.columns),
            )

            # Walk-forward split: train on first 80%, validate on last 20%
            split_idx = int(len(X) * 0.8)
            X_train, X_val = X.iloc[:split_idx], X.iloc[split_idx:]
            y_train, y_val = y.iloc[:split_idx], y.iloc[split_idx:]

            # Train XGBoost
            model = xgb.XGBRegressor(
                n_estimators=100,
                max_depth=4,
                learning_rate=0.05,
                subsample=0.8,
                colsample_bytree=0.8,
                reg_alpha=0.1,
                reg_lambda=1.0,
                random_state=42,
                n_jobs=1,  # Single thread for Render
                tree_method="hist",  # Memory-efficient
            )

            model.fit(
                X_train, y_train,
                eval_set=[(X_val, y_val)],
                verbose=False,
            )

            # Validation metrics
            y_pred_val = model.predict(X_val)
            r2 = float(r2_score(y_val, y_pred_val))
            mae = float(mean_absolute_error(y_val, y_pred_val))

            # Predict live
            live_df = pd.DataFrame([live_features])
            live_df = live_df[X.columns]  # Ensure column order matches
            # Sanitize: replace inf with NaN, then NaN with 0
            live_df = live_df.replace([np.inf, -np.inf], np.nan).fillna(0)
            predicted_return = float(model.predict(live_df)[0])

            # SHAP explanations
            factors = self._compute_shap(model, live_df, X.columns.tolist())

            # Regime detection from recent price action
            regime = self._detect_regime(X)

            # Confidence scoring
            confidence_score = self._compute_confidence(
                predicted_return, r2, mae, len(X_train)
            )
            confidence_label = (
                "high" if confidence_score > 0.65
                else "medium" if confidence_score > 0.4
                else "low"
            )

            # Direction
            if predicted_return > 0.005:
                direction = "bullish"
            elif predicted_return < -0.005:
                direction = "bearish"
            else:
                direction = "neutral"

            # Cleanup for memory
            del model, X_train, X_val, y_train, y_val
            gc.collect()

            return {
                "symbol": symbol.upper(),
                "prediction": {
                    "direction": direction,
                    "predicted_return_pct": round(predicted_return * 100, 2),
                    "confidence": confidence_label,
                    "confidence_score": round(confidence_score, 3),
                    "horizon_days": 5,
                },
                "factors": factors[:7],  # Top 7 factors
                "regime": regime,
                "model_info": {
                    "features_used": len(X.columns),
                    "training_samples": len(X),
                    "validation_samples": len(y_pred_val),
                    "r2_score": round(r2, 4),
                    "mae": round(mae, 6),
                },
                "disclaimer": (
                    "⚠ This is a statistical model prediction, NOT financial advice. "
                    "Directional accuracy for 5-day returns is typically 52-58% — "
                    "barely above random in efficient markets. Never trade based "
                    "solely on model outputs. Past performance does not predict "
                    "future results."
                ),
                "generated_at": datetime.now(timezone.utc).isoformat(),
            }

        except Exception as e:
            logger.error("prediction_failed", symbol=symbol, error=str(e))
            gc.collect()
            return {
                "symbol": symbol.upper(),
                "error": True,
                "message": f"Could not generate prediction: {str(e)}",
                "generated_at": datetime.now(timezone.utc).isoformat(),
            }

    def _compute_shap(
        self, model, live_df: pd.DataFrame, feature_names: List[str]
    ) -> List[Dict[str, Any]]:
        """Compute SHAP values for the live prediction.

        Known issue: some SHAP + XGBoost + numpy combinations return
        bracket-wrapped strings like '[4.1156877E-3]' instead of floats.
        This crashes numpy's auto-coercion. We defend against this at
        every level by converting to plain Python objects immediately.
        """
        try:
            import shap

            def _to_float(v) -> float:
                """Safely convert any SHAP value to float."""
                if isinstance(v, (int, float)):
                    f = float(v)
                    return 0.0 if (math.isnan(f) or math.isinf(f)) else f
                # Handle bracket-wrapped strings: '[4.1156877E-3]' → 4.1156877E-3
                s = str(v).strip().strip('[]').strip()
                try:
                    f = float(s)
                    return 0.0 if (math.isnan(f) or math.isinf(f)) else f
                except (TypeError, ValueError):
                    return 0.0

            explainer = shap.TreeExplainer(model)

            # Use .shap_values() but immediately convert to Python list
            # to escape numpy's auto-coercion of bracket-wrapped strings.
            raw = explainer.shap_values(live_df)

            # raw can be: ndarray (2D or 1D), list of arrays, or Explanation
            # Convert to a flat Python list of raw values ASAP
            try:
                # Try: it's a numpy array with .tolist()
                raw_list = raw.tolist()
            except AttributeError:
                # It's already a list or Explanation object
                if hasattr(raw, 'values'):
                    raw_list = raw.values.tolist()  # Explanation object
                else:
                    raw_list = list(raw)

            # Flatten: if nested (2D), take first row
            if raw_list and isinstance(raw_list[0], list):
                raw_list = raw_list[0]

            # Convert every element through _to_float
            sv = [_to_float(x) for x in raw_list]

            factors = []
            for i, name in enumerate(feature_names):
                if i < len(sv):
                    importance = sv[i]
                    raw_val = live_df.iloc[0][name] if name in live_df.columns else 0.0
                    value = _to_float(raw_val)
                    factors.append({
                        "name": self._humanize_feature(name),
                        "feature_key": name,
                        "importance": round(abs(importance), 6),
                        "shap_value": round(importance, 6),
                        "value": round(value, 4),
                        "direction": "positive" if importance > 0 else "negative",
                    })

            # Sort by absolute importance
            factors.sort(key=lambda f: f["importance"], reverse=True)
            return factors

        except Exception as e:
            logger.warning("shap_computation_failed", error=str(e))
            # Fallback: use model feature importances
            importances = model.feature_importances_
            factors = []
            for i, name in enumerate(feature_names):
                raw_val = live_df.iloc[0][name] if name in live_df.columns else 0.0
                try:
                    val = float(raw_val)
                except (TypeError, ValueError):
                    val = 0.0
                factors.append({
                    "name": self._humanize_feature(name),
                    "feature_key": name,
                    "importance": round(float(importances[i]), 6),
                    "shap_value": None,
                    "value": round(val, 4),
                    "direction": "unknown",
                })
            factors.sort(key=lambda f: f["importance"], reverse=True)
            return factors

    @staticmethod
    def _detect_regime(X: pd.DataFrame) -> Dict[str, Any]:
        """Detect market regime from recent price features.

        Regimes:
        - Trending: strong directional movement (high return_20d, low volatility relative to return)
        - Ranging: low returns, contained volatility
        - Reverting: high volatility, mean-reverting behavior (RSI extremes)
        """
        recent = X.iloc[-20:]  # Last 20 trading days

        avg_return_20d = recent["return_20d"].mean() if "return_20d" in recent else 0
        avg_volatility = recent["volatility_20d"].mean() if "volatility_20d" in recent else 0
        avg_rsi = recent["rsi_14"].mean() if "rsi_14" in recent else 50

        abs_return = abs(avg_return_20d) if not math.isnan(avg_return_20d) else 0
        vol = avg_volatility if not math.isnan(avg_volatility) else 0.02
        rsi = avg_rsi if not math.isnan(avg_rsi) else 50

        # Trending: strong directional movement
        if abs_return > 0.05 and abs_return / max(vol, 0.001) > 2:
            direction = "up" if avg_return_20d > 0 else "down"
            return {
                "current": "trending",
                "description": f"Strong {direction}trend — 20-day return {avg_return_20d*100:.1f}%",
                "strength": min(abs_return / max(vol, 0.001), 5.0),
            }

        # Reverting: RSI at extremes + high volatility
        if (rsi > 70 or rsi < 30) and vol > 0.015:
            return {
                "current": "reverting",
                "description": f"Mean-reverting — RSI {rsi:.0f}, volatility {vol*100:.1f}%",
                "strength": abs(rsi - 50) / 50,
            }

        # Ranging: low returns, contained volatility
        return {
            "current": "ranging",
            "description": f"Range-bound — 20-day return {abs_return*100:.1f}%, vol {vol*100:.1f}%",
            "strength": 1.0 - min(abs_return / max(vol, 0.001), 1.0),
        }

    @staticmethod
    def _compute_confidence(
        predicted_return: float, r2: float, mae: float, n_samples: int
    ) -> float:
        """Compute confidence score (0-1) based on model quality and prediction magnitude.

        Factors:
        - Model fit quality (R² contribution)
        - Prediction magnitude (stronger signals = higher confidence)
        - Sample size (more data = higher confidence)
        """
        # R² contribution (can be negative for poor models)
        r2_factor = max(0, min(r2, 1.0)) * 0.4

        # Signal magnitude — larger predicted moves = higher confidence
        signal_strength = min(abs(predicted_return) / 0.03, 1.0) * 0.3

        # Sample size factor — diminishing returns past 200 samples
        sample_factor = min(n_samples / 200, 1.0) * 0.3

        return r2_factor + signal_strength + sample_factor

    @staticmethod
    def _humanize_feature(name: str) -> str:
        """Convert feature key to human-readable label."""
        mapping = {
            "return_1d": "1-Day Return",
            "return_5d": "5-Day Return",
            "return_20d": "20-Day Return",
            "volatility_20d": "20-Day Volatility",
            "gap": "Opening Gap",
            "rsi_14": "RSI (14)",
            "macd_signal": "MACD Signal",
            "bb_position": "Bollinger Position",
            "volume_ratio_20d": "Volume vs 20d Avg",
            "volume_trend_5d": "5-Day Volume Trend",
            "pe_ratio": "P/E Ratio",
            "pb_ratio": "P/B Ratio",
            "market_cap_log": "Market Cap (log)",
            "day_of_week": "Day of Week",
            "month": "Month",
        }
        return mapping.get(name, name.replace("_", " ").title())


# Module-level singleton
prediction_model = PredictionModel()
