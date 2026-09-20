import sys
import os
from pathlib import Path
import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
import numpy as np
import pandas as pd

# Ensure app is in path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.engines.assistant.engine import AssistantEngine
from app.engines.prediction.outcome_tracker import outcome_tracker, OutcomeTracker, PredictionRecord
from app.core.quotas import check_user_quota
from app.engines.prediction.feature_engineering import FeatureEngineer
from app.engines.market.indicators import _compute_rsi
from app.llm.groq_client import GroqClient
from fastapi import HTTPException


# --- 1. Session Tenant Isolation Tests ---
def test_session_ownership_enforced():
    engine = AssistantEngine()
    # User A creates session
    sess_a = engine.get_or_create_session(session_id="sess_1", user_id="user_a")
    assert sess_a.owner_user_id == "user_a"
    
    # User B tries to get it
    sess_b = engine.get_session(session_id="sess_1", user_id="user_b")
    assert sess_b is None

def test_session_list_filtered_by_user():
    engine = AssistantEngine()
    engine._sessions.clear() # clear for test
    engine.get_or_create_session(session_id="sess_1", user_id="user_a")
    engine.get_or_create_session(session_id="sess_2", user_id="user_b")
    
    lst = engine.list_sessions(user_id="user_a")
    assert len(lst) == 1
    assert lst[0]["session_id"] == "sess_1"

def test_session_delete_denied_for_other_user():
    engine = AssistantEngine()
    engine._sessions.clear() # clear for test
    engine.get_or_create_session(session_id="sess_1", user_id="user_a")
    
    # User B tries to delete
    res = engine.delete_session("sess_1", user_id="user_b")
    assert res is False
    assert engine.get_session("sess_1", user_id="user_a") is not None

def test_session_overwrite_prevented():
    engine = AssistantEngine()
    engine._sessions.clear() # clear for test
    engine.get_or_create_session(session_id="sess_1", user_id="user_a")
    
    # User B tries to create with same id
    sess_b = engine.get_or_create_session(session_id="sess_1", user_id="user_b")
    assert sess_b.session_id != "sess_1"
    assert sess_b.owner_user_id == "user_b"

def test_session_id_none_on_mismatch():
    engine = AssistantEngine()
    engine._sessions.clear() # clear for test
    engine.get_or_create_session(session_id="sess_1", user_id="user_a")
    
    # Implementation sets session_id = None internally, which generates a fresh ID
    sess_b = engine.get_or_create_session(session_id="sess_1", user_id="user_b")
    assert sess_b.session_id != "sess_1"
    assert sess_b.session_id is not None

# --- 2. Prediction Outcome Tracker Tests ---
@pytest.mark.asyncio
async def test_store_prediction_full_uuid():
    tracker = OutcomeTracker()
    record = await tracker.store_prediction(
        symbol="AAPL",
        predicted_return_pct=1.0,
        confidence_score=0.8,
        confidence_band="high",
        reference_price=150.0
    )
    assert len(record.prediction_id) == 32

@pytest.mark.asyncio
async def test_store_prediction_ungradable_no_reference():
    tracker = OutcomeTracker()
    record = await tracker.store_prediction(
        symbol="AAPL",
        predicted_return_pct=1.0,
        confidence_score=0.8,
        confidence_band="high",
        reference_price=None
    )
    assert record.evaluation_status == "ungradable"

@pytest.mark.asyncio
async def test_neutral_direction_classification():
    from app.engines.prediction.outcome_tracker import _classify_direction
    assert _classify_direction(0.49) == "neutral"
    assert _classify_direction(-0.49) == "neutral"

@pytest.mark.asyncio
async def test_bullish_direction_classification():
    from app.engines.prediction.outcome_tracker import _classify_direction
    assert _classify_direction(0.51) == "bullish"

@pytest.mark.asyncio
async def test_bearish_direction_classification():
    from app.engines.prediction.outcome_tracker import _classify_direction
    assert _classify_direction(-0.51) == "bearish"

@pytest.mark.asyncio
async def test_evaluate_pending_skips_immature():
    tracker = OutcomeTracker()
    record = await tracker.store_prediction(
        symbol="AAPL",
        predicted_return_pct=1.0,
        confidence_score=0.8,
        confidence_band="high",
        reference_price=150.0,
        horizon_days=5
    )
    count = await tracker.evaluate_pending(fetch_price_func=AsyncMock(return_value=160.0))
    assert count == 0
    assert tracker._memory_store[f"prediction_track:{record.prediction_id}"].evaluation_status == "pending"

@pytest.mark.asyncio
async def test_evaluate_pending_skips_ungradable():
    tracker = OutcomeTracker()
    record = await tracker.store_prediction(
        symbol="AAPL",
        predicted_return_pct=1.0,
        confidence_score=0.8,
        confidence_band="high",
        reference_price=None
    )
    count = await tracker.evaluate_pending(fetch_price_func=AsyncMock(return_value=160.0))
    assert count == 0
    assert tracker._memory_store[f"prediction_track:{record.prediction_id}"].evaluation_status == "ungradable"
    
@pytest.mark.asyncio
async def test_unique_prediction_ids():
    tracker = OutcomeTracker()
    ids = set()
    for _ in range(100):
        record = await tracker.store_prediction(
            symbol="AAPL",
            predicted_return_pct=1.0,
            confidence_score=0.8,
            confidence_band="high",
            reference_price=150.0
        )
        ids.add(record.prediction_id)
    assert len(ids) == 100

# --- 3. Quota Enforcement Tests ---
@pytest.mark.asyncio
async def test_quota_check_allows_within_limit():
    redis_mock = AsyncMock()
    redis_mock.eval.return_value = 1
    # Should not raise
    await check_user_quota("user_1", "chat", redis_mock)

@pytest.mark.asyncio
async def test_quota_check_rejects_exceeded():
    redis_mock = AsyncMock()
    redis_mock.eval.return_value = -1
    with pytest.raises(HTTPException) as exc:
        await check_user_quota("user_1", "chat", redis_mock)
    assert exc.value.status_code == 429

@pytest.mark.asyncio
async def test_quota_skipped_without_redis():
    # Should not raise
    await check_user_quota("user_1", "chat", None)

# --- 4. Feature Engineering NaN Tests ---
@pytest.mark.asyncio
async def test_live_fundamentals_are_nan():
    fe = FeatureEngineer()
    with patch("app.engines.prediction.feature_engineering.market_data") as mock_md:
        mock_hist = MagicMock()
        mock_hist.available = True
        
        dates = pd.date_range(start="2023-01-01", periods=30)
        df = pd.DataFrame({
            "Open": np.random.rand(30)*100,
            "High": np.random.rand(30)*100,
            "Low": np.random.rand(30)*100,
            "Close": np.random.rand(30)*100,
            "Volume": np.random.rand(30)*1000
        }, index=dates)
        mock_hist.data = df
        mock_md.get_history = AsyncMock(return_value=mock_hist)
        
        features = await fe.build_live_features("AAPL")
        assert np.isnan(features["pe_ratio"])
        assert np.isnan(features["pb_ratio"])
        assert np.isnan(features["market_cap_log"])

# --- 5. Indicator Tests ---
def test_rsi_flat_market_returns_50():
    closes = pd.Series([100.0] * 20)
    rsi = _compute_rsi(closes, 14)
    assert rsi == 50.0

def test_rsi_all_gains_returns_100():
    closes = pd.Series([float(i) for i in range(100, 120)])
    rsi = _compute_rsi(closes, 14)
    assert rsi == 100.0

def test_rsi_normal_calculation():
    closes = pd.Series([100.0, 102.0, 101.0, 103.0, 102.0, 104.0, 103.0, 105.0, 104.0, 106.0, 105.0, 107.0, 106.0, 108.0, 107.0, 109.0, 108.0, 110.0])
    rsi = _compute_rsi(closes, 14)
    assert 0 < rsi < 100

# --- 6. Groq Error Classification Tests ---
def test_retryable_429():
    assert GroqClient._is_retryable_error(Exception("HTTP 429 Too Many Requests")) is True

def test_retryable_500():
    assert GroqClient._is_retryable_error(Exception("HTTP 500 Internal Server Error")) is True

def test_non_retryable_401():
    assert GroqClient._is_retryable_error(Exception("HTTP 401 Unauthorized")) is False

def test_non_retryable_403():
    assert GroqClient._is_retryable_error(Exception("HTTP 403 Forbidden")) is False

def test_non_retryable_400():
    assert GroqClient._is_retryable_error(Exception("HTTP 400 Bad Request")) is False

# --- 7. Direction Scoring Regression Tests ---
@pytest.mark.asyncio
async def test_neutral_predicted_vs_bullish_actual():
    tracker = OutcomeTracker()
    record = await tracker.store_prediction(
        symbol="AAPL",
        predicted_return_pct=0.1,
        confidence_score=0.8,
        confidence_band="high",
        reference_price=100.0,
        horizon_days=5
    )
    from datetime import datetime, timedelta, timezone
    old_time = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
    tracker._memory_store[f"prediction_track:{record.prediction_id}"].predicted_at = old_time
    
    async def fetch_price(sym): return 102.0
    
    await tracker.evaluate_pending(fetch_price_func=fetch_price)
    updated_record = tracker._memory_store[f"prediction_track:{record.prediction_id}"]
    
    assert updated_record.actual_class == "bullish"
    assert updated_record.predicted_class == "neutral"
    assert updated_record.directional_correct is False

@pytest.mark.asyncio
async def test_bullish_predicted_vs_bullish_actual():
    tracker = OutcomeTracker()
    record = await tracker.store_prediction(
        symbol="AAPL",
        predicted_return_pct=2.0,
        confidence_score=0.8,
        confidence_band="high",
        reference_price=100.0,
        horizon_days=5
    )
    from datetime import datetime, timedelta, timezone
    old_time = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
    tracker._memory_store[f"prediction_track:{record.prediction_id}"].predicted_at = old_time
    
    async def fetch_price(sym): return 105.0
    
    await tracker.evaluate_pending(fetch_price_func=fetch_price)
    updated_record = tracker._memory_store[f"prediction_track:{record.prediction_id}"]
    
    assert updated_record.actual_class == "bullish"
    assert updated_record.predicted_class == "bullish"
    assert updated_record.directional_correct is True
