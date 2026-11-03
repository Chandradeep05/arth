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
    redis.store["quote:RELIANCE.NS"] = json.dumps({"price": 2500.0, "provider": "Upstox"})

    result = await internal._run_eval(db, redis, _OPEN_TRADING_TIME)

    assert result["evaluated"] == 1
    assert result["triggered"] == 0
    assert result["notifications_created"] == 0
    assert _notifications(db) == []
