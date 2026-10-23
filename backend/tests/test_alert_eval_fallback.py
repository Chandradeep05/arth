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
from contextlib import asynccontextmanager
from datetime import datetime, timezone
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

    async def fake_get_quote(symbol):
        calls.append(symbol)
        return SimpleNamespace(available=True, data={"symbol": symbol, "price": 2900.0})

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
    async def fake_get_quote(symbol):
        return SimpleNamespace(available=True, data={"price": 3100.0})

    monkeypatch.setattr(mdp.market_data, "get_quote", fake_get_quote)
    db = FakeDB([_alert()])

    result = await internal._run_eval(db, None, _OPEN_TRADING_TIME)

    assert result["evaluated"] == 1
    assert result["triggered"] == 0
    assert _notifications(db) == []


@pytest.mark.asyncio
async def test_quote_with_datetime_is_cached_without_error(monkeypatch):
    """Upstox quotes carry a datetime timestamp; json.dumps must not fail."""
    async def fake_get_quote(symbol):
        return SimpleNamespace(available=True, data={
            "price": 2900.0, "timestamp": datetime.now(timezone.utc),
        })

    monkeypatch.setattr(mdp.market_data, "get_quote", fake_get_quote)
    redis = FakeRedis()
    db = FakeDB([_alert()])

    result = await internal._run_eval(db, redis, _OPEN_TRADING_TIME)

    assert result["triggered"] == 1
    cached = json.loads(redis.store["quote:RELIANCE.NS"])
    assert cached["price"] == 2900.0


@pytest.mark.asyncio
async def test_provider_error_is_counted_not_crashing(monkeypatch):
    async def boom(symbol):
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
    async def zero(symbol):
        return SimpleNamespace(available=True, data={"price": 0})

    monkeypatch.setattr(mdp.market_data, "get_quote", zero)
    db = FakeDB([_alert()])

    result = await internal._run_eval(db, None, _OPEN_TRADING_TIME)

    assert result["evaluated"] == 0
    assert _notifications(db) == []


@pytest.mark.asyncio
async def test_cached_symbol_skips_provider(monkeypatch):
    async def should_not_be_called(symbol):
        raise AssertionError("provider called despite cache hit")

    monkeypatch.setattr(mdp.market_data, "get_quote", should_not_be_called)
    redis = FakeRedis()
    redis.store["quote:RELIANCE.NS"] = json.dumps({"price": 2900.0})
    db = FakeDB([_alert()])

    result = await internal._run_eval(db, redis, _OPEN_TRADING_TIME)

    assert result["triggered"] == 1


def test_fallback_indian_market_cap():
    """Verify fallback market cap calculation for major Indian stocks."""
    from app.data.market_data_provider import _calculate_fallback_market_cap, _INDIAN_SHARES_OUTSTANDING

    assert "RELIANCE" in _INDIAN_SHARES_OUTSTANDING
    mcap_rel = _calculate_fallback_market_cap("RELIANCE.NS", 1167.70)
    assert mcap_rel is not None
    # 1167.70 * 13,532,453,400 ≈ 15.80 Trillion (15.80 L Cr)
    assert 1.5e13 < mcap_rel < 1.7e13

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

