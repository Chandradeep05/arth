"""
Walk-Forward Backtester for Prediction Accuracy Tracking.

Replays predictions against actual 5-day outcomes to measure model accuracy.
Stores results in a JSON file (no DB needed).

Tracks:
- Directional accuracy by confidence band (high/medium/low)
- Mean absolute error over time
- Accuracy trend (improving/stable/degrading)
"""

from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from app.core.logging import get_logger
from app.engines.prediction.feature_engineering import FeatureEngineer

logger = get_logger(__name__)

# Persistent storage for accuracy tracking
_ACCURACY_DIR = Path("/tmp/arth_accuracy")
_ACCURACY_DIR.mkdir(parents=True, exist_ok=True)


class Backtester:
    """Walk-forward backtester for prediction quality measurement."""

    def __init__(self):
        self._feature_engineer = FeatureEngineer()

    async def run_backtest(
        self,
        symbol: str,
        lookback_days: int = 90,
    ) -> Dict[str, Any]:
        """Run walk-forward backtest over the last N days.

        Simulates what would have happened if we'd made predictions
        every trading day for the last `lookback_days` days.

        Returns accuracy metrics by confidence band.
        """
        import xgboost as xgb
        from sklearn.metrics import r2_score

        try:
            X, y = await self._feature_engineer.build_features(symbol, period="2y")

            if len(X) < 100:
                return {
                    "symbol": symbol.upper(),
                    "error": True,
                    "message": f"Insufficient data: {len(X)} rows, need 100+",
                }

            # Walk-forward: train on expanding window, predict next 5 days
            test_start = max(60, len(X) - lookback_days)
            results = []

            model = xgb.XGBRegressor(
                n_estimators=80,
                max_depth=4,
                learning_rate=0.05,
                subsample=0.8,
                colsample_bytree=0.8,
                n_jobs=1,
                tree_method="hist",
                random_state=42,
            )

            for i in range(test_start, len(X)):
                X_train = X.iloc[:i]
                y_train = y.iloc[:i]

                model.fit(X_train, y_train, verbose=False)

                pred = float(model.predict(X.iloc[[i]])[0])
                actual = float(y.iloc[i])

                # Directional accuracy
                correct = (pred > 0 and actual > 0) or (pred < 0 and actual < 0) or (abs(pred) < 0.001 and abs(actual) < 0.001)

                # Confidence band
                abs_pred = abs(pred)
                if abs_pred > 0.02:
                    band = "high"
                elif abs_pred > 0.005:
                    band = "medium"
                else:
                    band = "low"

                results.append({
                    "predicted": round(pred * 100, 4),
                    "actual": round(actual * 100, 4),
                    "correct_direction": correct,
                    "confidence_band": band,
                    "error_pct": round(abs(pred - actual) * 100, 4),
                })

            # Aggregate metrics
            df = pd.DataFrame(results)
            overall_accuracy = df["correct_direction"].mean()
            overall_mae = df["error_pct"].mean()

            # By confidence band
            by_band = {}
            for band in ["high", "medium", "low"]:
                band_data = df[df["confidence_band"] == band]
                if len(band_data) > 0:
                    by_band[band] = {
                        "count": len(band_data),
                        "directional_accuracy": round(float(band_data["correct_direction"].mean()) * 100, 1),
                        "avg_error_pct": round(float(band_data["error_pct"].mean()), 2),
                    }

            # Trend: compare first half vs second half accuracy
            mid = len(df) // 2
            first_half_acc = df.iloc[:mid]["correct_direction"].mean() if mid > 0 else 0
            second_half_acc = df.iloc[mid:]["correct_direction"].mean() if mid > 0 else 0
            trend = (
                "improving" if second_half_acc > first_half_acc + 0.03
                else "degrading" if second_half_acc < first_half_acc - 0.03
                else "stable"
            )

            result = {
                "symbol": symbol.upper(),
                "backtest_days": lookback_days,
                "predictions_evaluated": len(results),
                "overall": {
                    "directional_accuracy_pct": round(float(overall_accuracy) * 100, 1),
                    "mean_absolute_error_pct": round(float(overall_mae), 2),
                    "trend": trend,
                },
                "by_confidence_band": by_band,
                "context": (
                    f"Directional accuracy of {overall_accuracy*100:.1f}% means the model "
                    f"correctly predicts whether the stock goes up or down over 5 days. "
                    f"In efficient markets, >55% is considered meaningful. "
                    f"This is NOT the probability of a profitable trade."
                ),
                "generated_at": datetime.now(timezone.utc).isoformat(),
            }

            # Save to disk for historical tracking
            self._save_result(symbol, result)

            return result

        except Exception as e:
            logger.error("backtest_failed", symbol=symbol, error=str(e))
            return {
                "symbol": symbol.upper(),
                "error": True,
                "message": f"Backtest failed: {str(e)}",
            }

    def get_cached_accuracy(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Get last cached backtest result for a symbol."""
        filepath = _ACCURACY_DIR / f"{symbol.upper().replace('.', '_')}_accuracy.json"
        if filepath.exists():
            try:
                return json.loads(filepath.read_text())
            except Exception:
                return None
        return None

    def _save_result(self, symbol: str, result: Dict[str, Any]) -> None:
        """Persist backtest result to disk."""
        try:
            filepath = _ACCURACY_DIR / f"{symbol.upper().replace('.', '_')}_accuracy.json"
            filepath.write_text(json.dumps(result, indent=2))
        except Exception as e:
            logger.warning("accuracy_save_failed", symbol=symbol, error=str(e))


# Module-level singleton
backtester = Backtester()
