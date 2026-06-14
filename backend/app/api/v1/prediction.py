"""
Prediction API endpoints.

Provides:
- POST /prediction/{symbol}/forecast  — 5-day forecast with SHAP factors
- GET  /prediction/{symbol}/accuracy  — historical prediction accuracy
- GET  /prediction/{symbol}/regime    — current market regime
"""

from __future__ import annotations

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field
from typing import Any, Dict, List, Optional

from app.core.logging import get_logger
from app.engines.prediction.model import prediction_model
from app.engines.prediction.backtester import backtester

logger = get_logger(__name__)
router = APIRouter(prefix="/prediction", tags=["prediction"])


# ── Response Models ──────────────────────────────────────────────

class PredictionDirection(BaseModel):
    direction: str = Field(..., description="bullish, bearish, or neutral")
    predicted_return_pct: float = Field(..., description="Predicted 5-day return %")
    confidence: str = Field(..., description="high, medium, or low")
    confidence_score: float = Field(..., description="0-1 confidence score")
    horizon_days: int = 5


class SHAPFactor(BaseModel):
    name: str
    feature_key: str
    importance: float
    shap_value: Optional[float] = None
    value: float
    direction: str


class RegimeInfo(BaseModel):
    current: str = Field(..., description="trending, ranging, or reverting")
    description: str
    strength: Optional[float] = None


class ModelInfo(BaseModel):
    features_used: int
    training_samples: int
    validation_samples: Optional[int] = None
    r2_score: float
    mae: Optional[float] = None


class ForecastResponse(BaseModel):
    symbol: str
    prediction: Optional[PredictionDirection] = None
    factors: Optional[List[SHAPFactor]] = None
    regime: Optional[RegimeInfo] = None
    model_info: Optional[ModelInfo] = None
    disclaimer: Optional[str] = None
    error: Optional[bool] = None
    message: Optional[str] = None
    generated_at: str


class AccuracyBand(BaseModel):
    count: int
    directional_accuracy: float
    avg_error_pct: float


class AccuracyOverall(BaseModel):
    directional_accuracy_pct: float
    mean_absolute_error_pct: float
    trend: str


class AccuracyResponse(BaseModel):
    symbol: str
    backtest_days: Optional[int] = None
    predictions_evaluated: Optional[int] = None
    overall: Optional[AccuracyOverall] = None
    by_confidence_band: Optional[Dict[str, AccuracyBand]] = None
    context: Optional[str] = None
    error: Optional[bool] = None
    message: Optional[str] = None
    generated_at: Optional[str] = None


# ── Endpoints ────────────────────────────────────────────────────

@router.post(
    "/{symbol}/forecast",
    response_model=ForecastResponse,
    summary="5-Day Forecast with SHAP",
    description=(
        "Generate a 5-day forward return prediction using XGBoost with SHAP explanations. "
        "Includes top contributing factors, market regime detection, and confidence scoring. "
        "First call for a symbol takes 5-10 seconds (model training). "
        "⚠ This is a statistical model, NOT financial advice."
    ),
)
async def generate_forecast(symbol: str):
    """Generate prediction for a stock."""
    logger.info("prediction_requested", symbol=symbol)
    result = await prediction_model.forecast(symbol)
    return ForecastResponse(**result)


@router.get(
    "/{symbol}/accuracy",
    response_model=AccuracyResponse,
    summary="Prediction Accuracy History",
    description=(
        "Get walk-forward backtesting results showing how well the model's "
        "predictions matched actual outcomes over the last 90 days."
    ),
)
async def get_accuracy(
    symbol: str,
    lookback_days: int = Query(default=90, ge=30, le=365),
):
    """Get prediction accuracy metrics."""
    # Try cached result first
    cached = backtester.get_cached_accuracy(symbol)
    if cached and not cached.get("error"):
        return AccuracyResponse(**cached)

    # Run fresh backtest
    logger.info("backtest_requested", symbol=symbol, lookback=lookback_days)
    result = await backtester.run_backtest(symbol, lookback_days)
    return AccuracyResponse(**result)


@router.get(
    "/{symbol}/regime",
    summary="Market Regime Detection",
    description=(
        "Detect current market regime for a symbol: trending (strong directional movement), "
        "ranging (sideways, low volatility), or reverting (mean-reverting after extremes)."
    ),
)
async def get_regime(symbol: str):
    """Get current market regime."""
    try:
        from app.engines.prediction.feature_engineering import FeatureEngineer

        fe = FeatureEngineer()
        X, _ = await fe.build_features(symbol, period="6mo")

        regime = prediction_model._detect_regime(X)
        return {
            "symbol": symbol.upper(),
            "regime": regime,
        }
    except Exception as e:
        return {
            "symbol": symbol.upper(),
            "error": True,
            "message": str(e),
        }
