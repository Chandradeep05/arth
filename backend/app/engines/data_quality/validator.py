"""
Data quality validation layer (Module 08 — Foundation).

Validates every data point entering the system against:
- Schema contracts (required fields, types)
- Range checks (price > 0, volume >= 0, OHLC relationship)
- Freshness thresholds (is this data too old?)
- Anomaly detection (>20% single-day moves flagged)

Data quality failures are NEVER silently swallowed — they're logged
and surfaced to users via staleness indicators.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.core.logging import get_logger

logger = get_logger(__name__)


class ValidationResult:
    """Result of data validation."""

    def __init__(self):
        self.is_valid: bool = True
        self.warnings: List[str] = []
        self.errors: List[str] = []
        self.flags: List[str] = []  # Anomaly flags for the UI

    def add_warning(self, msg: str) -> None:
        self.warnings.append(msg)

    def add_error(self, msg: str) -> None:
        self.errors.append(msg)
        self.is_valid = False

    def add_flag(self, msg: str) -> None:
        """Anomaly flags are shown to the user."""
        self.flags.append(msg)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "is_valid": self.is_valid,
            "warnings": self.warnings,
            "errors": self.errors,
            "flags": self.flags,
        }


class DataQualityValidator:
    """Validates market data for schema, range, and freshness."""

    def __init__(
        self,
        price_anomaly_threshold_pct: float = 20.0,
        freshness_threshold_live: int = 60,
        freshness_threshold_fundamentals: int = 86400,
    ):
        self._price_anomaly_threshold = price_anomaly_threshold_pct
        self._freshness_live = freshness_threshold_live
        self._freshness_fundamentals = freshness_threshold_fundamentals

    def validate_quote(self, data: Dict[str, Any]) -> ValidationResult:
        """Validate a stock quote data point."""
        result = ValidationResult()

        # Required fields
        required = ["symbol", "price", "volume", "timestamp"]
        for field in required:
            if field not in data or data[field] is None:
                result.add_error(f"Missing required field: {field}")

        if not result.is_valid:
            return result

        # Range checks
        price = data.get("price", 0)
        if price <= 0:
            result.add_error(f"Invalid price: {price} (must be > 0)")

        volume = data.get("volume", 0)
        if volume < 0:
            result.add_error(f"Invalid volume: {volume} (must be >= 0)")

        # OHLC relationship checks
        high = data.get("high", 0)
        low = data.get("low", 0)
        open_price = data.get("open", 0)

        if high > 0 and low > 0:
            if high < low:
                result.add_error(f"Invalid OHLC: high ({high}) < low ({low})")
            if open_price > 0 and (open_price > high or open_price < low):
                result.add_warning(f"Open ({open_price}) outside H/L range [{low}, {high}]")

        # Price anomaly detection
        prev_close = data.get("previous_close", 0)
        if prev_close > 0 and price > 0:
            pct_change = abs((price - prev_close) / prev_close * 100)
            if pct_change > self._price_anomaly_threshold:
                result.add_flag(
                    f"Large price move: {pct_change:.1f}% "
                    f"(threshold: {self._price_anomaly_threshold}%)"
                )
                logger.warning(
                    "price_anomaly_detected",
                    symbol=data.get("symbol"),
                    change_pct=round(pct_change, 2),
                    threshold=self._price_anomaly_threshold,
                )

        return result

    def validate_ohlcv_bars(self, bars: List[Dict[str, Any]]) -> ValidationResult:
        """Validate a list of OHLCV bars."""
        result = ValidationResult()

        if not bars:
            result.add_error("Empty OHLCV data")
            return result

        for i, bar in enumerate(bars):
            # Range checks
            for field in ["open", "high", "low", "close"]:
                val = bar.get(field, 0)
                if val <= 0:
                    result.add_warning(f"Bar {i}: {field} = {val} (should be > 0)")

            vol = bar.get("volume", 0)
            if vol < 0:
                result.add_warning(f"Bar {i}: negative volume ({vol})")

            high = bar.get("high", 0)
            low = bar.get("low", 0)
            if high > 0 and low > 0 and high < low:
                result.add_warning(f"Bar {i}: high ({high}) < low ({low})")

        # Check for chronological order
        if len(bars) >= 2:
            dates = [bar.get("date", "") for bar in bars]
            if dates != sorted(dates):
                result.add_warning("OHLCV bars are not in chronological order")

        return result

    def check_freshness(
        self,
        timestamp: datetime | str | None,
        data_type: str = "live",
    ) -> Dict[str, Any]:
        """
        Check data freshness against thresholds.

        Returns freshness metadata for the UI.
        """
        if timestamp is None:
            return {
                "is_stale": True,
                "age_seconds": -1,
                "label": "Unknown age",
            }

        if isinstance(timestamp, str):
            try:
                timestamp = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            except ValueError:
                return {
                    "is_stale": True,
                    "age_seconds": -1,
                    "label": "Invalid timestamp",
                }

        now = datetime.now(timezone.utc)
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)

        age = (now - timestamp).total_seconds()
        threshold = (
            self._freshness_live
            if data_type == "live"
            else self._freshness_fundamentals
        )

        is_stale = age > threshold

        if age < 30:
            label = "Just now"
        elif age < 60:
            label = "~15s delayed"
        elif age < 300:
            label = f"{int(age / 60)}m ago"
        elif age < 3600:
            label = f"{int(age / 60)}m ago"
        elif age < 86400:
            label = f"{int(age / 3600)}h ago"
        else:
            label = f"{int(age / 86400)}d ago"

        if is_stale:
            logger.info("data_staleness_detected", data_type=data_type, age_seconds=round(age))

        return {
            "is_stale": is_stale,
            "age_seconds": round(age, 1),
            "label": label,
        }
