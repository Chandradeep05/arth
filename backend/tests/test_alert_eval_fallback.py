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

    result = await internal._run_eval(db, None, datetime.now(timezone.utc))

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

    result = await internal._run_eval(db, None, datetime.now(timezone.utc))

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

    result = await internal._run_eval(db, redis, datetime.now(timezone.utc))

    assert result["triggered"] == 1
    cached = json.loads(redis.store["quote:RELIANCE.NS"])
    assert cached["price"] == 2900.0


@pytest.mark.asyncio
async def test_provider_error_is_counted_not_crashing(monkeypatch):
    async def boom(symbol):
        raise RuntimeError("provider down")

    monkeypatch.setattr(mdp.market_data, "get_quote", boom)
    db = FakeDB([_alert()])

    result = await internal._run_eval(db, None, datetime.now(timezone.utc))

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

    result = await internal._run_eval(db, None, datetime.now(timezone.utc))

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

    result = await internal._run_eval(db, redis, datetime.now(timezone.utc))

    assert result["triggered"] == 1
