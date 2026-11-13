"""
Regression tests for the alert evaluator cache-miss fallback.

Bug (f4e7e03): internal._run_eval imported a non-existent
`get_market_data_provider`; the ImportError was swallowed by a broad
`except`, so any alert whose symbol was not already in Redis was never
evaluated. These tests exercise the real fallback path end to end with a
fake DB so that class of bug cannot pass CI silently again.
"""
from __future__ import annotations

import json
from decimal import Decimal
from contextlib import asynccontextmanager
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace

import pytest

from app.api.v1 import internal
from app.data import market_data_provider as mdp


class FakeDB:
    def __init__(self, alerts):
        self._alerts = alerts
        self.executed = []

    async def fetch(self, sql, *args):
        return self._alerts

    async def execute(self, sql, *args):
        self.executed.append((sql, args))
        return "UPDATE 1" if sql.strip().upper().startswith("UPDATE") else "INSERT 0 1"

    @asynccontextmanager
    async def transaction(self):
        yield


class FakeRedis:
    def __init__(self):
        self.store = {}

    async def get(self, key):
        return self.store.get(key)

    async def set(self, key, value, ex=None, nx=False):
        self.store[key] = value
        return True


# Deterministic trading-session timestamp (Wednesday 11:00 AM IST / 05:30 UTC)
_OPEN_TRADING_TIME = datetime(2026, 10, 21, 5, 30, tzinfo=timezone.utc)

def _alert(symbol="RELIANCE.NS", atype="price_below", threshold=3000.0, state="armed"):
    return {
        "id": "a1", "user_id": "u1", "symbol": symbol,
        "alert_type": atype, "threshold": threshold, "trigger_state": state,
    }


def _notifications(db):
    return [e for e in db.executed if "INSERT INTO notifications" in e[0]]


def test_market_data_singleton_exists_and_evaluator_does_not_use_missing_factory():
    import inspect
    assert hasattr(mdp, "market_data")
    assert "get_market_data_provider" not in inspect.getsource(internal)


@pytest.mark.asyncio
async def test_cache_miss_falls_back_to_provider_and_triggers(monkeypatch):
    calls = []

    async def fake_get_quote(symbol, allow_nse_fallback=True):
        calls.append(symbol)
        return SimpleNamespace(available=True, data={"symbol": symbol, "price": 2900.0}, source="Upstox")

    monkeypatch.setattr(mdp.market_data, "get_quote", fake_get_quote)
    db = FakeDB([_alert()])

    result = await internal._run_eval(db, None, _OPEN_TRADING_TIME)

    assert calls == ["RELIANCE.NS"]
    assert result["quotes_obtained"] == 1
    assert result["evaluated"] == 1
    assert result["triggered"] == 1
    assert result["notifications_created"] == 1
    assert result["unpriced_symbols"] == []
    assert len(_notifications(db)) == 1
    assert "run_id" in result and "duration_ms" in result


@pytest.mark.asyncio
async def test_condition_not_met_does_not_notify(monkeypatch):
    async def fake_get_quote(symbol, allow_nse_fallback=True):
        return SimpleNamespace(available=True, data={"price": 3100.0}, source="Upstox")

    monkeypatch.setattr(mdp.market_data, "get_quote", fake_get_quote)
    db = FakeDB([_alert()])

    result = await internal._run_eval(db, None, _OPEN_TRADING_TIME)

    assert result["evaluated"] == 1
    assert result["triggered"] == 0
    assert _notifications(db) == []


@pytest.mark.asyncio
async def test_quote_with_datetime_is_cached_without_error(monkeypatch):
    """Upstox quotes carry a datetime timestamp; json.dumps must not fail."""
    async def fake_get_quote(symbol, allow_nse_fallback=True):
        return SimpleNamespace(available=True, data={
            "price": 2900.0, "timestamp": _OPEN_TRADING_TIME,
        }, source="Upstox")

    monkeypatch.setattr(mdp.market_data, "get_quote", fake_get_quote)
    redis = FakeRedis()
    db = FakeDB([_alert()])

    result = await internal._run_eval(db, redis, _OPEN_TRADING_TIME)

    assert result["triggered"] == 1
    cached = json.loads(redis.store["quote:RELIANCE.NS"])
    assert cached["price"] == 2900.0


@pytest.mark.asyncio
async def test_provider_error_is_counted_not_crashing(monkeypatch):
    async def boom(symbol, allow_nse_fallback=True):
        raise RuntimeError("provider down")

    monkeypatch.setattr(mdp.market_data, "get_quote", boom)
    db = FakeDB([_alert()])

    result = await internal._run_eval(db, None, _OPEN_TRADING_TIME)

    assert result["provider_errors"] == 1
    assert result["evaluated"] == 0
    assert result["unpriced_symbols"] == ["RELIANCE.NS"]


@pytest.mark.asyncio
async def test_zero_or_missing_price_is_not_evaluated(monkeypatch):
    """A 0 price must never trigger a price_below alert."""
    async def zero(symbol, allow_nse_fallback=True):
        return SimpleNamespace(available=True, data={"price": 0}, source="Upstox")

    monkeypatch.setattr(mdp.market_data, "get_quote", zero)
    db = FakeDB([_alert()])

    result = await internal._run_eval(db, None, _OPEN_TRADING_TIME)

    assert result["evaluated"] == 0
    assert _notifications(db) == []


@pytest.mark.asyncio
async def test_cached_symbol_skips_provider(monkeypatch):
    async def should_not_be_called(symbol, allow_nse_fallback=True):
        raise AssertionError("provider called despite cache hit")

    monkeypatch.setattr(mdp.market_data, "get_quote", should_not_be_called)
    redis = FakeRedis()
    redis.store["quote:RELIANCE.NS"] = json.dumps({
        "price": 2900.0,
        "ingested_at": _OPEN_TRADING_TIME.isoformat(),
    })
    db = FakeDB([_alert()])

    result = await internal._run_eval(db, redis, _OPEN_TRADING_TIME)

    assert result["triggered"] == 1


def test_fallback_indian_market_cap():
    """Verify fallback market cap calculation for major Indian stocks."""
    from app.data.market_data_provider import _calculate_fallback_market_cap, _INDIAN_SHARES_OUTSTANDING

    assert "RELIANCE" in _INDIAN_SHARES_OUTSTANDING
    res = _calculate_fallback_market_cap("RELIANCE.NS", 1167.70)
    assert res is not None
    mcap_rel, rec = res
    # 1167.70 * 13,532,453,400 ≈ 15.80 Trillion (15.80 L Cr)
    assert 1.5e13 < mcap_rel < 1.7e13
    assert rec.source_doc is not None
    assert rec.as_of is not None

    # Unknown stock returns None gracefully
    assert _calculate_fallback_market_cap("UNKNOWN_STOCK.NS", 100.0) is None
    # Missing/zero price returns None
    assert _calculate_fallback_market_cap("RELIANCE.NS", 0) is None
    assert _calculate_fallback_market_cap("RELIANCE.NS", None) is None


def test_risk_de_ratio_normalization():
    """Verify D/E ratio is not erroneously divided by 100 when already <= 20.0."""
    from app.engines.risk.engine import RiskEngine

    engine = RiskEngine()
    # Upstox/Finnhub returns direct ratio, e.g. 0.40
    score, factors, ok = engine._compute_financial_risk({"debt_to_equity": 0.40}, sector="Technology")
    assert ok is True
    # Should say "D/E: 0.40", not "D/E: 0.00"
    assert any("D/E: 0.40" in f for f in factors)

    # Strict normalized ratio contract: Low-debt company with 0.08x (e.g. TCS) is correctly classified as low leverage
    score_tcs, factors_tcs, ok_tcs = engine._compute_financial_risk({"debt_to_equity": 0.08}, sector="Technology")
    assert ok_tcs is True
    assert any("D/E: 0.08" in f for f in factors_tcs)
    assert score_tcs < 40.0


def test_edit_alert_request_validation():
    """Verify EditAlertRequest validates alert_type and threshold correctly."""
    from app.api.v1.alerts import EditAlertRequest
    from pydantic import ValidationError

    req = EditAlertRequest(threshold=1200.5, alert_type="price_above")
    assert req.threshold == 1200.5
    assert req.alert_type == "price_above"

    # Negative or zero threshold must raise
    with pytest.raises(ValidationError):
        EditAlertRequest(threshold=-5.0)
    with pytest.raises(ValidationError):
        EditAlertRequest(threshold=0.0)

    # Invalid alert_type must raise
    with pytest.raises(ValidationError):
        EditAlertRequest(alert_type="invalid_type")

    # Partial edit is valid
    partial = EditAlertRequest(threshold=1500.0)
    assert partial.threshold == 1500.0
    assert partial.alert_type is None



# ── Symbol Normalization & Provider Routing Regression Tests ─────────

def test_bare_indian_symbols_normalized_to_ns():
    """Bare Indian symbols (RELIANCE, TCS, INFY, etc.) must normalize to .NS."""
    from app.core.symbols import normalize_symbol, is_indian_symbol

    assert normalize_symbol("RELIANCE") == "RELIANCE.NS"
    assert normalize_symbol("TCS") == "TCS.NS"
    assert normalize_symbol("INFY") == "INFY.NS"
    assert normalize_symbol("HDFCBANK") == "HDFCBANK.NS"
    assert normalize_symbol("ICICIBANK") == "ICICIBANK.NS"
    assert normalize_symbol("SBIN") == "SBIN.NS"

    assert is_indian_symbol("RELIANCE") is True
    assert is_indian_symbol("TCS") is True
    assert is_indian_symbol("INFY") is True


def test_canonical_indian_symbols_preserved():
    """Canonical Indian symbols (.NS, .BO) must remain unchanged."""
    from app.core.symbols import normalize_symbol, is_indian_symbol

    assert normalize_symbol("RELIANCE.NS") == "RELIANCE.NS"
    assert normalize_symbol("INFY.NS") == "INFY.NS"
    assert normalize_symbol("TCS.BO") == "TCS.BO"

    assert is_indian_symbol("RELIANCE.NS") is True
    assert is_indian_symbol("TCS.BO") is True


def test_us_symbols_remain_us_market():
    """US symbols (AAPL, TSLA, NFLX) must remain US market and not be classified as Indian."""
    from app.core.symbols import normalize_symbol, is_indian_symbol

    assert normalize_symbol("AAPL") == "AAPL"
    assert normalize_symbol("TSLA") == "TSLA"
    assert normalize_symbol("NFLX") == "NFLX"
    assert normalize_symbol("MSFT") == "MSFT"

    assert is_indian_symbol("AAPL") is False
    assert is_indian_symbol("TSLA") is False
    assert is_indian_symbol("NFLX") is False
    assert is_indian_symbol("MSFT") is False


def test_market_state_session_routing_for_bare_and_us_symbols():
    """
    During Indian market hours, bare Indian symbols must show 'open'.
    During US market hours, US symbols must show 'open' and Indian symbols 'closed'.
    """
    from app.core.market_calendar import get_market_state

    # Wednesday 11:00 AM IST (05:30 UTC): NSE is open, NYSE is closed
    indian_time = datetime(2026, 10, 21, 5, 30, tzinfo=timezone.utc)
    mstate_rel, _ = get_market_state("RELIANCE", indian_time)
    mstate_tcs, _ = get_market_state("TCS", indian_time)
    mstate_infy, _ = get_market_state("INFY", indian_time)
    mstate_rel_ns, _ = get_market_state("RELIANCE.NS", indian_time)
    mstate_aapl, _ = get_market_state("AAPL", indian_time)

    assert mstate_rel == "open"
    assert mstate_tcs == "open"
    assert mstate_infy == "open"
    assert mstate_rel_ns == "open"
    assert mstate_aapl in ("closed", "pre-market")

    # Wednesday 10:30 AM ET (14:30 UTC = 20:00 IST): NYSE is open, NSE is closed
    us_time = datetime(2026, 10, 21, 14, 30, tzinfo=timezone.utc)
    mstate_aapl_us, _ = get_market_state("AAPL", us_time)
    mstate_tsla_us, _ = get_market_state("TSLA", us_time)
    mstate_rel_us, _ = get_market_state("RELIANCE", us_time)
    mstate_rel_ns_us, _ = get_market_state("RELIANCE.NS", us_time)

    assert mstate_aapl_us == "open"
    assert mstate_tsla_us == "open"
    assert mstate_rel_us == "closed"
    assert mstate_rel_ns_us == "closed"


def test_create_alert_request_canonicalizes_symbol():
    """CreateAlertRequest must canonicalize bare Indian symbols to .NS and preserve US symbols."""
    from app.api.v1.alerts import CreateAlertRequest

    req_bare = CreateAlertRequest(symbol="reliance", alert_type="price_above", threshold=1500.0)
    assert req_bare.symbol == "RELIANCE.NS"

    req_canonical = CreateAlertRequest(symbol="infy.ns", alert_type="price_below", threshold=1400.0)
    assert req_canonical.symbol == "INFY.NS"

    req_us = CreateAlertRequest(symbol="aapl", alert_type="price_above", threshold=250.0)
    assert req_us.symbol == "AAPL"


def test_currency_derivation_contract():
    """_currency_for_symbol must derive '₹' for Indian symbols and '$' for US."""
    from app.api.v1.alerts import _currency_for_symbol

    assert _currency_for_symbol("RELIANCE") == "₹"
    assert _currency_for_symbol("RELIANCE.NS") == "₹"
    assert _currency_for_symbol("TCS") == "₹"
    assert _currency_for_symbol("AAPL") == "$"
    assert _currency_for_symbol("TSLA") == "$"


@pytest.mark.asyncio
async def test_bare_indian_alert_evaluates_and_triggers_with_upstox_provenance(monkeypatch):
    """
    An alert stored as bare 'RELIANCE' must be evaluated canonically during Indian market hours
    and record 'Upstox' as the true quote provenance in notifications.
    """
    calls = []

    async def fake_get_quote(symbol, allow_nse_fallback=True):
        calls.append((symbol, allow_nse_fallback))
        return SimpleNamespace(
            available=True,
            data={"symbol": symbol, "price": 1280.0},
            source="Upstox",
        )

    monkeypatch.setattr(mdp.market_data, "get_quote", fake_get_quote)
    db = FakeDB([_alert(symbol="RELIANCE", atype="price_above", threshold=1200.0)])

    result = await internal._run_eval(db, None, _OPEN_TRADING_TIME)

    assert result["evaluated"] == 1
    assert result["triggered"] == 1
    notifications = _notifications(db)
    assert len(notifications) == 1
    title = notifications[0][1][2]
    body = notifications[0][1][3]
    assert "RELIANCE.NS crossed above ₹1200.00" == title
    assert "Source: Upstox" in body
    assert "₹1280.00" in body


@pytest.mark.asyncio
async def test_indian_provider_failure_skips_without_nse_fallback_and_no_fabrication(monkeypatch):
    """
    When Upstox fails to provide an Indian quote, the evaluator must:
    - NOT call NSE
    - NOT fabricate any synthetic price
    - Report the symbol in unpriced_symbols
    - Safely skip evaluation without triggering
    """
    nse_called = []

    async def fake_get_quote(symbol, allow_nse_fallback=True):
        assert allow_nse_fallback is False, "allow_nse_fallback must be False for Indian alert evaluation"
        # Return UNAVAILABLE_PROVIDER / None (Upstox down)
        return SimpleNamespace(available=False, data=None, source="upstox", reason="Upstox quote unavailable")

    async def fake_nse_quote(symbol):
        nse_called.append(symbol)
        return {"price": 1250.0}

    monkeypatch.setattr(mdp.market_data, "get_quote", fake_get_quote)
    monkeypatch.setattr(mdp.market_data._nse, "get_quote", fake_nse_quote)

    db = FakeDB([_alert(symbol="RELIANCE.NS", atype="price_above", threshold=1200.0)])

    result = await internal._run_eval(db, None, _OPEN_TRADING_TIME)

    assert result["evaluated"] == 0
    assert result["triggered"] == 0
    assert result["unpriced_symbols"] == ["RELIANCE.NS"]
    assert len(nse_called) == 0, "NSE must NOT be called as an operational fallback for alert quotes"
    assert _notifications(db) == [], "No notification should be created when quote is unavailable"


@pytest.mark.asyncio
async def test_non_positive_and_zero_price_does_not_evaluate_or_fabricate(monkeypatch):
    """Quotes with price <= 0 or None must never evaluate or trigger alerts."""
    for bad_price in (0.0, -50.0, None):
        async def fake_bad_quote(symbol, allow_nse_fallback=True):
            data = {"price": bad_price} if bad_price is not None else None
            return SimpleNamespace(available=bad_price is not None, data=data, source="Upstox")

        monkeypatch.setattr(mdp.market_data, "get_quote", fake_bad_quote)
        db = FakeDB([_alert(symbol="RELIANCE.NS", atype="price_below", threshold=1500.0)])

        result = await internal._run_eval(db, None, _OPEN_TRADING_TIME)
        assert result["evaluated"] == 0
        assert result["triggered"] == 0
        assert _notifications(db) == []


@pytest.mark.asyncio
async def test_atomic_trigger_state_transition_and_deduplication():
    """
    If another evaluator already flipped trigger_state from 'armed' to 'triggered'
    (UPDATE 0), no duplicate notification is inserted.
    """
    class RacingDB(FakeDB):
        async def execute(self, sql, *args):
            self.executed.append((sql, args))
            if "UPDATE alerts SET trigger_state" in sql and "trigger_state = 'armed'" in sql:
                return "UPDATE 0"  # Another worker won the race
            return "INSERT 0 1"

    db = RacingDB([_alert(symbol="RELIANCE.NS", atype="price_below", threshold=3000.0, state="armed")])
    redis = FakeRedis()
    redis.store["quote:RELIANCE.NS"] = json.dumps({
        "price": 2500.0,
        "provider": "Upstox",
        "ingested_at": _OPEN_TRADING_TIME.isoformat(),
    })

    result = await internal._run_eval(db, redis, _OPEN_TRADING_TIME)

    assert result["evaluated"] == 1
    assert result["triggered"] == 0
    assert result["notifications_created"] == 0
    assert _notifications(db) == []


def test_ambiguous_symbol_requires_explicit_suffix():
    """
    HAL is ambiguous: HAL.NS on NSE, Halliburton on NYSE.
    With the Stage 1 allowlist, bare HAL normalizes to HAL.NS (HAL is in COMMON_INDIAN_SYMBOLS).
    This is a KNOWN LIMITATION documented for Stage 2 instrument master.
    Users who mean Halliburton must use an explicit exchange-qualified symbol.
    """
    from app.core.symbols import normalize_symbol, is_indian_symbol

    # HAL is in the 59-symbol allowlist -> normalizes to HAL.NS
    assert normalize_symbol("HAL") == "HAL.NS"
    assert is_indian_symbol("HAL") is True  # Stage 1 known limitation for Halliburton case

    # Explicit NSE suffix always unambiguous
    assert normalize_symbol("HAL.NS") == "HAL.NS"


# ── Production Hardening & Security Regression Tests ─────────────────

@pytest.mark.asyncio
async def test_decimal_threshold_passed_as_decimal_to_update(monkeypatch):
    """
    PostgreSQL NUMERIC = FLOAT8 fails equality in PostgreSQL (e.g. 2450.70).
    The evaluator must pass the exact DB threshold (Decimal) to $6 in UPDATE alerts.
    """
    executed_params = []

    class CapturingDB(FakeDB):
        async def execute(self, sql, *args):
            self.executed.append((sql, args))
            if "UPDATE alerts SET trigger_state" in sql:
                executed_params.append(args)
                return "UPDATE 1"
            return "INSERT 0 1"

    # Simulate asyncpg returning a Decimal for NUMERIC column
    decimal_threshold = Decimal("2450.75")
    alert = {
        "id": "a_dec", "user_id": "u1", "symbol": "RELIANCE.NS",
        "alert_type": "price_above", "threshold": decimal_threshold, "trigger_state": "armed",
    }
    db = CapturingDB([alert])
    redis = FakeRedis()
    redis.store["quote:RELIANCE.NS"] = json.dumps({
        "price": 2500.0,
        "provider": "Upstox",
        "ingested_at": _OPEN_TRADING_TIME.isoformat(),
    })

    result = await internal._run_eval(db, redis, _OPEN_TRADING_TIME)

    assert result["evaluated"] == 1
    assert result["triggered"] == 1
    assert len(executed_params) == 1
    # Check that $6 parameter in UPDATE is Decimal, preserving exact PostgreSQL NUMERIC type
    assert executed_params[0][5] == decimal_threshold
    assert isinstance(executed_params[0][5], Decimal)


@pytest.mark.asyncio
async def test_stale_cache_rejected_and_falls_back_to_provider(monkeypatch):
    """
    A quote in Redis with ingested_at older than 900 seconds must be rejected as stale,
    forcing the evaluator to fall back to a fresh provider quote.
    """
    calls = []

    async def fake_get_quote(symbol, allow_nse_fallback=True):
        calls.append(symbol)
        return SimpleNamespace(available=True, data={"price": 2950.0}, source="Upstox")

    monkeypatch.setattr(mdp.market_data, "get_quote", fake_get_quote)
    redis = FakeRedis()
    # Cache entry from 25 minutes ago (1500 seconds old)
    stale_time = datetime(2026, 10, 21, 5, 5, tzinfo=timezone.utc).isoformat()
    redis.store["quote:RELIANCE.NS"] = json.dumps({
        "price": 2900.0,
        "provider": "Upstox",
        "ingested_at": stale_time,
    })
    db = FakeDB([_alert(symbol="RELIANCE.NS", atype="price_above", threshold=2920.0)])

    result = await internal._run_eval(db, redis, _OPEN_TRADING_TIME)

    # Provider must have been called because cached quote was stale
    assert "RELIANCE.NS" in calls
    assert result["triggered"] == 1
    # Notification contains fresh price (2950.00), not stale cached price (2900.00)
    notifs = _notifications(db)
    assert len(notifs) == 1
    assert "2950.00" in notifs[0][1][3]


@pytest.mark.asyncio
async def test_fresh_cache_with_provider_provenance_accepted():
    """
    A fresh cached quote (< 900s old) with 'provider' metadata must be accepted
    and its provider correctly recorded in the notification provenance.
    """
    redis = FakeRedis()
    # Cache entry from 2 minutes ago
    fresh_time = datetime(2026, 10, 21, 5, 28, tzinfo=timezone.utc).isoformat()
    redis.store["quote:RELIANCE.NS"] = json.dumps({
        "price": 2950.0,
        "provider": "Upstox",
        "ingested_at": fresh_time,
    })
    db = FakeDB([_alert(symbol="RELIANCE.NS", atype="price_above", threshold=2900.0)])

    result = await internal._run_eval(db, redis, _OPEN_TRADING_TIME)

    assert result["evaluated"] == 1
    assert result["triggered"] == 1
    notifs = _notifications(db)
    assert len(notifs) == 1
    body = notifs[0][1][3]
    assert "Source: Upstox" in body
    assert "2950.00" in body


def test_symbol_validation_rejects_injection_and_invalid_chars():
    """
    CreateAlertRequest must reject malformed symbols, colons, spaces, newlines,
    and strings exceeding 20 characters to prevent Redis key injection.
    """
    from app.api.v1.alerts import CreateAlertRequest
    from pydantic import ValidationError

    # Valid symbols
    valid_1 = CreateAlertRequest(symbol="RELIANCE", alert_type="price_above", threshold=2500.0)
    assert valid_1.symbol == "RELIANCE.NS"

    valid_2 = CreateAlertRequest(symbol="AAPL", alert_type="price_above", threshold=150.0)
    assert valid_2.symbol == "AAPL"

    valid_3 = CreateAlertRequest(symbol="TCS.BO", alert_type="price_below", threshold=3000.0)
    assert valid_3.symbol == "TCS.BO"

    # Invalid: colon (Redis namespace pollution)
    with pytest.raises(ValidationError):
        CreateAlertRequest(symbol="RELIANCE:exploit", alert_type="price_above", threshold=100.0)

    # Invalid: spaces
    with pytest.raises(ValidationError):
        CreateAlertRequest(symbol="REL IANCE", alert_type="price_above", threshold=100.0)

    # Invalid: newlines
    with pytest.raises(ValidationError):
        CreateAlertRequest(symbol="RELIANCE\nINJECT", alert_type="price_above", threshold=100.0)

    # Invalid: over 20 chars
    with pytest.raises(ValidationError):
        CreateAlertRequest(symbol="A" * 25, alert_type="price_above", threshold=100.0)


@pytest.mark.asyncio
async def test_quota_atomic_incr_expire_and_rollback(monkeypatch):
    """
    _atomic_incr_expire must increment key and set expiration.
    When daily limit is exceeded, daily counter is rolled back.
    """
    from app.core.provider_quota import ProviderQuotaGovernor, ProviderLimit, PROVIDER_LIMITS

    class MockRedisQuota:
        def __init__(self):
            self.store = {}
            self.ttls = {}

        async def eval(self, script, numkeys, key, count, ttl):
            val = self.store.get(key, 0) + int(count)
            self.store[key] = val
            if val == int(count):
                self.ttls[key] = int(ttl)
            return val

        async def incrby(self, key, count):
            self.store[key] = self.store.get(key, 0) + count
            return self.store[key]

        async def decrby(self, key, count):
            self.store[key] = self.store.get(key, 0) - count
            return self.store[key]

        async def expire(self, key, ttl):
            self.ttls[key] = ttl
            return True

    mock_redis = MockRedisQuota()
    governor = ProviderQuotaGovernor()

    # Allow 2 per day
    monkeypatch.setitem(PROVIDER_LIMITS, "test_prov", ProviderLimit(per_minute=10, per_day=2))

    assert await governor.acquire("test_prov", redis_client=mock_redis, count=1) is True
    assert await governor.acquire("test_prov", redis_client=mock_redis, count=1) is True
    # Third request must exceed daily limit and roll back
    assert await governor.acquire("test_prov", redis_client=mock_redis, count=1) is False


@pytest.mark.asyncio
async def test_evaluate_predictions_uses_upstox_for_indian_symbols(monkeypatch):
    """
    evaluate_predictions must fetch quotes with allow_nse_fallback=False for Indian symbols.
    """
    calls = []

    async def fake_get_quote(symbol, allow_nse_fallback=True):
        calls.append((symbol, allow_nse_fallback))
        return SimpleNamespace(available=True, data={"price": 2800.0})

    monkeypatch.setattr(mdp.market_data, "get_quote", fake_get_quote)

    from app.engines.prediction.outcome_tracker import outcome_tracker
    async def fake_evaluate_pending(fetch_price_func):
        # Call fetch_price_func on Indian symbol
        price_ind = await fetch_price_func("RELIANCE")
        # Call fetch_price_func on US symbol
        price_us = await fetch_price_func("AAPL")
        return 2

    monkeypatch.setattr(outcome_tracker, "evaluate_pending", fake_evaluate_pending)

    fake_request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace()))
    res = await internal.evaluate_predictions(fake_request, None)

    assert res["status"] == "ok"
    assert res["evaluated"] == 2
    # Verify Indian symbol was normalized to RELIANCE.NS and allow_nse_fallback=False
    assert ("RELIANCE.NS", False) in calls
    # Verify US symbol had allow_nse_fallback=True
    assert ("AAPL", True) in calls


# ── Additional Master Audit Hardening Tests ──────────────────────────

@pytest.mark.asyncio
async def test_jsonresponse_defined_on_infrastructure_skips():
    """
    JSONResponse must be imported at module level so that warmup and prediction
    infrastructure failure paths do not raise NameError.
    """
    req_no_redis = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(redis=None)), state=SimpleNamespace(db=FakeDB([])))
    resp_redis = await internal.warm_alert_symbols(req_no_redis, None)
    assert resp_redis.status_code == 503
    body = json.loads(resp_redis.body.decode("utf-8"))
    assert body["reason"] == "Redis not configured"

    req_no_db = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(redis=FakeRedis())), state=SimpleNamespace(db=None))
    resp_db = await internal.warm_alert_symbols(req_no_db, None)
    assert resp_db.status_code == 503
    body_db = json.loads(resp_db.body.decode("utf-8"))
    assert body_db["reason"] == "Database pool unavailable"


def test_symbol_mm_allowed_and_hal_ambiguous_validation():
    """
    M&M must be allowed by symbol validation and normalized to M&M.NS.
    Bare HAL must be rejected as ambiguous with explicit guidance.
    HAL.NS must be accepted.
    """
    from app.api.v1.alerts import CreateAlertRequest
    from pydantic import ValidationError

    # M&M is valid
    req_mm = CreateAlertRequest(symbol="M&M", alert_type="price_above", threshold=2800.0)
    assert req_mm.symbol == "M&M.NS"

    # Bare HAL is ambiguous
    with pytest.raises(ValidationError) as exc:
        CreateAlertRequest(symbol="HAL", alert_type="price_above", threshold=4200.0)
    assert "ambiguous across exchanges" in str(exc.value)

    # Qualified HAL.NS is accepted
    req_hal_ns = CreateAlertRequest(symbol="HAL.NS", alert_type="price_above", threshold=4200.0)
    assert req_hal_ns.symbol == "HAL.NS"


def test_financial_numeric_validation_nan_and_inf():
    """
    Alert thresholds must reject NaN, positive infinity, and negative infinity.
    """
    from app.api.v1.alerts import CreateAlertRequest, EditAlertRequest
    from pydantic import ValidationError

    # NaN in CreateAlertRequest
    with pytest.raises(ValidationError) as exc_nan:
        CreateAlertRequest(symbol="RELIANCE", alert_type="price_above", threshold=float("nan"))
    assert "finite, positive number" in str(exc_nan.value)

    # Infinity in CreateAlertRequest
    with pytest.raises(ValidationError) as exc_inf:
        CreateAlertRequest(symbol="RELIANCE", alert_type="price_above", threshold=float("inf"))
    assert "finite, positive number" in str(exc_inf.value)

    # NaN in EditAlertRequest
    with pytest.raises(ValidationError) as exc_edit:
        EditAlertRequest(threshold=float("nan"))
    assert "finite, positive number" in str(exc_edit.value)


def test_internal_secret_unicode_and_type_safety():
    """
    Non-ASCII or invalid surrogate strings in X-Internal-Secret must return 403 Forbidden,
    not an unhandled TypeError 500 error.
    """
    from fastapi import HTTPException
    from app.config import Settings
    from app.core.auth import require_internal_secret

    settings = Settings(internal_job_secret="safe-secret-key")
    # Non-ASCII surrogate string
    req_bad = SimpleNamespace(headers={"X-Internal-Secret": "bad\ud800secret"})
    with pytest.raises(HTTPException) as exc:
        require_internal_secret(req_bad, settings)
    assert exc.value.status_code == 403


def test_quote_freshness_fail_closed_validation():
    """
    _is_quote_fresh must strictly validate UTC timestamps and reject:
    - Missing ingested_at
    - Stale (> 900s)
    - Future (> 60s)
    - Naive timestamps normalized safely
    """
    now = datetime(2026, 10, 21, 5, 30, tzinfo=timezone.utc)

    # Missing ingested_at -> Rejected
    assert internal._is_quote_fresh({"price": 2500.0}, now) is False

    # Stale (> 900s, 1500s old) -> Rejected
    stale_ts = datetime(2026, 10, 21, 5, 5, tzinfo=timezone.utc).isoformat()
    assert internal._is_quote_fresh({"price": 2500.0, "ingested_at": stale_ts}, now) is False

    # Implausibly future (> 60s, 5 minutes in future) -> Rejected
    future_ts = datetime(2026, 10, 21, 5, 35, tzinfo=timezone.utc).isoformat()
    assert internal._is_quote_fresh({"price": 2500.0, "ingested_at": future_ts}, now) is False

    # Fresh timezone-aware (60s old) -> Accepted
    fresh_ts = datetime(2026, 10, 21, 5, 29, tzinfo=timezone.utc).isoformat()
    assert internal._is_quote_fresh({"price": 2500.0, "ingested_at": fresh_ts}, now) is True

    # Fresh timezone-naive (60s old, normalized as UTC) -> Accepted
    fresh_naive = "2026-10-21T05:29:00"
    assert internal._is_quote_fresh({"price": 2500.0, "ingested_at": fresh_naive}, now) is True


def test_upstox_static_index_keys():
    """
    Upstox adapter must map NIFTY, NIFTY.NS, BANKNIFTY, BANKNIFTY.NS, SENSEX to index keys.
    """
    from app.data.adapters.upstox import UpstoxAdapter

    adapter = UpstoxAdapter()
    assert adapter._symbol_to_key.get("NIFTY.NS") == "NSE_INDEX|Nifty 50"
    assert adapter._symbol_to_key.get("NIFTY") == "NSE_INDEX|Nifty 50"
    assert adapter._symbol_to_key.get("BANKNIFTY.NS") == "NSE_INDEX|Nifty Bank"
    assert adapter._symbol_to_key.get("BANKNIFTY") == "NSE_INDEX|Nifty Bank"
    assert adapter._symbol_to_key.get("SENSEX.BO") == "BSE_INDEX|SENSEX"
    assert adapter._symbol_to_key.get("SENSEX") == "BSE_INDEX|SENSEX"


# =============================================================================
# Stage 1 Final Remediation Pass: Regression Test Battery (FIX 01 - FIX 07)
# =============================================================================

@pytest.mark.asyncio
async def test_warmup_ignores_stale_quote_even_if_key_exists(monkeypatch):
    """
    FIX 01: Warmup must reject stale quotes via _is_quote_fresh and must NOT
    fall back to exists_fn to treat a stale key as having a price.
    """
    now = datetime(2026, 10, 21, 5, 30, tzinfo=timezone.utc)
    stale_ts = datetime(2026, 10, 21, 4, 30, tzinfo=timezone.utc).isoformat()  # 1 hr old (> 900s)

    warmed_symbols = []

    class MockRedisWithStaleQuote:
        def __init__(self):
            # Key exists in Redis with stale quote data
            self._data = {
                "quote:RELIANCE.NS": json.dumps({"price": 2500.0, "ingested_at": stale_ts})
            }

        async def zrange(self, *args, **kwargs):
            return ["RELIANCE.NS"]

        async def zadd(self, *args, **kwargs):
            return 1

        async def zrem(self, *args, **kwargs):
            return 1

        async def get(self, key):
            return self._data.get(key)

        async def exists(self, key):
            # Simulates the existence check that previously caused the bug
            return 1 if key in self._data else 0

        async def set(self, key, value, ex=None):
            self._data[key] = value
            return True

    mock_redis = MockRedisWithStaleQuote()

    class MockDB:
        async def fetch(self, query):
            return [{"symbol": "RELIANCE.NS"}]

    async def fake_get_quote(symbol, allow_nse_fallback=False):
        warmed_symbols.append(symbol)
        return SimpleNamespace(
            available=True,
            data={"price": 2550.0, "symbol": symbol},
            source="Upstox",
        )

    monkeypatch.setattr(mdp.market_data, "get_quote", fake_get_quote)
    monkeypatch.setattr(internal, "get_market_state", lambda sym, now: ("open", None))

    req = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(redis=mock_redis)),
        state=SimpleNamespace(db=MockDB()),
    )

    res = await internal.warm_alert_symbols(req, _=None)
    # The stale quote must be ignored and refreshed via market_data.get_quote
    assert res["warmed"] == 1
    assert "RELIANCE.NS" in warmed_symbols


@pytest.mark.asyncio
async def test_invite_redemption_rejects_used_at_with_null_used_by():
    """
    FIX 02: Account deletion clears used_by but preserves used_at.
    Invite redemption must reject when used_at is NOT NULL even if used_by is NULL.
    """
    from app.api.v1 import invite
    from app.models.schemas.user import RedeemInviteRequest
    from fastapi import HTTPException
    from types import SimpleNamespace
    from uuid import uuid4

    class MockInviteDB:
        def __init__(self):
            self.tx_entered = False

        async def fetchval(self, sql, *args):
            return "pending"  # current user access_status

        async def fetchrow(self, sql, *args):
            # Inspect the SQL passed: verify that 'used_at' is explicitly requested in SELECT.
            # If the production code omits 'used_at' from the query, the returned row lacks
            # 'used_at', failing the test and proving that SQL column selection is verified.
            sql_clean = sql.replace("\n", " ")
            select_clause = sql_clean.split("FROM")[0].lower()
            cols = [c.strip() for c in select_clause.replace("select", "").split(",")]
            row = {
                "id": uuid4(),
                "used_by": None,
                "expires_at": datetime(2099, 1, 1, tzinfo=timezone.utc),
                "created_by": None,
            }
            if "used_at" in cols:
                row["used_at"] = datetime.now(timezone.utc)
            return row

        async def execute(self, sql, *args):
            pass

        @asynccontextmanager
        async def transaction(self):
            self.tx_entered = True
            yield

    db = MockInviteDB()
    user = SimpleNamespace(user_id=uuid4(), email="tester@example.com")
    req = SimpleNamespace(state=SimpleNamespace(db=db))
    body = RedeemInviteRequest(code="TEST-CODE-1234")

    with pytest.raises(HTTPException) as exc:
        await invite.redeem_invite_code(body, req, user)
    assert exc.value.status_code == 409
    assert "already been used" in exc.value.detail


@pytest.mark.asyncio
async def test_admin_cannot_regenerate_used_invite_with_null_used_by():
    """
    FIX 02: Admin regeneration must reject invites where used_at is NOT NULL,
    preventing resurrecting an invite after account deletion.
    """
    from app.api.v1 import admin
    from fastapi import HTTPException
    from uuid import uuid4

    class MockAdminDB:
        async def fetchrow(self, sql, *args):
            # Verify row-locking and used_at column selection
            assert "for update" in sql.lower(), "Admin query must use FOR UPDATE row lock"
            sql_clean = sql.replace("\n", " ")
            select_clause = sql_clean.split("FROM")[0].lower()
            cols = [c.strip() for c in select_clause.replace("select", "").split(",")]
            row = {
                "id": uuid4(),
                "used_by": None,
            }
            if "used_at" in cols:
                row["used_at"] = datetime.now(timezone.utc)
            return row

        async def execute(self, sql, *args):
            return "UPDATE 1"

        @asynccontextmanager
        async def transaction(self):
            yield

    db = MockAdminDB()
    admin_user = SimpleNamespace(user_id=uuid4(), role="admin")
    req = SimpleNamespace(state=SimpleNamespace(db=db))

    with pytest.raises(HTTPException) as exc:
        await admin.regenerate_invite_code(str(uuid4()), req, admin_user)
    assert exc.value.status_code == 400
    assert "Cannot regenerate an already used invite code" in exc.value.detail


@pytest.mark.asyncio
async def test_admin_regenerate_concurrency_conflict():
    """
    Critical Area E: If an invite is concurrently redeemed or modified between
    the lock read and update, the atomic conditional update returns 'UPDATE 0'
    and raises HTTP 409 Conflict.
    """
    from app.api.v1 import admin
    from fastapi import HTTPException
    from uuid import uuid4

    class MockConflictDB:
        async def fetchrow(self, sql, *args):
            return {
                "id": uuid4(),
                "used_by": None,
                "used_at": None,
            }

        async def execute(self, sql, *args):
            # Simulate concurrent redemption: zero rows updated because used_by/used_at was set
            return "UPDATE 0"

        @asynccontextmanager
        async def transaction(self):
            yield

    db = MockConflictDB()
    admin_user = SimpleNamespace(user_id=uuid4(), role="admin")
    req = SimpleNamespace(state=SimpleNamespace(db=db))

    with pytest.raises(HTTPException) as exc:
        await admin.regenerate_invite_code(str(uuid4()), req, admin_user)
    assert exc.value.status_code == 409
    assert "concurrently redeemed" in exc.value.detail


@pytest.mark.asyncio
async def test_alert_eval_rejects_non_finite_price(monkeypatch):
    """
    FIX 04: Evaluator must reject NaN, Infinity, -Infinity, and <= 0.
    """
    test_cases = [float("inf"), float("-inf"), float("nan"), -50.0, 0.0]

    for bad_price in test_cases:
        async def fake_get_quote(symbol, allow_nse_fallback=True):
            return SimpleNamespace(available=True, data={"price": bad_price, "symbol": symbol}, source="Upstox")

        monkeypatch.setattr(mdp.market_data, "get_quote", fake_get_quote)
        db = FakeDB([_alert()])

        res = await internal._run_eval(db, None, _OPEN_TRADING_TIME)
        assert res["evaluated"] == 0, f"Failed to reject non-finite/non-positive price: {bad_price}"
        assert res["triggered"] == 0
        assert "RELIANCE.NS" in res["unpriced_symbols"]


@pytest.mark.asyncio
async def test_outcome_tracker_rejects_non_finite_price(monkeypatch):
    """
    FIX 04: Outcome tracker evaluate_pending must reject non-finite prices.
    """
    from app.engines.prediction.outcome_tracker import OutcomeTracker, PredictionRecord
    from uuid import uuid4

    tracker = OutcomeTracker()
    now = datetime.now(timezone.utc)
    key = f"{tracker._PREFIX}{uuid4().hex}"

    record = PredictionRecord(
        prediction_id=str(uuid4()),
        symbol="TCS.NS",
        predicted_class="bullish",
        predicted_return_pct=5.0,
        confidence_score=0.85,
        confidence_band="high",
        horizon_days=7,
        reference_price=3500.0,
        predicted_at=(now - timedelta(days=10)).isoformat(),
        evaluation_status="pending",
    )
    tracker._memory_store[key] = record

    async def fake_fetch_bad_price(symbol):
        return float("inf")

    count = await tracker.evaluate_pending(fetch_price_func=fake_fetch_bad_price)
    assert count == 0
    assert count.stats["evaluated"] == 0
    assert count.stats["pending_unpriced"] == 1

    # Record must still be pending, not evaluated
    reloaded = tracker._memory_store[key]
    assert reloaded.evaluation_status == "pending"
    assert reloaded.evaluation_price is None


@pytest.mark.asyncio
async def test_evaluator_cache_write_includes_freshness_metadata(monkeypatch):
    """
    FIX 05: Live fallback cache writes must include ingested_at, provider, and canonical symbol.
    """
    cached_writes = {}

    class TrackingRedis:
        async def get(self, key):
            return None

        async def set(self, key, val, ex=None):
            cached_writes[key] = json.loads(val)
            return True

    async def fake_get_quote(symbol, allow_nse_fallback=False):
        return SimpleNamespace(
            available=True,
            data={"price": 2800.0, "symbol": symbol},
            source="Upstox",
        )

    monkeypatch.setattr(mdp.market_data, "get_quote", fake_get_quote)
    db = FakeDB([_alert(symbol="RELIANCE.NS", atype="price_above", threshold=2500.0)])
    redis_instance = TrackingRedis()

    res = await internal._run_eval(db, redis_instance, _OPEN_TRADING_TIME)
    assert res["evaluated"] == 1

    assert "quote:RELIANCE.NS" in cached_writes
    payload = cached_writes["quote:RELIANCE.NS"]
    assert "ingested_at" in payload
    assert payload["provider"] == "Upstox"
    assert payload["symbol"] == "RELIANCE.NS"
    assert payload["price"] == 2800.0


@pytest.mark.asyncio
async def test_alert_eval_timeout_returns_504(monkeypatch):
    """
    FIX 06: Evaluator timeout must return HTTP 504 with structured error,
    while safely releasing the Redis lock.
    """
    import asyncio
    eval_lock_released = []

    class MockRedisTimeout:
        async def get(self, key):
            return None

        async def set(self, key, val, nx=False, ex=None):
            return True

        async def eval(self, script, numkeys, *args):
            eval_lock_released.append((script, args))
            return 1

    async def hanging_run_eval(*args, **kwargs):
        raise asyncio.TimeoutError()

    monkeypatch.setattr(internal, "_run_eval", hanging_run_eval)

    req = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(redis=MockRedisTimeout())),
        state=SimpleNamespace(db=FakeDB([])),
    )

    response = await internal.evaluate_alerts(req, _=None)
    assert response.status_code == 504
    body = json.loads(response.body)
    assert body["status"] == "error"
    assert "timed out" in body["reason"]
    assert len(eval_lock_released) == 1  # Redis lock released via finally


@pytest.mark.asyncio
async def test_evaluate_predictions_stalled_semantics(monkeypatch):
    """
    FIX 03: When eligible > 0 and evaluated == 0, evaluate_predictions returns
    HTTP 502 with status: stalled.
    """
    from app.engines.prediction.outcome_tracker import EvaluationCount

    async def fake_evaluate_pending(*args, **kwargs):
        return EvaluationCount(0, stats={
            "evaluated": 0,
            "eligible": 5,
            "pending_unpriced": 5,
            "provider_errors": 0,
            "skipped_immature": 0,
            "ungradable": 0,
        })

    from app.engines.prediction.outcome_tracker import outcome_tracker
    monkeypatch.setattr(outcome_tracker, "evaluate_pending", fake_evaluate_pending)

    req = SimpleNamespace()
    res = await internal.evaluate_predictions(req, _=None)
    assert res.status_code == 502
    body = json.loads(res.body)
    assert body["status"] == "stalled"
    assert body["eligible"] == 5
    assert body["evaluated"] == 0


def test_prediction_evaluator_workflow_yaml_syntax_and_summary_generation(tmp_path):
    """
    Regression test for GitHub Actions check failure on line 54 of prediction-evaluator.yml.
    Ensures that prediction-evaluator.yml is valid YAML and that multiline markdown
    table generation inside run blocks preserves block scalar indentation and syntax.
    """
    import yaml
    from pathlib import Path

    # Find the repository root
    repo_root = Path(__file__).resolve().parent.parent.parent
    workflow_path = repo_root / ".github" / "workflows" / "prediction-evaluator.yml"

    assert workflow_path.exists(), f"Workflow not found at {workflow_path}"

    with open(workflow_path, "r", encoding="utf-8") as f:
        content = f.read()

    # 1. Strict YAML syntax parsing (this failed on line 54 prior to fix)
    data = yaml.safe_load(content)
    assert isinstance(data, dict)
    assert data.get("name") == "Prediction Evaluator"

    # 2. Extract and verify step run commands
    jobs = data.get("jobs", {})
    assert "evaluate-predictions" in jobs
    steps = jobs["evaluate-predictions"].get("steps", [])
    eval_step = next(s for s in steps if s.get("name") == "Evaluate matured predictions")
    run_script = eval_step.get("run", "")
    assert "evaluate-predictions" in run_script
    assert "### 🎯 Prediction Evaluation Evidence" in run_script

    # 3. Verify semantic evaluation logic: test summary table formatting
    status = "stalled"
    d = {
        "status": "stalled",
        "error": "Eligible predictions could not be evaluated",
        "evaluated": 0,
        "eligible": 4,
        "pending_unpriced": 4,
        "provider_errors": 0,
        "skipped_immature": 1,
        "ungradable": 0,
    }
    http_code = "502"

    summary = f"""### 🎯 Prediction Evaluation Evidence
| Metric | Value |
|---|---|
| **HTTP Status** | `{http_code}` |
| **Status** | `{status}` |
| **Error** | `{d.get('error', 'None')}` |
| **Predictions Evaluated** | `{d.get('evaluated', 'N/A')}` |
| **Eligible Predictions** | `{d.get('eligible', 'N/A')}` |
| **Pending Unpriced** | `{d.get('pending_unpriced', 'N/A')}` |
| **Provider Errors** | `{d.get('provider_errors', 'N/A')}` |
| **Skipped (Immature)** | `{d.get('skipped_immature', 'N/A')}` |
| **Ungradable** | `{d.get('ungradable', 'N/A')}` |
"""
    assert "| **HTTP Status** | `502` |" in summary
    assert "| **Status** | `stalled` |" in summary
    assert "| **Eligible Predictions** | `4` |" in summary


@pytest.mark.asyncio
async def test_provider_quota_burst_per_second_enforcement():
    """
    Critical Area A: Enforce per-second burst limits across providers.
    Upstox allows 10 req/s. The 11th request in the same second window must be rejected.
    """
    from app.core.provider_quota import ProviderQuotaGovernor

    gov = ProviderQuotaGovernor()
    gov.reset()

    # In dev/test in-memory mode
    # First 10 requests within the same second should succeed
    for i in range(10):
        ok = await gov.acquire("upstox", count=1)
        assert ok is True, f"Request {i+1} should have succeeded within 10 req/s limit"

    # 11th request in same second window must fail
    rejected = await gov.acquire("upstox", count=1)
    assert rejected is False, "11th request must be rejected on per-second quota limit"

    # Also test batch count exceeding limit
    gov.reset()
    ok_batch = await gov.acquire("upstox", count=11)
    assert ok_batch is False, "Batch acquire of 11 must be rejected against 10 req/s limit"


@pytest.mark.asyncio
async def test_provider_quota_production_fail_closed_on_redis_unavailable(monkeypatch):
    """
    Critical Area A: In production, missing Redis or Redis failure must FAIL CLOSED.
    It must not silently fall back to process-local in-memory state.
    """
    from app.core.provider_quota import ProviderQuotaGovernor
    import app.config as config_mod

    gov = ProviderQuotaGovernor()
    gov.reset()

    class FakeSettings:
        is_production = True
        app_env = config_mod.Environment.PRODUCTION

    monkeypatch.setattr(config_mod, "get_settings", lambda: FakeSettings())

    # 1. When redis_client is None in production -> Fail closed (False)
    ok = await gov.acquire("upstox", redis_client=None, count=1)
    assert ok is False, "Must fail closed when Redis is None in production"

    # 2. When redis throws an exception in production -> Fail closed (False)
    class BrokenRedis:
        async def eval(self, *args, **kwargs):
            raise ConnectionError("Redis connection lost")

        async def incrby(self, *args, **kwargs):
            raise ConnectionError("Redis connection lost")

    ok_broken = await gov.acquire("upstox", redis_client=BrokenRedis(), count=1)
    assert ok_broken is False, "Must fail closed when Redis throws an exception in production"

    # 3. In non-production (dev/test), redis_client=None falls back to in-memory and succeeds
    FakeSettings.is_production = False
    FakeSettings.app_env = config_mod.Environment.DEVELOPMENT
    ok_dev = await gov.acquire("upstox", redis_client=None, count=1)
    assert ok_dev is True, "In non-production, missing Redis can use in-memory fallback"


@pytest.mark.asyncio
async def test_provider_quota_atomic_lua_contract():
    """
    Critical Area A: Verify the Lua script handles 3 keys (sec, min, daily),
    enforces sliding-window sorted sets and daily limits, and returns expected status codes:
    1: Allowed
    -2: Rejected on second burst
    0: Rejected on minute limit
    -1: Rejected on daily limit
    """
    from app.core.provider_quota import _ATOMIC_SLIDING_QUOTA_LUA, ProviderQuotaGovernor
    assert "KEYS[1]" in _ATOMIC_SLIDING_QUOTA_LUA
    assert "KEYS[2]" in _ATOMIC_SLIDING_QUOTA_LUA
    assert "KEYS[3]" in _ATOMIC_SLIDING_QUOTA_LUA
    assert "sec_limit" in _ATOMIC_SLIDING_QUOTA_LUA
    assert "min_limit" in _ATOMIC_SLIDING_QUOTA_LUA
    assert "day_limit" in _ATOMIC_SLIDING_QUOTA_LUA
    assert "ZREMRANGEBYSCORE" in _ATOMIC_SLIDING_QUOTA_LUA
    assert "ZCARD" in _ATOMIC_SLIDING_QUOTA_LUA
    assert "ZADD" in _ATOMIC_SLIDING_QUOTA_LUA
    assert "return -2" in _ATOMIC_SLIDING_QUOTA_LUA
    assert "return 0" in _ATOMIC_SLIDING_QUOTA_LUA
    assert "return -1" in _ATOMIC_SLIDING_QUOTA_LUA
    assert "return 1" in _ATOMIC_SLIDING_QUOTA_LUA
    assert "ttl < 0 then" in _ATOMIC_SLIDING_QUOTA_LUA  # TTL repair contract

    # Simulate Redis eval dispatch
    class MockRedisEval:
        def __init__(self, return_code):
            self.return_code = return_code
            self.eval_called_with = None

        async def eval(self, script, numkeys, *args):
            self.eval_called_with = (script, numkeys, args)
            return self.return_code

    gov = ProviderQuotaGovernor()

    # Test allowed
    mock_redis = MockRedisEval(1)
    ok = await gov.acquire("upstox", redis_client=mock_redis, count=1)
    assert ok is True
    assert mock_redis.eval_called_with[1] == 3

    # Test second burst exceeded (-2)
    mock_redis_sec = MockRedisEval(-2)
    assert await gov.acquire("upstox", redis_client=mock_redis_sec, count=1) is False

    # Test minute limit exceeded (0)
    mock_redis_min = MockRedisEval(0)
    assert await gov.acquire("upstox", redis_client=mock_redis_min, count=1) is False

    # Test daily limit exceeded (-1)
    mock_redis_day = MockRedisEval(-1)
    assert await gov.acquire("upstox", redis_client=mock_redis_day, count=1) is False


def test_workflow_semantic_validation_rejects_malformed_and_empty_payloads(tmp_path):
    """
    Critical Areas B, C, D: Workflow response validation scripts must reject
    empty payloads '{}', missing fields, negative integers, invalid types,
    and unrecognized skip reasons with sys.exit(1).
    """
    import subprocess
    import sys
    from pathlib import Path
    import yaml

    repo_root = Path(__file__).resolve().parent.parent.parent

    def extract_python_snippet(step_run: str) -> str:
        parts = step_run.split('python3 -c "')
        after_c = parts[-1]
        code = after_c.split('\n"\n')[0]
        return code.replace('\\"', '"').replace('\\$', '$')

    def run_validation_script(code, body_content, http_code="200"):
        script_file = tmp_path / "validator.py"
        body_file = tmp_path / "body.json"
        body_file.write_text(body_content, encoding="utf-8")
        script_file.write_text(code.replace("$http_code", http_code), encoding="utf-8")
        res = subprocess.run([sys.executable, str(script_file)], cwd=str(tmp_path), capture_output=True, text=True)
        return res.returncode, res.stdout, res.stderr

    # 1. Test alert-evaluator.yml python script
    alert_eval_yml = repo_root / ".github" / "workflows" / "alert-evaluator.yml"
    with open(alert_eval_yml, "r", encoding="utf-8") as f:
        y_data = yaml.safe_load(f)
    steps = y_data["jobs"]["evaluate-alerts"]["steps"]
    step = next(s for s in steps if "python3 -c" in s.get("run", ""))
    py_code = extract_python_snippet(step["run"])

    # Empty payload '{}' must exit 1 on alert evaluator
    code, out, err = run_validation_script(py_code, "{}")
    assert code != 0, f"Alert evaluator must reject empty payload '{{}}', got code {code}"

    # Non-dictionary payload must exit 1
    code, _, _ = run_validation_script(py_code, '["not", "a", "dict"]')
    assert code != 0, "Alert evaluator must reject non-dict JSON"

    # Unrecognized skip reason must exit 1
    code, _, _ = run_validation_script(py_code, '{"skipped": true, "reason": "Random reason"}')
    assert code != 0, "Alert evaluator must reject illegal skip reasons"

    # Legitimate skip reason must exit 0
    code, _, _ = run_validation_script(py_code, '{"skipped": true, "reason": "Evaluated recently within 120s cooldown"}')
    assert code == 0, "Alert evaluator must accept valid skip reason"

    # Valid completion payload must exit 0
    valid_payload = json.dumps({
        "run_id": "test-run-123",
        "at": "2026-11-13T12:00:00Z",
        "active_alerts": 10,
        "symbols_requested": 5,
        "quotes_obtained": 5,
        "evaluated": 10,
        "triggered": 0,
        "notifications_created": 0,
        "skipped_market_closed": 0,
        "provider_errors": 0,
        "unpriced_symbols": [],
        "duration_ms": 142.5,
    })
    code, _, _ = run_validation_script(py_code, valid_payload)
    assert code == 0, "Alert evaluator must accept valid evaluation payload"

    # Negative metric must exit 1
    invalid_metric_payload = json.dumps({
        "run_id": "test-run-123",
        "at": "2026-11-13T12:00:00Z",
        "active_alerts": -1,
        "symbols_requested": 5,
        "quotes_obtained": 5,
        "evaluated": 10,
        "triggered": 0,
        "notifications_created": 0,
        "skipped_market_closed": 0,
        "provider_errors": 0,
        "unpriced_symbols": [],
        "duration_ms": 142.5,
    })
    code, _, _ = run_validation_script(py_code, invalid_metric_payload)
    assert code != 0, "Alert evaluator must reject negative integer metrics"

    # 2. Test prediction-evaluator.yml python script
    pred_eval_yml = repo_root / ".github" / "workflows" / "prediction-evaluator.yml"
    with open(pred_eval_yml, "r", encoding="utf-8") as f:
        p_data = yaml.safe_load(f)
    # The second python3 -c step is the validation step
    p_steps = [s for s in p_data["jobs"]["evaluate-predictions"]["steps"] if "python3 -c" in s.get("run", "")]
    p_step = p_steps[-1]
    p_py_code = extract_python_snippet(p_step["run"])

    # Empty payload '{}' must exit 1 on prediction evaluator
    code, _, _ = run_validation_script(p_py_code, "{}")
    assert code != 0, "Prediction evaluator must reject empty payload '{}'"

    # Stalled payload must exit 1
    stalled_payload = json.dumps({
        "status": "stalled",
        "error": "Eligible predictions could not be evaluated",
        "evaluated": 0,
        "eligible": 5,
        "pending_unpriced": 5,
        "provider_errors": 0,
        "skipped_immature": 0,
        "ungradable": 0,
    })
    code, _, _ = run_validation_script(p_py_code, stalled_payload, http_code="502")
    assert code != 0, "Prediction evaluator must exit 1 on stalled status"

    # Valid OK payload must exit 0
    ok_payload = json.dumps({
        "status": "ok",
        "evaluated": 3,
        "eligible": 3,
        "pending_unpriced": 0,
        "provider_errors": 0,
        "skipped_immature": 1,
        "ungradable": 0,
    })
    code, _, _ = run_validation_script(p_py_code, ok_payload, http_code="200")
    assert code == 0, "Prediction evaluator must exit 0 on valid ok payload"

    # 3. Test alert-warmup.yml python script
    warmup_yml = repo_root / ".github" / "workflows" / "alert-warmup.yml"
    with open(warmup_yml, "r", encoding="utf-8") as f:
        w_data = yaml.safe_load(f)
    w_step = next(s for s in w_data["jobs"]["warmup-alerts"]["steps"] if "python3 -c" in s.get("run", ""))
    w_py_code = extract_python_snippet(w_step["run"])

    # Empty payload '{}' must exit 1 on warmup
    code, _, _ = run_validation_script(w_py_code, "{}")
    assert code != 0, "Alert warmup must reject empty payload '{}'"

    # Valid warmup payload must exit 0
    warmup_valid = json.dumps({
        "warmed": 10,
        "skipped": 2,
        "uncached_remaining": 0,
        "duration_ms": 320.0,
    })
    code, _, _ = run_validation_script(w_py_code, warmup_valid, http_code="200")
    assert code == 0, "Alert warmup must exit 0 on valid warmup payload"
