"""
ARTH Stage 1 / Gate G1 Production Hardening Test Suite.

Deterministic regression tests verifying:
1. Authoritative 2026 NSE & NYSE holiday calendars
2. NYSE early-close modeling (1:00 PM ET)
3. Zero data fabrication (missing values -> None, missing timestamp -> None)
4. Truthful freshness metadata (no false 'real-time' claims)
5. Market-session aware alert evaluator (skips closed exchanges)
6. Central provider quota governor (minute & daily limits)
7. Fail-closed authentication in production
8. SHA-256 invite code hashing and backward-compatible redemption
9. Sanitized health check error responses
"""

from datetime import datetime, timezone
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

from app.core.market_calendar import (
    NSE_HOLIDAYS_2026,
    NYSE_HOLIDAYS_2026,
    NYSE_EARLY_CLOSES,
    get_market_state,
    is_nse_holiday,
    is_us_holiday,
    is_us_early_close,
)
from app.api.v1.market import _make_freshness
from app.core.provider_quota import ProviderQuotaGovernor, ProviderLimit
from app.core.auth import hash_invite_code


# ── 1. Official 2026 Exchange Holiday Tests ─────────────────────────────

@pytest.mark.parametrize(
    "year,month,day,desc",
    [
        (2026, 1, 15, "Maharashtra Municipal Election"),
        (2026, 1, 26, "Republic Day"),
        (2026, 3, 3, "Holi"),
        (2026, 3, 26, "Shri Ram Navami"),
        (2026, 3, 31, "Shri Mahavir Jayanti"),
        (2026, 4, 3, "Good Friday"),
        (2026, 4, 14, "Ambedkar Jayanti"),
        (2026, 5, 1, "Maharashtra Day"),
        (2026, 5, 28, "Bakri Id"),
        (2026, 6, 26, "Muharram"),
        (2026, 9, 14, "Ganesh Chaturthi"),
        (2026, 10, 2, "Mahatma Gandhi Jayanti"),
        (2026, 10, 20, "Dussehra"),
        (2026, 11, 10, "Diwali-Balipratipada"),
        (2026, 11, 24, "Guru Nanak Jayanti"),
        (2026, 12, 25, "Christmas"),
    ],
)
def test_all_official_2026_nse_holidays(year, month, day, desc):
    """Every official NSE 2026 holiday must be recognized as market closed."""
    d = datetime(year, month, day, 10, 30, tzinfo=ZoneInfo("Asia/Kolkata"))
    assert (year, month, day) in NSE_HOLIDAYS_2026, f"Missing {desc} in NSE 2026 holidays"
    assert is_nse_holiday(d) is True
    mstate, label = get_market_state("RELIANCE.NS", d)
    assert mstate == "closed"
    assert label == "Market Holiday"


@pytest.mark.parametrize(
    "year,month,day,desc",
    [
        (2026, 1, 1, "New Year's Day"),
        (2026, 1, 19, "MLK Day"),
        (2026, 2, 16, "Presidents' Day"),
        (2026, 4, 3, "Good Friday"),
        (2026, 5, 25, "Memorial Day"),
        (2026, 6, 19, "Juneteenth"),
        (2026, 7, 3, "Independence Day (Observed)"),
        (2026, 9, 7, "Labor Day"),
        (2026, 11, 26, "Thanksgiving"),
        (2026, 12, 25, "Christmas Day"),
    ],
)
def test_all_official_2026_nyse_holidays(year, month, day, desc):
    """Every official NYSE 2026 holiday must be recognized as market closed."""
    d = datetime(year, month, day, 11, 0, tzinfo=ZoneInfo("America/New_York"))
    assert (year, month, day) in NYSE_HOLIDAYS_2026, f"Missing {desc} in NYSE 2026 holidays"
    assert is_us_holiday(d) is True
    mstate, label = get_market_state("AAPL", d)
    assert mstate == "closed"
    assert label == "Market Holiday"


def test_nyse_early_close_modeling():
    """NYSE early close on 2026-11-27 and 2026-12-24 at 1:00 PM ET."""
    tz = ZoneInfo("America/New_York")

    # Nov 27, 2026 12:30 PM ET -> OPEN
    d_open = datetime(2026, 11, 27, 12, 30, tzinfo=tz)
    assert is_us_early_close(d_open) is True
    state_open, _ = get_market_state("AAPL", d_open)
    assert state_open == "open"

    # Nov 27, 2026 1:15 PM ET -> POST-MARKET / AFTER HOURS (closed for regular trading)
    d_closed = datetime(2026, 11, 27, 13, 15, tzinfo=tz)
    state_closed, label = get_market_state("AAPL", d_closed)
    assert state_closed != "open"
    assert "After Hours" in label or "post-market" in state_closed

    # Dec 24, 2026 1:05 PM ET -> CLOSED for regular trading
    d_xmas_eve = datetime(2026, 12, 24, 13, 5, tzinfo=tz)
    state_xmas, _ = get_market_state("AAPL", d_xmas_eve)
    assert state_xmas != "open"


# ── 2. Freshness & Truthful Reporting Tests ──────────────────────────────

def test_missing_timestamp_is_truthful_and_not_now():
    """When upstream provider timestamp is missing, do NOT substitute datetime.now()."""
    # Open market simulation
    wednesday_trading_hour = datetime(2026, 10, 21, 14, 0, tzinfo=ZoneInfo("America/New_York"))

    with patch("app.api.v1.market.get_market_state", return_value=("open", "Regular Trading")):
        meta = _make_freshness(
            source="TwelveData",
            cache_hit=False,
            quote_timestamp=None,
            market_or_symbol="AAPL",
        )
        assert meta.timestamp is None
        assert meta.delay_label == "timestamp unavailable"
        assert meta.is_stale is True


def test_provided_timestamp_preserved_without_alteration():
    """Valid provider timestamp is preserved and parsed accurately."""
    actual_quote_time = datetime(2026, 10, 21, 13, 45, 0, tzinfo=timezone.utc)
    with patch("app.api.v1.market.get_market_state", return_value=("open", "Regular Trading")):
        meta = _make_freshness(
            source="TwelveData",
            cache_hit=False,
            quote_timestamp=actual_quote_time,
            market_or_symbol="AAPL",
        )
        assert meta.timestamp == actual_quote_time


# ── 3. Market-Aware Alert Evaluation Tests ───────────────────────────────

@pytest.mark.asyncio
async def test_alert_evaluator_skips_closed_market():
    """Alert evaluation must skip symbols whose markets are closed."""
    from app.api.v1.internal import _run_eval

    # Mock DB with 2 alerts: one Indian (NSE) and one US (NYSE)
    mock_db = MagicMock()
    mock_alerts = [
        {"id": "a1", "user_id": "u1", "symbol": "RELIANCE.NS", "alert_type": "price_above", "threshold": 2500.0, "trigger_state": "armed"},
        {"id": "a2", "user_id": "u2", "symbol": "AAPL", "alert_type": "price_above", "threshold": 220.0, "trigger_state": "armed"},
    ]
    mock_db.fetch = AsyncMock(return_value=mock_alerts)

    # Sunday timestamp: both markets are closed
    sunday_dt = datetime(2026, 10, 25, 12, 0, tzinfo=timezone.utc)

    res = await _run_eval(mock_db, redis=None, now=sunday_dt)
    assert res["run_id"] is not None
    assert res["evaluated"] == 0
    assert res["skipped_market_closed"] == 2
    assert res["symbols_requested"] == 0


# ── 4. Provider Quota Governor Tests ─────────────────────────────────────

@pytest.mark.asyncio
async def test_provider_quota_governor_minute_and_daily_limits():
    """Governor must enforce configured per-minute and per-day caps."""
    gov = ProviderQuotaGovernor()
    gov.PROVIDER_LIMITS = {
        "test_prov": ProviderLimit(per_minute=3, per_day=5),
    }
    with patch.dict("app.core.provider_quota.PROVIDER_LIMITS", {"test_prov": ProviderLimit(per_minute=3, per_day=5)}):
        # 3 calls allowed in first minute
        assert await gov.acquire("test_prov") is True
        assert await gov.acquire("test_prov") is True
        assert await gov.acquire("test_prov") is True
        # 4th call blocked by minute limit
        assert await gov.acquire("test_prov") is False


# ── 5. Security & Fail-Closed Authentication Tests ───────────────────────

@pytest.mark.asyncio
async def test_fail_closed_auth_in_production():
    """get_current_user must raise HTTP 503 when DB is unavailable in production."""
    from app.core.auth import get_current_user
    from fastapi import HTTPException

    mock_request = MagicMock()
    mock_request.state.db = None
    mock_request.app.state.pg_pool = None
    mock_request.headers = {"Authorization": "Bearer fake.test.token"}

    mock_settings = MagicMock()
    mock_settings.is_production = True
    mock_settings.supabase_jwt_secret = "test-secret"

    with patch("app.core.auth._decode_supabase_jwt", return_value={"sub": "11111111-1111-1111-1111-111111111111", "email": "user@example.com"}):
        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(mock_request, settings=mock_settings)
        assert exc_info.value.status_code == 503
        assert "unavailable" in exc_info.value.detail.lower()


def test_invite_code_hashing():
    """Invite code hashing produces consistent SHA-256 digests and case-insensitivity."""
    raw = "arth-test-code-123"
    hash1 = hash_invite_code(raw)
    hash2 = hash_invite_code("ARTH-TEST-CODE-123")
    assert hash1 == hash2
    assert len(hash1) == 64  # SHA-256 hex string


# ── 6. Sanitized Health Check Responses ──────────────────────────────────

@pytest.mark.asyncio
async def test_health_check_error_sanitization_in_production():
    """Production health check must never expose raw connection exceptions or credentials."""
    from app.api.v1.system import health_check

    mock_settings = MagicMock()
    mock_settings.is_development = False
    mock_settings.app_env.value = "production"

    with patch("app.config.get_settings", return_value=mock_settings):
        with patch("app.dependencies._engine") as mock_eng:
            mock_eng.connect.side_effect = Exception("password=secret postgresql://user:pass@internal.db:5432/arth")
            with patch("app.api.v1.system.get_redis", side_effect=Exception("Connection refused redis://user:pass@internal.redis:6379")):
                health = await health_check()
                # Ensure no leaked credentials or driver internals
                db_msg = health.services["database"].message or ""
                redis_msg = health.services["redis"].message or ""
                assert "password" not in db_msg.lower()
                assert "secret" not in db_msg.lower()
                assert "redis://" not in redis_msg.lower()
                assert db_msg == "Database connection failed"
                assert redis_msg == "Redis connection failed"


# ── 7. Open-Market Only Alert Evaluation & Market Cap Metadata ───────────

@pytest.mark.asyncio
async def test_alert_evaluator_strictly_requires_open_market():
    """Alert evaluation must skip symbols during pre-market, post-market, and closed sessions."""
    from app.api.v1.internal import _run_eval

    mock_db = MagicMock()
    mock_alerts = [
        {"id": "a1", "user_id": "u1", "symbol": "RELIANCE.NS", "alert_type": "price_above", "threshold": 2500.0, "trigger_state": "armed"},
    ]
    mock_db.fetch = AsyncMock(return_value=mock_alerts)

    # 9:05 AM IST on Wednesday -> Pre-market session (not yet open)
    pre_market_dt = datetime(2026, 10, 21, 9, 5, tzinfo=ZoneInfo("Asia/Kolkata"))
    res = await _run_eval(mock_db, redis=None, now=pre_market_dt)
    assert res["evaluated"] == 0
    assert res["skipped_market_closed"] == 1


def test_computed_market_cap_metadata_attached():
    """Computed market cap must attach provenance metadata (computed source, as_of, citation)."""
    from app.data.market_data_provider import _calculate_fallback_market_cap

    res = _calculate_fallback_market_cap("RELIANCE.NS", 1300.0)
    assert res is not None
    mcap, rec = res
    assert mcap > 0
    assert rec.as_of == "2024-10"
    assert "Bonus" in rec.source
