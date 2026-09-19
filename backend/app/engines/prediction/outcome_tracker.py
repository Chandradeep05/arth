"""
ARTH — Prediction Outcome Tracker

Tracks every forecast, stores it, and later evaluates against actual market outcomes.
Builds the credibility loop: "Was that 64% confidence prediction actually right?"

Storage Strategy:
- Primary: Upstash Redis (persistent across Render cold starts)
- Fallback: In-memory dict (lost on restart, but operational)
- JSON file storage explicitly avoided (Render filesystem is ephemeral)

Key design decisions:
- Predictions are stored immediately when generated with their reference_price
- Evaluation happens lazily: when accuracy is requested, check all unevaluated predictions
  whose horizon has passed and fetch actual returns
- Evaluation uses atomic Redis claims (SET NX) to prevent concurrent evaluators
- Predictions without reference_price are marked 'ungradable' (not silently skipped)
- Uses calendar-day approximation (horizon_days + 2) as MVP for maturity check
  (exact trading-session calendar is deferred architecture work)
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone, timedelta
from typing import Optional

from pydantic import BaseModel, Field

from app.core.logging import get_logger

logger = get_logger(__name__)


class PredictionRecord(BaseModel):
    """A single stored prediction with its eventual outcome."""
    symbol: str
    predicted_return_pct: float        # predicted return percentage
    confidence_score: float            # 0.0 - 1.0
    confidence_band: str               # "high", "medium", "low"
    regime: str = "unknown"            # "trending", "ranging", "reverting"
    horizon_days: int = 5
    predicted_at: str                  # ISO timestamp
    model_r2: float | None = None     # model's R² at time of prediction

    # Reference price at prediction time — REQUIRED for evaluation
    reference_price: float | None = None
    reference_timestamp: str | None = None

    # Model/feature versioning for cache key alignment
    model_version: str = "xgb-v1"
    feature_version: str = "features-v2"

    # Evaluation status: pending | evaluated | ungradable
    evaluation_status: str = "pending"

    # Filled after evaluation
    actual_return_pct: float | None = None
    evaluation_price: float | None = None
    evaluation_timestamp: str | None = None
    directional_correct: bool | None = None
    magnitude_error_pp: float | None = None  # percentage points error
    evaluated_at: str | None = None


class AccuracyStats(BaseModel):
    """Aggregated accuracy statistics."""
    total_predictions: int = 0
    evaluated_predictions: int = 0
    pending_predictions: int = 0
    ungradable_predictions: int = 0
    directional_accuracy_pct: float | None = None   # % of directional calls correct
    mean_magnitude_error_pp: float | None = None     # average |predicted - actual| in pp
    accuracy_by_band: dict = {}        # {"high": {"total": N, "correct": M}, ...}
    accuracy_by_regime: dict = {}      # {"trending": {"total": N, "correct": M}, ...}
    oldest_prediction: str | None = None
    newest_prediction: str | None = None


class OutcomeTracker:
    """
    Tracks prediction outcomes using Upstash Redis (primary) or in-memory (fallback).
    """

    # Redis key prefixes
    _PREFIX = "prediction_track:"
    _INDEX_KEY = "prediction_index"   # sorted set of all prediction keys by timestamp

    def __init__(self):
        self._memory_store: dict[str, PredictionRecord] = {}
        self._redis = None

    def set_redis(self, redis_client) -> None:
        """Set the Redis client (called during app startup if Upstash is available)."""
        self._redis = redis_client
        logger.info("outcome_tracker_redis_connected")

    async def store_prediction(
        self,
        symbol: str,
        predicted_return_pct: float,
        confidence_score: float,
        confidence_band: str,
        regime: str = "unknown",
        horizon_days: int = 5,
        model_r2: float | None = None,
        reference_price: float | None = None,
    ) -> PredictionRecord:
        """Store a new prediction for later evaluation.

        If reference_price is None (quote provider failed), the prediction
        is immediately marked 'ungradable' — it will appear in accuracy stats
        but cannot be evaluated.
        """
        now = datetime.now(timezone.utc)

        # Determine evaluation status based on reference_price availability
        eval_status = "pending"
        if reference_price is None:
            eval_status = "ungradable"
            logger.warning(
                "prediction_ungradable",
                symbol=symbol,
                reason="reference_price_unavailable",
            )

        record = PredictionRecord(
            symbol=symbol.upper(),
            predicted_return_pct=predicted_return_pct,
            confidence_score=confidence_score,
            confidence_band=confidence_band,
            regime=regime,
            horizon_days=horizon_days,
            predicted_at=now.isoformat(),
            model_r2=model_r2,
            reference_price=reference_price,
            reference_timestamp=now.isoformat() if reference_price else None,
            evaluation_status=eval_status,
        )

        key = f"{self._PREFIX}{symbol.upper()}:{int(now.timestamp())}"
        record_json = record.model_dump_json()

        # Try Redis first, with 90-day TTL
        if self._redis:
            try:
                await self._redis.set(key, record_json, ex=90 * 86400)  # 90-day TTL
                # Add to sorted index for efficient querying
                await self._redis.zadd(
                    self._INDEX_KEY,
                    {key: now.timestamp()}
                )
                logger.info(
                    "prediction_stored",
                    symbol=symbol,
                    key=key,
                    storage="redis",
                    has_reference_price=reference_price is not None,
                )
                return record
            except Exception as e:
                logger.warning("prediction_store_redis_failed", error=str(e))

        # Fallback: in-memory
        self._memory_store[key] = record
        logger.info(
            "prediction_stored",
            symbol=symbol,
            key=key,
            storage="memory",
            has_reference_price=reference_price is not None,
        )
        return record

    async def evaluate_pending(
        self,
        fetch_price_func,
    ) -> int:
        """
        Evaluate all predictions whose horizon has expired.

        Uses calendar-day approximation (horizon_days + 2) as MVP.
        Exact trading-session calendar is deferred architecture work.

        Atomic evaluation: uses Redis SET NX to prevent concurrent evaluators
        from processing the same record.

        Args:
            fetch_price_func: async callable(symbol) -> current_price (float)

        Returns:
            Number of predictions newly evaluated.
        """
        records = await self._get_all_records()
        now = datetime.now(timezone.utc)
        count = 0

        for key, record in records.items():
            # Skip non-pending records (already evaluated or ungradable)
            if record.evaluation_status != "pending":
                continue

            # Skip if reference_price is missing (shouldn't happen for pending, but be safe)
            if not record.reference_price:
                record.evaluation_status = "ungradable"
                await self._update_record(key, record)
                continue

            # Check if horizon has elapsed (calendar-day approximation)
            predicted_at = datetime.fromisoformat(record.predicted_at)
            if now - predicted_at < timedelta(days=record.horizon_days + 2):
                continue

            # Atomic claim — only one evaluator can process this record
            if self._redis:
                claim_key = f"eval_claim:{key}"
                claimed = await self._redis.set(claim_key, "1", ex=300, nx=True)
                if not claimed:
                    continue  # Another evaluator owns this record

            try:
                price = await fetch_price_func(record.symbol)
                if not price or price <= 0:
                    continue

                actual = (price - record.reference_price) / record.reference_price * 100
                record.actual_return_pct = round(actual, 4)
                record.evaluation_price = price
                record.evaluation_timestamp = now.isoformat()
                record.directional_correct = (record.predicted_return_pct > 0) == (actual > 0)
                record.magnitude_error_pp = round(abs(record.predicted_return_pct - actual), 4)
                record.evaluated_at = now.isoformat()
                record.evaluation_status = "evaluated"
                await self._update_record(key, record)
                count += 1
                logger.info(
                    "prediction_evaluated",
                    symbol=record.symbol,
                    predicted=record.predicted_return_pct,
                    actual=record.actual_return_pct,
                    correct=record.directional_correct,
                )
            except Exception as e:
                logger.warning("evaluation_failed", symbol=record.symbol, error=str(e))
                # Release claim on failure so retry can pick it up
                if self._redis:
                    await self._redis.delete(f"eval_claim:{key}")

        return count

    async def get_accuracy(
        self,
        symbol: str | None = None,
    ) -> AccuracyStats:
        """Get accuracy statistics, optionally filtered by symbol."""
        records = await self._get_all_records()

        # Filter by symbol if specified
        if symbol:
            symbol_upper = symbol.upper()
            records = {
                k: v for k, v in records.items()
                if v.symbol == symbol_upper
            }

        if not records:
            return AccuracyStats()

        total = len(records)
        evaluated = [r for r in records.values() if r.evaluation_status == "evaluated"]
        pending = [r for r in records.values() if r.evaluation_status == "pending"]
        ungradable = [r for r in records.values() if r.evaluation_status == "ungradable"]

        # Directional accuracy
        correct_count = sum(1 for r in evaluated if r.directional_correct)
        directional_accuracy = (
            (correct_count / len(evaluated) * 100) if evaluated else None
        )

        # Mean magnitude error
        errors = [r.magnitude_error_pp for r in evaluated if r.magnitude_error_pp is not None]
        mean_error = (sum(errors) / len(errors)) if errors else None

        # Accuracy by confidence band
        band_stats: dict = {}
        for r in evaluated:
            band = r.confidence_band
            if band not in band_stats:
                band_stats[band] = {"total": 0, "correct": 0}
            band_stats[band]["total"] += 1
            if r.directional_correct:
                band_stats[band]["correct"] += 1

        # Accuracy by regime
        regime_stats: dict = {}
        for r in evaluated:
            regime = r.regime
            if regime not in regime_stats:
                regime_stats[regime] = {"total": 0, "correct": 0}
            regime_stats[regime]["total"] += 1
            if r.directional_correct:
                regime_stats[regime]["correct"] += 1

        # Timestamps
        all_times = [r.predicted_at for r in records.values()]

        return AccuracyStats(
            total_predictions=total,
            evaluated_predictions=len(evaluated),
            pending_predictions=len(pending),
            ungradable_predictions=len(ungradable),
            directional_accuracy_pct=round(directional_accuracy, 1) if directional_accuracy is not None else None,
            mean_magnitude_error_pp=round(mean_error, 2) if mean_error is not None else None,
            accuracy_by_band=band_stats,
            accuracy_by_regime=regime_stats,
            oldest_prediction=min(all_times) if all_times else None,
            newest_prediction=max(all_times) if all_times else None,
        )

    async def get_history(
        self,
        symbol: str,
        limit: int = 50,
    ) -> list[PredictionRecord]:
        """Get prediction history for a symbol, newest first."""
        records = await self._get_all_records()
        symbol_upper = symbol.upper()

        matching = [
            r for r in records.values()
            if r.symbol == symbol_upper
        ]

        # Sort by predicted_at descending
        matching.sort(key=lambda r: r.predicted_at, reverse=True)
        return matching[:limit]

    # ── Private storage methods ──

    async def _get_all_records(self) -> dict[str, PredictionRecord]:
        """Get all records from Redis or memory."""
        if self._redis:
            try:
                # Get all keys from the sorted index
                keys = await self._redis.zrange(self._INDEX_KEY, 0, -1)
                if not keys:
                    return {}

                records = {}
                for key in keys:
                    data = await self._redis.get(key)
                    if data:
                        records[key] = PredictionRecord.model_validate_json(data)
                return records
            except Exception as e:
                logger.warning("prediction_read_redis_failed", error=str(e))

        # Fallback: return memory store
        return dict(self._memory_store)

    async def _update_record(self, key: str, record: PredictionRecord) -> None:
        """Update a record in storage."""
        record_json = record.model_dump_json()

        if self._redis:
            try:
                await self._redis.set(key, record_json)
                return
            except Exception as e:
                logger.warning("prediction_update_redis_failed", error=str(e))

        # Fallback: memory
        self._memory_store[key] = record


# Module-level singleton
outcome_tracker = OutcomeTracker()
