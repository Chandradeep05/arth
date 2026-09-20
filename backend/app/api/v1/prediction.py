"""
Prediction API endpoints.

Provides:
- POST /prediction/{symbol}/forecast  — 5-day forecast with SHAP factors
- GET  /prediction/{symbol}/accuracy  — historical prediction accuracy
- GET  /prediction/{symbol}/regime    — current market regime
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field
from typing import Any, Dict, List, Optional

from app.core.auth import UserContext, require_active_user
from app.core.logging import get_logger
from app.core.quotas import check_user_quota
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
async def generate_forecast(
    symbol: str,
    request: Request,
    user: UserContext = Depends(require_active_user),
):
    """Generate prediction for a stock and record for outcome tracking."""
    logger.info("prediction_requested", symbol=symbol)
    
    # Quota enforcement
    redis_instance = getattr(request.app.state, "redis", None)
    await check_user_quota(user.user_id, "prediction", redis_instance)

    result = await prediction_model.forecast(symbol)

    # Phase 3: Store prediction in Outcome Tracker for credibility verification
    try:
        from app.engines.prediction.outcome_tracker import outcome_tracker
        from app.data.market_data_provider import market_data
        pred = result.get("prediction")
        regime = result.get("regime")
        model_info = result.get("model_info")

        if pred and not result.get("error"):
            pred_return = pred.get("predicted_return_pct") if isinstance(pred, dict) else getattr(pred, "predicted_return_pct", 0.0)
            conf_score = pred.get("confidence_score") if isinstance(pred, dict) else getattr(pred, "confidence_score", 0.5)
            conf_band = pred.get("confidence") if isinstance(pred, dict) else getattr(pred, "confidence", "medium")
            regime_curr = regime.get("current") if isinstance(regime, dict) else getattr(regime, "current", "unknown")
            r2 = model_info.get("r2_score") if isinstance(model_info, dict) else getattr(model_info, "r2_score", None)

            # Reference price: prefer model's own latest_close (same data universe)
            # Fallback to quote API if model didn't provide it
            ref_price = None
            ref_timestamp = None
            ref_source = None
            if model_info and isinstance(model_info, dict):
                ref_price = model_info.get("latest_close")
                ref_timestamp = model_info.get("latest_close_timestamp")
                ref_source = "training_data"
            if ref_price is None:
                try:
                    quote_result = await market_data.get_quote(symbol)
                    if quote_result.available and quote_result.data:
                        ref_price = quote_result.data.get("price")
                        ref_source = "quote_api"
                except Exception as qe:
                    logger.warning("reference_price_fetch_failed", symbol=symbol, error=str(qe))

            await outcome_tracker.store_prediction(
                symbol=symbol,
                predicted_return_pct=pred_return,
                confidence_score=conf_score,
                confidence_band=conf_band,
                regime=regime_curr or "unknown",
                horizon_days=5,
                model_r2=r2,
                reference_price=ref_price,
                reference_timestamp=ref_timestamp,
                reference_source=ref_source,
            )
    except Exception as e:
        logger.warning("prediction_tracking_record_failed", symbol=symbol, error=str(e))

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
    request: Request = None,
    user: UserContext = Depends(require_active_user),
):
    """Get prediction accuracy metrics."""
    # Try cached result first
    cached = backtester.get_cached_accuracy(symbol, lookback_days)
    if cached and not cached.get("error"):
        return AccuracyResponse(**cached)

    # Run fresh backtest
    logger.info("backtest_requested", symbol=symbol, lookback=lookback_days)
    result = await backtester.run_backtest(symbol, lookback_days)
    return AccuracyResponse(**result)


@router.get(
    "/{symbol}/history",
    summary="Prediction Tracking History",
    description=(
        "Get historical tracked predictions and evaluated accuracy outcomes "
        "for a symbol from the persistent outcome tracker (Phase 3 Trust Layer)."
    ),
)
async def get_prediction_history(
    symbol: str,
    limit: int = Query(default=50, ge=1, le=200),
    request: Request = None,
    user: UserContext = Depends(require_active_user),
):
    """Get live tracked predictions and evaluation metrics."""
    from app.engines.prediction.outcome_tracker import outcome_tracker

    stats = await outcome_tracker.get_accuracy(symbol)
    history = await outcome_tracker.get_history(symbol, limit=limit)

    return {
        "symbol": symbol.upper(),
        "stats": stats.model_dump(),
        "history": [r.model_dump() for r in history],
    }


@router.get(
    "/{symbol}/regime",
    summary="Market Regime Detection",
    description=(
        "Detect current market regime for a symbol: trending (strong directional movement), "
        "ranging (sideways, low volatility), or reverting (mean-reverting after extremes)."
    ),
)
async def get_regime(
    symbol: str,
    request: Request = None,
    user: UserContext = Depends(require_active_user),
):
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

