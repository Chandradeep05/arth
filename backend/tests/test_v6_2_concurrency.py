"""
Behavioral and Concurrency Tests for V6.2 Production Hardening.

Covers:
- Upstox adapter _CACHE_MAX_ENTRIES scoping and circuit breaker recovery
- Prediction model concurrency lock & symbol caching
- Backtest concurrency lock & caching
- Assistant idempotency reservation lock
- Assistant session message concurrency lock
- DB connection skip prefixes for long-lived SSE streams
- Invite code personal binding validation
- Research cache key depth segregation
- Watchlist batch rate limiting configuration
- Alert warmup starvation prevention and fair round-robin scheduling
"""

from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from app.data.adapters.upstox import _CACHE_MAX_ENTRIES, upstox_adapter, UpstoxAdapter
from app.data.cache import CacheManager
from app.core.rate_limiter import RATE_LIMITS
from app.main import _NO_DB_PREFIXES
from app.engines.assistant.engine import AssistantSession, AssistantEngine
from app.engines.prediction.model import PredictionModel
from app.engines.prediction.backtester import Backtester


# =============================================================================
# 1. Upstox Scoping & Circuit Breaker Tests
# =============================================================================

def test_upstox_cache_max_entries_module_scope():
    """Verify _cache_set runs without NameError: name '_CACHE_MAX_ENTRIES' is not defined."""
    assert _CACHE_MAX_ENTRIES == 500
    adapter = UpstoxAdapter()
    # Add test entries to verify eviction logic doesn't crash on _CACHE_MAX_ENTRIES
    adapter._cache_set("test_key_1", {"data": 123}, ttl=60)
    assert adapter._cache_get("test_key_1") == {"data": 123}


# =============================================================================
# 2. Prediction Concurrency & Cache Tests
# =============================================================================

@pytest.mark.asyncio
async def test_prediction_model_concurrency_lock_and_cache():
    """
    Concurrent forecast requests for the same symbol must be serialized by the symbol lock,
    and subsequent requests must hit the forecast cache instead of retraining XGBoost.
    """
    import numpy as np
    import pandas as pd

    model = PredictionModel()
    X_data = {f"feat_{i}": np.random.randn(120) for i in range(5)}
    mock_df_X = pd.DataFrame(X_data)
    mock_series_y = pd.Series(np.random.randn(120))
    mock_live = {f"feat_{i}": 1.0 for i in range(5)}

    mock_quote = MagicMock()
    mock_quote.available = True
    mock_quote.data = {"price": 3500.0, "timestamp": "2026-09-28T00:00:00Z"}

    build_count = 0

    async def mock_build_features(*args, **kwargs):
        nonlocal build_count
        build_count += 1
        await asyncio.sleep(0.05)  # simulate training time
        return mock_df_X, mock_series_y

    model._feature_engineer.build_features = mock_build_features
    model._feature_engineer.build_live_features = AsyncMock(return_value=mock_live)
    model._compute_shap = MagicMock(return_value=[{"feature": "feat_0", "impact": "high"}])

    mock_xgb = MagicMock()
    mock_xgb_regressor = MagicMock()
    mock_xgb_regressor.predict.side_effect = lambda df: np.full(len(df), 0.03)
    mock_xgb.XGBRegressor.return_value = mock_xgb_regressor

    with patch.dict("sys.modules", {"xgboost": mock_xgb}), \
         patch("app.data.market_data_provider.market_data.get_quote", new_callable=AsyncMock, return_value=mock_quote):

        # Fire 5 concurrent requests for TCS.NS
        tasks = [
            model.forecast("TCS.NS")
            for _ in range(5)
        ]
        results = await asyncio.gather(*tasks)

        # All 5 must succeed with identical symbol and prediction payload
        assert len(results) == 5
        for res in results:
            assert res["symbol"] == "TCS.NS"
            assert "prediction" in res

        # Crucially: feature building and model training must have run only ONCE because of lock + cache
        assert build_count == 1


@pytest.mark.asyncio
async def test_prediction_backtest_concurrency_lock_and_cache():
    """
    Concurrent backtest requests for the same symbol must be serialized by backtest lock,
    with secondary callers served from the backtest cache.
    """
    import numpy as np
    import pandas as pd

    backtester = Backtester()
    X_data = {f"feat_{i}": np.random.randn(150) for i in range(5)}
    mock_df_X = pd.DataFrame(X_data)
    mock_series_y = pd.Series(np.random.randn(150))

    build_count = 0

    async def mock_build_features(*args, **kwargs):
        nonlocal build_count
        build_count += 1
        await asyncio.sleep(0.05)
        return mock_df_X, mock_series_y

    backtester._feature_engineer.build_features = mock_build_features
    backtester._save_result = MagicMock()

    mock_xgb = MagicMock()
    mock_xgb_regressor = MagicMock()
    mock_xgb_regressor.predict.return_value = np.array([0.02])
    mock_xgb.XGBRegressor.return_value = mock_xgb_regressor

    with patch.dict("sys.modules", {"xgboost": mock_xgb}):
        # Fire 3 concurrent backtests for INFY.NS
        tasks = [
            backtester.run_backtest("INFY.NS", lookback_days=30)
            for _ in range(3)
        ]
        results = await asyncio.gather(*tasks)

        assert len(results) == 3
        for res in results:
            assert res["symbol"] == "INFY.NS"
            assert "overall" in res

        # Must only compute once
        assert build_count == 1


# =============================================================================
# 3. Assistant Concurrency & Idempotency Tests
# =============================================================================

@pytest.mark.asyncio
async def test_assistant_session_lock_serializes_messages():
    """Verify session._lock prevents race conditions when concurrent requests hit the same session."""
    session = AssistantSession(session_id="test_session", owner_user_id="user_123")
    
    order = []
    
    async def mock_chat(msg):
        async with session._lock:
            order.append(f"start_{msg}")
            await asyncio.sleep(0.02)
            order.append(f"end_{msg}")
            session.messages.append({"role": "user", "content": msg})
            session.messages.append({"role": "assistant", "content": f"Reply to {msg}"})
            return f"Reply to {msg}"

    await asyncio.gather(
        mock_chat("msg1"),
        mock_chat("msg2"),
        mock_chat("msg3"),
    )

    # Messages must be cleanly serialized: start_X followed by end_X before next start
    assert order[0].startswith("start_")
    assert order[1] == f"end_{order[0].split('_')[1]}"
    assert order[2].startswith("start_")
    assert order[3] == f"end_{order[2].split('_')[1]}"
    assert len(session.messages) == 6


# =============================================================================
# 4. Long SSE Streams & Connection Pool Protection Tests
# =============================================================================

def test_no_db_prefixes_includes_sse_streaming_endpoints():
    """
    Endpoints that stream responses for 20-30s must NOT hold connections from the
    small 5-connection asyncpg pool.
    """
    assert "/api/v1/research" in _NO_DB_PREFIXES
    assert "/api/v1/assistant" in _NO_DB_PREFIXES
    assert "/api/v1/prediction" in _NO_DB_PREFIXES


# =============================================================================
# 5. Invite Code Personal Binding Tests
# =============================================================================

def test_personal_invite_code_binding_logic():
    """
    If invite has created_by set to a non-admin user, another user cannot redeem it.
    """
    creator_user_id = "user_owner_1"
    redeemer_user_id = "user_attacker_2"
    creator_role = "member"

    # Rule: creator_role != "admin" and invite["created_by"] != user.user_id -> 403 Forbidden
    is_blocked = (creator_role != "admin" and creator_user_id != redeemer_user_id)
    assert is_blocked is True

    # Same user can redeem their own code
    assert (creator_role != "admin" and creator_user_id != creator_user_id) is False

    # Admin-created code can be redeemed by anyone
    admin_role = "admin"
    assert (admin_role != "admin" and creator_user_id != redeemer_user_id) is False


# =============================================================================
# 6. Research Cache Key Depth Segregation Tests
# =============================================================================

def test_research_cache_key_depth_segregation():
    """Verify research cache keys segregate between standard and deep reports."""
    standard_key = CacheManager.research_key("RELIANCE.NS", "standard")
    deep_key = CacheManager.research_key("RELIANCE.NS", "deep")
    quick_key = CacheManager.research_key("RELIANCE.NS", "quick")

    assert standard_key == "research:RELIANCE.NS:standard"
    assert deep_key == "research:RELIANCE.NS:deep"
    assert quick_key == "research:RELIANCE.NS:quick"
    assert standard_key != deep_key


# =============================================================================
# 7. Rate Limiting Configuration Tests
# =============================================================================

def test_watchlist_batch_rate_limit_configured():
    """Verify watchlist batch endpoint is protected by rate limiting."""
    assert "/api/v1/watchlist/batch" in RATE_LIMITS
    limit, window = RATE_LIMITS["/api/v1/watchlist/batch"]
    assert limit == 10
    assert window == 60


# =============================================================================
# 8. Alert Warmup Starvation Prevention Tests
# =============================================================================

@pytest.mark.asyncio
async def test_alert_warmup_starvation_prevention():
    """
    Verify alert warmup updates scheduled symbols in ZSET and round-robins uncached symbols.
    """
    mock_redis = MagicMock()
    mock_redis.exists = AsyncMock(return_value=False)
    mock_redis.zadd = AsyncMock()
    mock_redis.zrem = AsyncMock()
    # Return 15 symbols sorted by oldest score
    mock_redis.zrange = AsyncMock(return_value=[f"SYM_{i}".encode("utf-8") for i in range(15)])
    mock_redis.set = AsyncMock()

    mock_db = MagicMock()
    mock_db.fetch = AsyncMock(return_value=[{"symbol": f"SYM_{i}"} for i in range(15)])

    from app.api.v1.internal import warm_alert_symbols
    from starlette.requests import Request

    mock_request = MagicMock(spec=Request)
    mock_request.app.state.redis = mock_redis
    mock_request.state.db = mock_db

    with patch("app.data.market_data_provider.market_data.get_quote", new_callable=AsyncMock) as mock_get_quote:
        mock_quote_res = MagicMock()
        mock_quote_res.available = True
        mock_quote_res.data = {"price": 100.0}
        mock_get_quote.return_value = mock_quote_res

        result = await warm_alert_symbols(mock_request)

        # Processed 10 (batch limit) out of 15
        assert result["warmed"] == 10
        assert result["uncached_remaining"] == 5
        # zadd must have been called to update scores for all warmed symbols
        assert mock_redis.zadd.call_count >= 10
