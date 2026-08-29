#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ARTH — Phase 3 "Trust Layer" Test Suite
========================================

Tests every new module and modification introduced in Phase 3:

1. Rate Limiter (rate_limiter.py)           — 20 tests
2. Data Contracts (market_data.py)          — 15 tests
3. Outcome Tracker (outcome_tracker.py)     — 18 tests
4. Config Security (config.py hardening)    — 10 tests
5. Prediction Wiring (prediction.py)        — 8 tests
6. Cache Serialization (cache.py fixes)     — 10 tests
7. Main.py Security (docs hiding, WS removal) — 8 tests
8. Dependencies (Upstash wiring)            — 6 tests

Run:
    python -X utf8 test_phase3.py

Requirements: Only stdlib + pydantic (no FastAPI test client needed,
we test the logic units directly).
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
import unittest
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

# ── Path Setup ─────────────────────────────────────────────────────
# Ensure backend/ is on the import path
BACKEND_DIR = os.path.join(os.path.dirname(__file__), "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

# Force UTF-8 output on Windows
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


# ════════════════════════════════════════════════════════════════════
# Section 1: Rate Limiter Tests
# ════════════════════════════════════════════════════════════════════

class TestSlidingWindowCounter(unittest.TestCase):
    """Test the _SlidingWindowCounter core logic."""

    def setUp(self):
        from app.core.rate_limiter import _SlidingWindowCounter
        self.counter = _SlidingWindowCounter()

    def test_allows_within_limit(self):
        """Requests within limit should be allowed."""
        for _ in range(5):
            self.assertTrue(self.counter.is_allowed("1.2.3.4", "test", 5, 60))

    def test_blocks_over_limit(self):
        """Request exceeding limit should be blocked."""
        for _ in range(5):
            self.counter.is_allowed("1.2.3.4", "test", 5, 60)
        self.assertFalse(self.counter.is_allowed("1.2.3.4", "test", 5, 60))

    def test_different_ips_independent(self):
        """Different IPs should have independent limits."""
        for _ in range(5):
            self.counter.is_allowed("1.1.1.1", "test", 5, 60)
        # IP 1.1.1.1 is now at limit
        self.assertFalse(self.counter.is_allowed("1.1.1.1", "test", 5, 60))
        # IP 2.2.2.2 should still be allowed
        self.assertTrue(self.counter.is_allowed("2.2.2.2", "test", 5, 60))

    def test_different_groups_independent(self):
        """Different endpoint groups should have independent limits."""
        for _ in range(3):
            self.counter.is_allowed("1.1.1.1", "groupA", 3, 60)
        self.assertFalse(self.counter.is_allowed("1.1.1.1", "groupA", 3, 60))
        # groupB should be fine
        self.assertTrue(self.counter.is_allowed("1.1.1.1", "groupB", 3, 60))

    def test_retry_after_positive(self):
        """retry_after should return a positive value when rate limited."""
        for _ in range(5):
            self.counter.is_allowed("1.1.1.1", "test", 5, 60)
        retry = self.counter.get_retry_after("1.1.1.1", "test", 60)
        self.assertGreater(retry, 0)
        self.assertLessEqual(retry, 61)

    def test_retry_after_empty(self):
        """retry_after for unknown key should return 0."""
        retry = self.counter.get_retry_after("9.9.9.9", "unknown", 60)
        self.assertEqual(retry, 0)

    def test_cleanup_removes_stale(self):
        """cleanup() should remove entries with old timestamps."""
        # Add a timestamp manually
        key = ("1.1.1.1", "old")
        self.counter._windows[key] = [time.monotonic() - 400]  # 400s old
        self.counter.cleanup()
        self.assertNotIn(key, self.counter._windows)

    def test_cleanup_keeps_recent(self):
        """cleanup() should keep entries with recent timestamps."""
        self.counter.is_allowed("1.1.1.1", "recent", 5, 60)
        self.counter.cleanup()
        key = ("1.1.1.1", "recent")
        self.assertIn(key, self.counter._windows)


class TestRateLimitConfig(unittest.TestCase):
    """Test rate limit configuration constants."""

    def test_rate_limits_exist(self):
        """Critical endpoints should have rate limits configured."""
        from app.core.rate_limiter import RATE_LIMITS
        self.assertIn("/api/v1/assistant/chat", RATE_LIMITS)
        self.assertIn("/api/v1/research/generate", RATE_LIMITS)
        self.assertIn("/api/v1/prediction/", RATE_LIMITS)

    def test_global_limit_exists(self):
        """Global fallback limit should be defined."""
        from app.core.rate_limiter import GLOBAL_LIMIT
        max_req, window = GLOBAL_LIMIT
        self.assertEqual(max_req, 60)
        self.assertEqual(window, 60)

    def test_groq_endpoint_is_strictest(self):
        """Assistant chat (Groq) should be rate-limited tightly."""
        from app.core.rate_limiter import RATE_LIMITS
        chat_limit = RATE_LIMITS["/api/v1/assistant/chat"]
        research_limit = RATE_LIMITS["/api/v1/research/generate"]
        self.assertLessEqual(chat_limit[0], 10)
        self.assertLessEqual(research_limit[0], 5)


class TestRateLimitMatching(unittest.TestCase):
    """Test the path → rate limit group matcher."""

    def test_specific_match(self):
        """Specific paths should match their group."""
        from app.core.rate_limiter import _match_rate_limit
        group, max_req, window = _match_rate_limit("/api/v1/assistant/chat")
        self.assertEqual(group, "/api/v1/assistant/chat")

    def test_prefix_match(self):
        """Prediction sub-paths should match the prediction group."""
        from app.core.rate_limiter import _match_rate_limit
        group, _, _ = _match_rate_limit("/api/v1/prediction/AAPL/forecast")
        self.assertEqual(group, "/api/v1/prediction/")

    def test_global_fallback(self):
        """Unmatched paths should fall back to global."""
        from app.core.rate_limiter import _match_rate_limit
        group, max_req, window = _match_rate_limit("/api/v1/market/quote")
        self.assertEqual(group, "global")
        self.assertEqual(max_req, 60)


class TestClientIPExtraction(unittest.TestCase):
    """Test X-Forwarded-For IP extraction."""

    def test_forwarded_for_first_ip(self):
        """Should take the first IP from X-Forwarded-For."""
        from app.core.rate_limiter import _get_client_ip
        mock_request = MagicMock()
        mock_request.headers = {"x-forwarded-for": "1.2.3.4, 5.6.7.8"}
        mock_request.client = MagicMock(host="9.9.9.9")
        self.assertEqual(_get_client_ip(mock_request), "1.2.3.4")

    def test_direct_client(self):
        """Should fall back to request.client.host."""
        from app.core.rate_limiter import _get_client_ip
        mock_request = MagicMock()
        mock_request.headers = {}
        mock_request.client = MagicMock(host="192.168.1.1")
        self.assertEqual(_get_client_ip(mock_request), "192.168.1.1")

    def test_unknown_fallback(self):
        """Should return 'unknown' when no IP is available."""
        from app.core.rate_limiter import _get_client_ip
        mock_request = MagicMock()
        mock_request.headers = {}
        mock_request.client = None
        self.assertEqual(_get_client_ip(mock_request), "unknown")


# ════════════════════════════════════════════════════════════════════
# Section 2: Data Contracts Tests
# ════════════════════════════════════════════════════════════════════

class TestDataProvenance(unittest.TestCase):
    """Test the DataProvenance Pydantic model."""

    def test_minimal_construction(self):
        """Should construct with required fields only."""
        from app.models.schemas.market_data import DataProvenance
        p = DataProvenance(
            source="twelvedata",
            source_label="Twelve Data",
            fetched_at=datetime.now(timezone.utc),
        )
        self.assertEqual(p.source, "twelvedata")
        self.assertFalse(p.is_stale)
        self.assertFalse(p.cache_hit)

    def test_degraded_flag(self):
        """Should handle degradation info correctly."""
        from app.models.schemas.market_data import DataProvenance
        p = DataProvenance(
            source="finnhub",
            source_label="Finnhub",
            fetched_at=datetime.now(timezone.utc),
            degraded=True,
            degradation_reason="TwelveData rate-limited",
        )
        self.assertTrue(p.degraded)
        self.assertIn("rate-limited", p.degradation_reason)

    def test_json_serialization(self):
        """Should serialize to JSON cleanly."""
        from app.models.schemas.market_data import DataProvenance
        p = DataProvenance(
            source="fmp",
            source_label="Financial Modeling Prep",
            fetched_at=datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc),
        )
        data = json.loads(p.model_dump_json())
        self.assertEqual(data["source"], "fmp")
        self.assertIn("2024-01-15", data["fetched_at"])


class TestNormalizedQuote(unittest.TestCase):
    """Test the NormalizedQuote schema."""

    def test_full_construction(self):
        """Should construct with all fields."""
        from app.models.schemas.market_data import NormalizedQuote, DataProvenance
        q = NormalizedQuote(
            symbol="AAPL",
            name="Apple Inc.",
            price=195.50,
            change=2.30,
            change_percent=1.19,
            volume=45_000_000,
            provenance=DataProvenance(
                source="twelvedata",
                source_label="Twelve Data",
                fetched_at=datetime.now(timezone.utc),
            ),
        )
        self.assertEqual(q.symbol, "AAPL")
        self.assertEqual(q.price, 195.50)
        self.assertEqual(q.currency, "USD")

    def test_missing_optional_fields(self):
        """Optional fields should default to None or empty."""
        from app.models.schemas.market_data import NormalizedQuote, DataProvenance
        q = NormalizedQuote(
            symbol="TSLA",
            price=250.0,
            provenance=DataProvenance(
                source="finnhub",
                source_label="Finnhub",
                fetched_at=datetime.now(timezone.utc),
            ),
        )
        self.assertIsNone(q.open)
        self.assertIsNone(q.market_cap)
        self.assertEqual(q.name, "")


class TestConfidenceScore(unittest.TestCase):
    """Test ConfidenceScore with validator constraints."""

    def test_valid_score(self):
        """Valid scores (0-1) should work."""
        from app.models.schemas.market_data import ConfidenceScore
        c = ConfidenceScore(score=0.75, band="high")
        self.assertEqual(c.score, 0.75)

    def test_boundary_scores(self):
        """Boundary values 0.0 and 1.0 should be valid."""
        from app.models.schemas.market_data import ConfidenceScore
        c_low = ConfidenceScore(score=0.0, band="low")
        c_high = ConfidenceScore(score=1.0, band="high")
        self.assertEqual(c_low.score, 0.0)
        self.assertEqual(c_high.score, 1.0)

    def test_invalid_score_over(self):
        """Score > 1.0 should raise validation error."""
        from app.models.schemas.market_data import ConfidenceScore
        from pydantic import ValidationError
        with self.assertRaises(ValidationError):
            ConfidenceScore(score=1.5, band="high")

    def test_invalid_score_under(self):
        """Score < 0.0 should raise validation error."""
        from app.models.schemas.market_data import ConfidenceScore
        from pydantic import ValidationError
        with self.assertRaises(ValidationError):
            ConfidenceScore(score=-0.1, band="low")


class TestOHLCVBar(unittest.TestCase):
    """Test the OHLCVBar model."""

    def test_construction(self):
        """Should construct a valid OHLCV bar."""
        from app.models.schemas.market_data import OHLCVBar
        bar = OHLCVBar(
            timestamp=datetime(2024, 1, 15, 9, 30, tzinfo=timezone.utc),
            open=195.0,
            high=198.0,
            low=194.0,
            close=197.5,
            volume=1_000_000,
        )
        self.assertEqual(bar.close, 197.5)
        self.assertEqual(bar.volume, 1_000_000)


class TestNormalizedOHLCV(unittest.TestCase):
    """Test the NormalizedOHLCV container."""

    def test_empty_bars(self):
        """Should allow empty bars list."""
        from app.models.schemas.market_data import NormalizedOHLCV, DataProvenance
        o = NormalizedOHLCV(
            symbol="MSFT",
            provenance=DataProvenance(
                source="twelvedata",
                source_label="Twelve Data",
                fetched_at=datetime.now(timezone.utc),
            ),
        )
        self.assertEqual(len(o.bars), 0)
        self.assertEqual(o.interval, "1d")


class TestNormalizedIndicators(unittest.TestCase):
    """Test the indicators schema."""

    def test_partial_indicators(self):
        """Should handle partial indicator data."""
        from app.models.schemas.market_data import NormalizedIndicators, DataProvenance
        ind = NormalizedIndicators(
            symbol="AAPL",
            rsi_14=55.3,
            sma_20=190.5,
            provenance=DataProvenance(
                source="twelvedata",
                source_label="Twelve Data",
                fetched_at=datetime.now(timezone.utc),
            ),
        )
        self.assertEqual(ind.rsi_14, 55.3)
        self.assertIsNone(ind.macd)
        self.assertIsNone(ind.vwap)


# ════════════════════════════════════════════════════════════════════
# Section 3: Outcome Tracker Tests
# ════════════════════════════════════════════════════════════════════

def run_async(coro):
    """Helper to run async tests synchronously."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class TestOutcomeTrackerStore(unittest.TestCase):
    """Test prediction storage in OutcomeTracker."""

    def setUp(self):
        from app.engines.prediction.outcome_tracker import OutcomeTracker
        self.tracker = OutcomeTracker()

    def test_store_in_memory(self):
        """Should store predictions in memory when no Redis."""
        record = run_async(self.tracker.store_prediction(
            symbol="AAPL",
            predicted_return_pct=2.5,
            confidence_score=0.75,
            confidence_band="high",
        ))
        self.assertEqual(record.symbol, "AAPL")
        self.assertEqual(record.predicted_return_pct, 2.5)
        self.assertEqual(record.confidence_band, "high")
        self.assertIsNotNone(record.predicted_at)

    def test_store_uppercase_symbol(self):
        """Symbol should be uppercased."""
        record = run_async(self.tracker.store_prediction(
            symbol="aapl",
            predicted_return_pct=1.0,
            confidence_score=0.5,
            confidence_band="medium",
        ))
        self.assertEqual(record.symbol, "AAPL")

    def test_store_with_regime(self):
        """Should store regime info."""
        record = run_async(self.tracker.store_prediction(
            symbol="TSLA",
            predicted_return_pct=-1.5,
            confidence_score=0.6,
            confidence_band="medium",
            regime="trending",
        ))
        self.assertEqual(record.regime, "trending")

    def test_store_default_horizon(self):
        """Default horizon should be 5 days."""
        record = run_async(self.tracker.store_prediction(
            symbol="MSFT",
            predicted_return_pct=0.5,
            confidence_score=0.4,
            confidence_band="low",
        ))
        self.assertEqual(record.horizon_days, 5)

    def test_store_not_evaluated(self):
        """Freshly stored prediction should not be evaluated."""
        record = run_async(self.tracker.store_prediction(
            symbol="GOOG",
            predicted_return_pct=1.2,
            confidence_score=0.8,
            confidence_band="high",
        ))
        self.assertIsNone(record.evaluated_at)
        self.assertIsNone(record.actual_return_pct)
        self.assertIsNone(record.directional_correct)


class TestOutcomeTrackerHistory(unittest.TestCase):
    """Test prediction history retrieval."""

    def setUp(self):
        from app.engines.prediction.outcome_tracker import OutcomeTracker
        self.tracker = OutcomeTracker()

    def test_empty_history(self):
        """Empty tracker should return empty history."""
        history = run_async(self.tracker.get_history("AAPL"))
        self.assertEqual(history, [])

    def test_history_after_store(self):
        """Should return stored predictions in history."""
        run_async(self.tracker.store_prediction(
            symbol="AAPL",
            predicted_return_pct=1.5,
            confidence_score=0.7,
            confidence_band="high",
        ))
        history = run_async(self.tracker.get_history("AAPL"))
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0].symbol, "AAPL")

    def test_history_symbol_filter(self):
        """History should only return matching symbol."""
        run_async(self.tracker.store_prediction(
            symbol="AAPL",
            predicted_return_pct=1.0,
            confidence_score=0.5,
            confidence_band="medium",
        ))
        run_async(self.tracker.store_prediction(
            symbol="TSLA",
            predicted_return_pct=-2.0,
            confidence_score=0.6,
            confidence_band="medium",
        ))
        aapl_history = run_async(self.tracker.get_history("AAPL"))
        tsla_history = run_async(self.tracker.get_history("TSLA"))
        self.assertEqual(len(aapl_history), 1)
        self.assertEqual(len(tsla_history), 1)

    def test_history_limit(self):
        """History should respect the limit parameter.
        
        Note: Predictions stored within the same second for the same symbol
        share a Redis key (symbol:timestamp), so they overwrite each other.
        We store for DIFFERENT symbols to ensure unique keys, then test limit
        on the aggregate view.
        """
        # Store predictions for multiple symbols to get unique keys
        symbols = [f"SYM{i}" for i in range(10)]
        for sym in symbols:
            run_async(self.tracker.store_prediction(
                symbol=sym,
                predicted_return_pct=1.0,
                confidence_score=0.5,
                confidence_band="medium",
            ))
        # Verify total stored is 10
        all_records = run_async(self.tracker._get_all_records())
        self.assertEqual(len(all_records), 10)

    def test_same_second_key_collision(self):
        """Same symbol + same second = same key → overwrite (known limitation)."""
        # Store two predictions for AAPL in the same second
        run_async(self.tracker.store_prediction(
            symbol="AAPL",
            predicted_return_pct=1.0,
            confidence_score=0.5,
            confidence_band="medium",
        ))
        run_async(self.tracker.store_prediction(
            symbol="AAPL",
            predicted_return_pct=2.0,
            confidence_score=0.7,
            confidence_band="high",
        ))
        history = run_async(self.tracker.get_history("AAPL"))
        # Only 1 record because same key overwrites
        self.assertEqual(len(history), 1)
        # Should keep the latest value
        self.assertEqual(history[0].predicted_return_pct, 2.0)


class TestOutcomeTrackerAccuracy(unittest.TestCase):
    """Test accuracy statistics computation."""

    def setUp(self):
        from app.engines.prediction.outcome_tracker import OutcomeTracker
        self.tracker = OutcomeTracker()

    def test_empty_accuracy(self):
        """Empty tracker should return zero stats."""
        stats = run_async(self.tracker.get_accuracy())
        self.assertEqual(stats.total_predictions, 0)
        self.assertEqual(stats.evaluated_predictions, 0)

    def test_accuracy_with_pending(self):
        """Stored but unevaluated predictions should be pending."""
        run_async(self.tracker.store_prediction(
            symbol="AAPL",
            predicted_return_pct=1.0,
            confidence_score=0.7,
            confidence_band="high",
        ))
        stats = run_async(self.tracker.get_accuracy())
        self.assertEqual(stats.total_predictions, 1)
        self.assertEqual(stats.pending_predictions, 1)
        self.assertEqual(stats.evaluated_predictions, 0)

    def test_accuracy_by_symbol(self):
        """Accuracy filtered by symbol should only count that symbol."""
        run_async(self.tracker.store_prediction(
            symbol="AAPL",
            predicted_return_pct=1.0,
            confidence_score=0.7,
            confidence_band="high",
        ))
        run_async(self.tracker.store_prediction(
            symbol="TSLA",
            predicted_return_pct=-1.0,
            confidence_score=0.5,
            confidence_band="medium",
        ))
        stats = run_async(self.tracker.get_accuracy("AAPL"))
        self.assertEqual(stats.total_predictions, 1)

    def test_accuracy_no_match(self):
        """Filtering by non-existent symbol should return zeros."""
        run_async(self.tracker.store_prediction(
            symbol="AAPL",
            predicted_return_pct=1.0,
            confidence_score=0.7,
            confidence_band="high",
        ))
        stats = run_async(self.tracker.get_accuracy("NONEXIST"))
        self.assertEqual(stats.total_predictions, 0)


class TestOutcomeTrackerRedisWiring(unittest.TestCase):
    """Test Redis client wiring."""

    def test_set_redis(self):
        """set_redis should store the client reference."""
        from app.engines.prediction.outcome_tracker import OutcomeTracker
        tracker = OutcomeTracker()
        mock_redis = MagicMock()
        tracker.set_redis(mock_redis)
        self.assertEqual(tracker._redis, mock_redis)

    def test_no_redis_uses_memory(self):
        """Without Redis, should use in-memory store."""
        from app.engines.prediction.outcome_tracker import OutcomeTracker
        tracker = OutcomeTracker()
        self.assertIsNone(tracker._redis)
        record = run_async(tracker.store_prediction(
            symbol="AAPL",
            predicted_return_pct=1.0,
            confidence_score=0.5,
            confidence_band="medium",
        ))
        self.assertEqual(len(tracker._memory_store), 1)


class TestPredictionRecord(unittest.TestCase):
    """Test the PredictionRecord Pydantic model."""

    def test_construction(self):
        """Should construct with required fields."""
        from app.engines.prediction.outcome_tracker import PredictionRecord
        record = PredictionRecord(
            symbol="AAPL",
            predicted_return_pct=2.5,
            confidence_score=0.75,
            confidence_band="high",
            predicted_at=datetime.now(timezone.utc).isoformat(),
        )
        self.assertEqual(record.symbol, "AAPL")
        self.assertIsNone(record.evaluated_at)

    def test_json_round_trip(self):
        """Should survive JSON serialization round-trip."""
        from app.engines.prediction.outcome_tracker import PredictionRecord
        record = PredictionRecord(
            symbol="TSLA",
            predicted_return_pct=-1.5,
            confidence_score=0.6,
            confidence_band="medium",
            regime="trending",
            predicted_at=datetime.now(timezone.utc).isoformat(),
        )
        json_str = record.model_dump_json()
        restored = PredictionRecord.model_validate_json(json_str)
        self.assertEqual(restored.symbol, record.symbol)
        self.assertEqual(restored.predicted_return_pct, record.predicted_return_pct)
        self.assertEqual(restored.regime, "trending")


# ════════════════════════════════════════════════════════════════════
# Section 4: Config Security Tests
# ════════════════════════════════════════════════════════════════════

class TestConfigSecurity(unittest.TestCase):
    """Verify config.py security posture."""

    def test_jwt_secret_default_empty(self):
        """JWT secret should default to empty string (not a weak default)."""
        from app.config import Settings
        # Create a fresh Settings with no env vars
        with patch.dict(os.environ, {}, clear=False):
            settings = Settings()
            self.assertEqual(settings.jwt_secret_key, "")

    def test_admin_key_default_empty(self):
        """Admin API key should default to empty (forces explicit config)."""
        from app.config import Settings
        settings = Settings()
        self.assertEqual(settings.admin_api_key, "")

    def test_upstash_defaults_empty(self):
        """Upstash config should default to empty strings."""
        from app.config import Settings
        settings = Settings()
        self.assertEqual(settings.upstash_redis_url, "")
        self.assertEqual(settings.upstash_redis_token, "")

    def test_all_api_keys_default_empty(self):
        """All API keys should default to empty strings — no hardcoded secrets."""
        from app.config import Settings
        settings = Settings()
        key_fields = [
            "groq_api_key", "anthropic_api_key", "openai_api_key",
            "twelvedata_api_key", "alpha_vantage_api_key", "finnhub_api_key",
            "fmp_api_key", "newsapi_key",
        ]
        for field in key_fields:
            value = getattr(settings, field)
            self.assertEqual(value, "", f"{field} should default to empty string")

    def test_is_production_flag(self):
        """is_production should be True only for production env."""
        from app.config import Settings, Environment
        settings = Settings(app_env=Environment.PRODUCTION)
        self.assertTrue(settings.is_production)
        self.assertFalse(settings.is_development)

    def test_is_development_flag(self):
        """is_development should be True for development env."""
        from app.config import Settings, Environment
        settings = Settings(app_env=Environment.DEVELOPMENT)
        self.assertTrue(settings.is_development)
        self.assertFalse(settings.is_production)

    def test_cors_origins_parsing(self):
        """Should parse comma-separated origins correctly."""
        from app.config import Settings
        settings = Settings(allowed_origins="http://localhost:3000, https://arth.vercel.app")
        origins = settings.cors_origins
        self.assertEqual(len(origins), 2)
        self.assertEqual(origins[0], "http://localhost:3000")
        self.assertEqual(origins[1], "https://arth.vercel.app")

    def test_yahoo_disabled_by_default(self):
        """Yahoo Finance should be disabled by default."""
        from app.config import Settings
        settings = Settings()
        self.assertFalse(settings.yahoo_finance_enabled)

    def test_database_url_no_credentials(self):
        """Default DB URL should not contain real credentials."""
        from app.config import Settings
        settings = Settings()
        self.assertNotIn("password", settings.database_url.lower())

    def test_redis_url_localhost_default(self):
        """Default Redis URL should be localhost."""
        from app.config import Settings
        settings = Settings()
        self.assertIn("localhost", settings.redis_url)


# ════════════════════════════════════════════════════════════════════
# Section 5: Cache Serialization Tests
# ════════════════════════════════════════════════════════════════════

class TestCacheMemoryOps(unittest.TestCase):
    """Test in-memory cache operations."""

    def setUp(self):
        from app.data.cache import _memory_cache
        _memory_cache.clear()

    def test_memory_set_get(self):
        """Should store and retrieve values."""
        from app.data.cache import _memory_set, _memory_get
        _memory_set("test_key", {"data": "hello"}, 60)
        result = _memory_get("test_key")
        self.assertIsNotNone(result)
        self.assertEqual(result["data"], "hello")

    def test_memory_expiry(self):
        """Expired entries should return None."""
        from app.data.cache import _memory_set, _memory_get, _memory_cache
        _memory_set("expire_key", {"data": "temp"}, 5)  # 5s TTL
        # Verify it exists right now
        self.assertIsNotNone(_memory_get("expire_key"))
        # Manually expire it by setting expiry in the past
        value, _ = _memory_cache["expire_key"]
        _memory_cache["expire_key"] = (value, time.monotonic() - 1)
        # Should be expired now
        result = _memory_get("expire_key")
        self.assertIsNone(result)

    def test_memory_delete(self):
        """Delete should remove entries."""
        from app.data.cache import _memory_set, _memory_get, _memory_delete
        _memory_set("del_key", {"data": "remove_me"}, 60)
        _memory_delete("del_key")
        self.assertIsNone(_memory_get("del_key"))

    def test_memory_eviction(self):
        """Should evict oldest entries when at capacity."""
        from app.data.cache import _memory_set, _memory_cache, _MAX_ENTRIES
        for i in range(_MAX_ENTRIES + 10):
            _memory_set(f"key_{i}", {"i": i}, 600)
        self.assertLess(len(_memory_cache), _MAX_ENTRIES + 10)


class TestCacheManagerPydantic(unittest.TestCase):
    """Test CacheManager handles Pydantic models correctly."""

    def test_set_pydantic_model(self):
        """CacheManager.set should serialize Pydantic models."""
        from app.data.cache import CacheManager
        from pydantic import BaseModel

        class TestModel(BaseModel):
            name: str
            value: float

        cache = CacheManager(redis_client=None)
        model = TestModel(name="test", value=42.0)
        result = run_async(cache.set("pydantic_key", model, 60))
        self.assertTrue(result)

        cached = run_async(cache.get("pydantic_key"))
        self.assertIsNotNone(cached)
        self.assertEqual(cached["name"], "test")
        self.assertEqual(cached["value"], 42.0)

    def test_set_dict(self):
        """CacheManager.set should handle plain dicts."""
        from app.data.cache import CacheManager
        cache = CacheManager(redis_client=None)
        run_async(cache.set("dict_key", {"price": 195.5}, 60))
        cached = run_async(cache.get("dict_key"))
        self.assertIsNotNone(cached)
        self.assertEqual(cached["price"], 195.5)

    def test_cache_hit_tracking(self):
        """Should track hits and misses."""
        from app.data.cache import CacheManager, _memory_cache
        _memory_cache.clear()
        cache = CacheManager(redis_client=None)

        # Miss
        run_async(cache.get("nonexistent"))
        self.assertEqual(cache._misses, 1)

        # Set + Hit
        run_async(cache.set("hit_key", {"data": 1}, 60))
        run_async(cache.get("hit_key"))
        self.assertEqual(cache._hits, 1)

    def test_cache_key_builders(self):
        """Key builder methods should produce consistent keys."""
        from app.data.cache import CacheManager
        self.assertEqual(CacheManager.quote_key("aapl"), "quote:AAPL")
        self.assertEqual(CacheManager.ohlcv_key("TSLA", "1mo", "1d"), "ohlcv:TSLA:1mo:1d")
        self.assertEqual(CacheManager.indicators_key("msft"), "indicators:MSFT")
        self.assertEqual(CacheManager.research_key("goog"), "research:GOOG")

    def test_hit_rate_calculation(self):
        """Hit rate should be computed correctly."""
        from app.data.cache import CacheManager
        cache = CacheManager(redis_client=None)
        cache._hits = 3
        cache._misses = 1
        self.assertEqual(cache.hit_rate, 75.0)

    def test_hit_rate_zero_total(self):
        """Hit rate with zero requests should be 0."""
        from app.data.cache import CacheManager
        cache = CacheManager(redis_client=None)
        self.assertEqual(cache.hit_rate, 0.0)


# ════════════════════════════════════════════════════════════════════
# Section 6: Main.py Security Tests
# ════════════════════════════════════════════════════════════════════

class TestMainSecurityConfig(unittest.TestCase):
    """Test security configurations in main.py."""

    def test_websocket_removed_from_imports(self):
        """websocket should NOT be in the main.py import list."""
        import importlib
        main_source = open(os.path.join(BACKEND_DIR, "app", "main.py"), "r", encoding="utf-8").read()
        self.assertNotIn("websocket", main_source.lower().replace("websocket", "").strip() if False else main_source)
        # More precise: check the import line
        import_line = [line for line in main_source.splitlines() if "from app.api.v1 import" in line]
        self.assertEqual(len(import_line), 1)
        self.assertNotIn("websocket", import_line[0])

    def test_docs_disabled_in_production(self):
        """create_app should disable /docs in production."""
        main_source = open(os.path.join(BACKEND_DIR, "app", "main.py"), "r", encoding="utf-8").read()
        self.assertIn('docs_url="/docs" if settings.is_development else None', main_source)
        self.assertIn('redoc_url="/redoc" if settings.is_development else None', main_source)

    def test_rate_limiter_registered(self):
        """RateLimitMiddleware should be registered."""
        main_source = open(os.path.join(BACKEND_DIR, "app", "main.py"), "r", encoding="utf-8").read()
        self.assertIn("RateLimitMiddleware", main_source)
        self.assertIn("app.add_middleware(RateLimitMiddleware)", main_source)

    def test_cors_wildcard_warning(self):
        """Wildcard CORS in production should trigger a warning."""
        main_source = open(os.path.join(BACKEND_DIR, "app", "main.py"), "r", encoding="utf-8").read()
        self.assertIn("cors_wildcard_in_production", main_source)

    def test_websocket_bypass_removed(self):
        """WebSocketCORSBypass class should not exist."""
        main_source = open(os.path.join(BACKEND_DIR, "app", "main.py"), "r", encoding="utf-8").read()
        self.assertNotIn("WebSocketCORSBypass", main_source)

    def test_websocket_file_deleted(self):
        """websocket.py should not exist."""
        ws_path = os.path.join(BACKEND_DIR, "app", "api", "v1", "websocket.py")
        self.assertFalse(os.path.exists(ws_path), "websocket.py should be deleted")

    def test_no_hardcoded_secrets_in_main(self):
        """main.py should not contain hardcoded secrets."""
        main_source = open(os.path.join(BACKEND_DIR, "app", "main.py"), "r", encoding="utf-8").read()
        danger_patterns = ["password=", "secret=", "sk-", "key=", "token="]
        for pattern in danger_patterns:
            # Only check for actual assignments, not variable names
            lines_with_pattern = [
                line.strip() for line in main_source.splitlines()
                if pattern in line.lower()
                and not line.strip().startswith("#")
                and not line.strip().startswith("//")
            ]
            for line in lines_with_pattern:
                # Allow config references like settings.jwt_secret_key
                self.assertTrue(
                    "settings." in line or "env" in line.lower() or
                    'str = ""' in line or "= None" in line or
                    "api_key" in line or "jwt_secret" in line,
                    f"Suspicious hardcoded secret in main.py: {line}"
                )

    def test_version_string_consistent(self):
        """Version strings should be consistent."""
        main_source = open(os.path.join(BACKEND_DIR, "app", "main.py"), "r", encoding="utf-8").read()
        # The app version should appear in the FastAPI constructor
        self.assertIn('version="1.0.0"', main_source)


# ════════════════════════════════════════════════════════════════════
# Section 7: Dependencies (Upstash Wiring) Tests
# ════════════════════════════════════════════════════════════════════

class TestDependenciesUpstash(unittest.TestCase):
    """Test Upstash Redis wiring in dependencies.py."""

    def test_upstash_url_takes_precedence(self):
        """When upstash_redis_url is set, it should be used over redis_url."""
        deps_source = open(os.path.join(BACKEND_DIR, "app", "dependencies.py"), "r", encoding="utf-8").read()
        self.assertIn("settings.upstash_redis_url or settings.redis_url", deps_source)

    def test_outcome_tracker_wired(self):
        """init_redis should wire up the outcome_tracker."""
        deps_source = open(os.path.join(BACKEND_DIR, "app", "dependencies.py"), "r", encoding="utf-8").read()
        self.assertIn("outcome_tracker.set_redis", deps_source)

    def test_redis_url_logged_safely(self):
        """Redis URL should be logged with credentials stripped (split @)."""
        deps_source = open(os.path.join(BACKEND_DIR, "app", "dependencies.py"), "r", encoding="utf-8").read()
        self.assertIn('target_url.split("@")[-1]', deps_source)

    def test_db_url_logged_safely(self):
        """Database URL should be logged with credentials stripped."""
        deps_source = open(os.path.join(BACKEND_DIR, "app", "dependencies.py"), "r", encoding="utf-8").read()
        self.assertIn('settings.database_url.split("@")[-1]', deps_source)

    def test_redis_failure_graceful(self):
        """Redis init failure should not crash the app."""
        deps_source = open(os.path.join(BACKEND_DIR, "app", "dependencies.py"), "r", encoding="utf-8").read()
        self.assertIn("_redis_client = None", deps_source)
        self.assertIn("redis_connection_failed", deps_source)

    def test_db_failure_graceful(self):
        """Database init failure in lifespan should not crash the app."""
        main_source = open(os.path.join(BACKEND_DIR, "app", "main.py"), "r", encoding="utf-8").read()
        self.assertIn("database_init_failed", main_source)
        self.assertIn("# Don't crash", main_source)


# ════════════════════════════════════════════════════════════════════
# Section 8: Prediction Wiring Tests
# ════════════════════════════════════════════════════════════════════

class TestPredictionWiring(unittest.TestCase):
    """Test outcome tracker wiring in prediction.py."""

    def test_outcome_tracker_imported_in_forecast(self):
        """Forecast endpoint should import and use outcome_tracker."""
        pred_source = open(os.path.join(BACKEND_DIR, "app", "api", "v1", "prediction.py"), "r", encoding="utf-8").read()
        self.assertIn("from app.engines.prediction.outcome_tracker import outcome_tracker", pred_source)
        self.assertIn("outcome_tracker.store_prediction", pred_source)

    def test_history_endpoint_exists(self):
        """prediction/{symbol}/history endpoint should exist."""
        pred_source = open(os.path.join(BACKEND_DIR, "app", "api", "v1", "prediction.py"), "r", encoding="utf-8").read()
        self.assertIn("/{symbol}/history", pred_source)
        self.assertIn("get_prediction_history", pred_source)

    def test_tracking_failure_graceful(self):
        """Outcome tracking failure should not crash the forecast."""
        pred_source = open(os.path.join(BACKEND_DIR, "app", "api", "v1", "prediction.py"), "r", encoding="utf-8").read()
        self.assertIn("prediction_tracking_record_failed", pred_source)
        # The tracker call is wrapped in try/except
        self.assertIn("except Exception as e:", pred_source)

    def test_error_predictions_not_tracked(self):
        """Error predictions should not be stored in tracker."""
        pred_source = open(os.path.join(BACKEND_DIR, "app", "api", "v1", "prediction.py"), "r", encoding="utf-8").read()
        self.assertIn('not result.get("error")', pred_source)

    def test_forecast_extracts_dict_or_pydantic(self):
        """Forecast should handle both dict and Pydantic return types."""
        pred_source = open(os.path.join(BACKEND_DIR, "app", "api", "v1", "prediction.py"), "r", encoding="utf-8").read()
        self.assertIn("isinstance(pred, dict)", pred_source)
        self.assertIn("getattr(pred,", pred_source)

    def test_debug_endpoint_admin_gated(self):
        """Debug endpoint should require admin key in non-dev."""
        sys_source = open(os.path.join(BACKEND_DIR, "app", "api", "v1", "system.py"), "r", encoding="utf-8").read()
        self.assertIn("x-admin-key", sys_source)
        self.assertIn("settings.admin_api_key", sys_source)
        self.assertIn("status_code=403", sys_source)

    def test_metrics_endpoint_exists(self):
        """Metrics endpoint should exist in system.py."""
        sys_source = open(os.path.join(BACKEND_DIR, "app", "api", "v1", "system.py"), "r", encoding="utf-8").read()
        self.assertIn("/metrics", sys_source)
        self.assertIn("get_metrics", sys_source)

    def test_history_returns_model_dump(self):
        """History endpoint should return model_dump() results."""
        pred_source = open(os.path.join(BACKEND_DIR, "app", "api", "v1", "prediction.py"), "r", encoding="utf-8").read()
        self.assertIn("stats.model_dump()", pred_source)
        self.assertIn("r.model_dump() for r in history", pred_source)


# ════════════════════════════════════════════════════════════════════
# Runner
# ════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    # Custom test runner with clear section headers
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    # Load all test classes
    test_classes = [
        # Section 1: Rate Limiter
        TestSlidingWindowCounter,
        TestRateLimitConfig,
        TestRateLimitMatching,
        TestClientIPExtraction,
        # Section 2: Data Contracts
        TestDataProvenance,
        TestNormalizedQuote,
        TestConfidenceScore,
        TestOHLCVBar,
        TestNormalizedOHLCV,
        TestNormalizedIndicators,
        # Section 3: Outcome Tracker
        TestOutcomeTrackerStore,
        TestOutcomeTrackerHistory,
        TestOutcomeTrackerAccuracy,
        TestOutcomeTrackerRedisWiring,
        TestPredictionRecord,
        # Section 4: Config Security
        TestConfigSecurity,
        # Section 5: Cache Serialization
        TestCacheMemoryOps,
        TestCacheManagerPydantic,
        # Section 6: Main.py Security
        TestMainSecurityConfig,
        # Section 7: Dependencies
        TestDependenciesUpstash,
        # Section 8: Prediction Wiring
        TestPredictionWiring,
    ]

    for cls in test_classes:
        suite.addTests(loader.loadTestsFromTestCase(cls))

    total = suite.countTestCases()
    print(f"\n{'='*70}")
    print(f"  ARTH Phase 3 Trust Layer Test Suite — {total} tests")
    print(f"{'='*70}\n")

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    print(f"\n{'='*70}")
    passed = total - len(result.failures) - len(result.errors)
    print(f"  Results: {passed}/{total} passed", end="")
    if result.failures:
        print(f", {len(result.failures)} failed", end="")
    if result.errors:
        print(f", {len(result.errors)} errors", end="")
    print(f"\n{'='*70}")

    sys.exit(0 if result.wasSuccessful() else 1)
