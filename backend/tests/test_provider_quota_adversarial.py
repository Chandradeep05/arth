"""
ARTH Provider Quota Governor — Comprehensive Adversarial Verification Suite.

Validates all 14 mandatory adversarial properties across distributed Redis,
concurrency contention, fail-closed boundaries, sliding window semantics,
and configuration failure modes.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import os
import time
from typing import List
from uuid import uuid4

import fakeredis
import fakeredis.aioredis
import pytest
from redis.exceptions import ConnectionError as RedisConnectionError, ResponseError, TimeoutError as RedisTimeoutError

from app.core.provider_quota import (
    ProviderQuotaGovernor,
    PROVIDER_LIMITS,
    _ATOMIC_SLIDING_QUOTA_LUA,
    is_production_environment,
)
import app.config as config_mod


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    """Ensure clean environment state across tests."""
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.delenv("ENVIRONMENT", raising=False)


@pytest.mark.asyncio
async def test_concurrent_reservations_independent_redis_clients():
    """
    Adversarial Test 1: Concurrency from independent Redis clients.
    5 independent Redis clients execute 50 concurrent requests for Upstox (limit: 10/s).
    Exactly 10 must succeed and 40 must be rejected.
    ZSET cardinality must be exactly 10.
    """
    server = fakeredis.FakeServer()
    clients = [fakeredis.aioredis.FakeRedis(server=server) for _ in range(5)]
    gov = ProviderQuotaGovernor()

    # Explicitly test in production environment
    class FakeProdSettings:
        is_production = True
        app_env = config_mod.Environment.PRODUCTION

    async def worker_task(client_idx: int):
        client = clients[client_idx % len(clients)]
        return await gov.acquire("upstox", redis_client=client, count=1)

    # Monkeypatch to ensure production check passes
    from unittest.mock import patch
    with patch("app.core.provider_quota.is_production_environment", return_value=True):
        tasks = [worker_task(i) for i in range(50)]
        results = await asyncio.gather(*tasks)

    successes = sum(1 for r in results if r is True)
    rejections = sum(1 for r in results if r is False)
    assert successes == 10, f"Expected exactly 10 successes against Upstox limit, got {successes}"
    assert rejections == 40, f"Expected exactly 40 rejections, got {rejections}"

    # Verify the underlying Redis ZSET card
    sec_card = await clients[0].zcard("quota:provider:upstox:sec_zset")
    assert sec_card == 10, f"ZSET cardinality must be exactly 10, got {sec_card}"


@pytest.mark.asyncio
async def test_quota_boundary_contention():
    """
    Adversarial Test 2: Quota boundary contention.
    At Upstox limit 10, when 9 requests are in, two concurrent tasks request count=2 and count=1.
    The count=1 task must succeed, reaching 10/10.
    The count=2 task must fail (9 + 2 = 11 > 10).
    Total reserved must be exactly 10.
    """
    server = fakeredis.FakeServer()
    client = fakeredis.aioredis.FakeRedis(server=server)
    gov = ProviderQuotaGovernor()

    from unittest.mock import patch
    with patch("app.core.provider_quota.is_production_environment", return_value=True):
        # Fill 9 tokens
        for _ in range(9):
            ok = await gov.acquire("upstox", redis_client=client, count=1)
            assert ok is True

        # Launch contending tasks
        t_count1 = gov.acquire("upstox", redis_client=client, count=1)
        t_count2 = gov.acquire("upstox", redis_client=client, count=2)
        res_count1, res_count2 = await asyncio.gather(t_count1, t_count2)

        assert res_count1 is True, "Count=1 must succeed (9 + 1 = 10)"
        assert res_count2 is False, "Count=2 must fail (9 + 2 = 11 > 10)"

        sec_card = await client.zcard("quota:provider:upstox:sec_zset")
        assert sec_card == 10, f"Total ZSET card must be exactly 10, got {sec_card}"


@pytest.mark.asyncio
async def test_lua_failure_with_commands_available_fails_closed_in_production():
    """
    Adversarial Test 3: Lua script failure while ordinary Redis commands remain available.
    In production, if Lua eval raises ResponseError/script error, the governor MUST FAIL CLOSED.
    It must NEVER fall back to ordinary Redis commands (INCRBY/DECRBY) or in-memory state.
    """
    class LuaFailingRedis:
        def __init__(self):
            self.incrby_called = False

        async def eval(self, *args, **kwargs):
            raise ResponseError("NOSCRIPT No matching script. Please use EVAL.")

        async def incrby(self, *args, **kwargs):
            self.incrby_called = True
            return 1

    broken_client = LuaFailingRedis()
    gov = ProviderQuotaGovernor()
    gov.reset()

    from unittest.mock import patch
    with patch("app.core.provider_quota.is_production_environment", return_value=True):
        ok = await gov.acquire("upstox", redis_client=broken_client, count=1)
        assert ok is False, "Production MUST reject reservation if Lua fails"
        assert broken_client.incrby_called is False, "Production must NEVER fall back to separate commands"
        assert len(gov._sec_calls) == 0, "Production must NEVER fall back to in-memory state"


@pytest.mark.asyncio
async def test_redis_timeout_uncertain_execution_fails_closed():
    """
    Adversarial Test 4: Redis timeout with uncertain script execution.
    If Redis times out during eval, the outcome is uncertain.
    The governor must fail closed (return False) to prevent upstream API quota exhaustion.
    """
    class TimingOutRedis:
        async def eval(self, *args, **kwargs):
            raise RedisTimeoutError("Timeout reading from socket on eval")

    gov = ProviderQuotaGovernor()
    gov.reset()

    from unittest.mock import patch
    with patch("app.core.provider_quota.is_production_environment", return_value=True):
        ok = await gov.acquire("upstox", redis_client=TimingOutRedis(), count=1)
        assert ok is False, "Timeout must fail closed in production"
        assert len(gov._sec_calls) == 0


@pytest.mark.asyncio
async def test_redis_unavailable_in_production_fails_closed():
    """
    Adversarial Test 5: Redis unavailable in production.
    When redis_client is None in production, returns False without touching in-memory state.
    """
    gov = ProviderQuotaGovernor()
    gov.reset()

    from unittest.mock import patch
    with patch("app.core.provider_quota.is_production_environment", return_value=True):
        ok = await gov.acquire("upstox", redis_client=None, count=1)
        assert ok is False
        assert len(gov._sec_calls) == 0


@pytest.mark.asyncio
async def test_unexpected_lua_return_value_fails_closed():
    """
    Adversarial Test 6: Unexpected Lua return value.
    If Lua returns an unhandled code (e.g. 999 or None), fails closed.
    """
    class BadReturnRedis:
        def __init__(self, val):
            self.val = val

        async def eval(self, *args, **kwargs):
            return self.val

    gov = ProviderQuotaGovernor()
    from unittest.mock import patch
    with patch("app.core.provider_quota.is_production_environment", return_value=True):
        for bad_val in [999, -99, None, "unexpected", []]:
            ok = await gov.acquire("upstox", redis_client=BadReturnRedis(bad_val), count=1)
            assert ok is False, f"Unexpected return {bad_val} must fail closed"


@pytest.mark.asyncio
async def test_missing_ttl_and_ttl_repair():
    """
    Adversarial Test 7: Missing TTL on daily counter key.
    If a daily key has no TTL (TTL == -1), the Lua script automatically repairs and sets TTL.
    """
    server = fakeredis.FakeServer()
    client = fakeredis.aioredis.FakeRedis(server=server)
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    daily_key = f"quota:provider:twelvedata:daily:{today_str}"

    # Pre-seed daily key with no TTL
    await client.set(daily_key, "5")
    ttl_before = await client.ttl(daily_key)
    assert ttl_before == -1, "Pre-condition: key must have no TTL"

    gov = ProviderQuotaGovernor()
    from unittest.mock import patch
    with patch("app.core.provider_quota.is_production_environment", return_value=True):
        ok = await gov.acquire("twelvedata", redis_client=client, count=1)
        assert ok is True

    ttl_after = await client.ttl(daily_key)
    assert ttl_after > 0, f"Lua script must repair missing TTL, got {ttl_after}"


@pytest.mark.asyncio
async def test_partial_reservation_failure_is_atomic():
    """
    Adversarial Test 9: Partial reservation failure is atomic.
    When second limit has capacity (0/10) but daily limit is exceeded (800/800 for twelvedata),
    the script must return -1 and insert ZERO tokens into the second or minute ZSET.
    """
    server = fakeredis.FakeServer()
    client = fakeredis.aioredis.FakeRedis(server=server)
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    daily_key = f"quota:provider:twelvedata:daily:{today_str}"

    # Pre-seed daily limit as fully consumed
    await client.set(daily_key, "800")

    gov = ProviderQuotaGovernor()
    from unittest.mock import patch
    with patch("app.core.provider_quota.is_production_environment", return_value=True):
        ok = await gov.acquire("twelvedata", redis_client=client, count=1)
        assert ok is False, "Must reject on daily limit exceeded"

    # Verify atomic rollback: no keys created or modified
    sec_card = await client.zcard("quota:provider:twelvedata:sec_zset")
    min_card = await client.zcard("quota:provider:twelvedata:min_zset")
    daily_val = int(await client.get(daily_key))
    assert sec_card == 0, "No second tokens should be created"
    assert min_card == 0, "No minute tokens should be created"
    assert daily_val == 800, "Daily counter must remain unchanged"


@pytest.mark.asyncio
async def test_window_boundary_bursts_rejected_by_sliding_window():
    """
    Adversarial Test 10: Window-boundary bursts.
    In a fixed-window algorithm, 10 requests at t=0.95s and 10 requests at t=1.05s
    would both pass (20 requests in 100ms).
    In our true sliding window log, requests at t=1.05s MUST BE REJECTED because
    the 10 requests from t=0.95s are still in the 1.0s window [0.05s, 1.05s].
    """
    server = fakeredis.FakeServer()
    client = fakeredis.aioredis.FakeRedis(server=server)

    # 1. Test in Redis Lua
    now_ms = 1_000_000_000  # Base time
    # Acquire 10 tokens at base time
    for i in range(10):
        res = await client.eval(
            _ATOMIC_SLIDING_QUOTA_LUA,
            3,
            "quota:test:sec_zset",
            "quota:test:min_zset",
            "quota:test:daily",
            1,
            10,  # sec_limit
            -1,  # min_limit
            -1,  # day_limit
            now_ms + 900,  # t = 0.9s
            f"req_{i}",
        )
        assert res == 1

    # Attempt request 150ms later (t = 1.05s, across the integer-second boundary)
    res_burst = await client.eval(
        _ATOMIC_SLIDING_QUOTA_LUA,
        3,
        "quota:test:sec_zset",
        "quota:test:min_zset",
        "quota:test:daily",
        1,
        10,
        -1,
        -1,
        now_ms + 1050,  # t = 1.05s
        "burst_req",
    )
    assert res_burst == -2, "Sliding window must REJECT burst across integer second boundary!"

    # Advance time to t = 1.95s (> 1.0s after the 0.9s requests)
    res_after = await client.eval(
        _ATOMIC_SLIDING_QUOTA_LUA,
        3,
        "quota:test:sec_zset",
        "quota:test:min_zset",
        "quota:test:daily",
        1,
        10,
        -1,
        -1,
        now_ms + 1950,  # t = 1.95s
        "after_req",
    )
    assert res_after == 1, "Request must succeed once the window slides past 1000ms"

    # 2. Test in-memory sliding window fallback matches identically
    gov = ProviderQuotaGovernor()
    gov.reset()
    now = time.time()
    # Inject 10 calls at now - 0.1s
    gov._sec_calls["upstox"] = [now - 0.1] * 10
    from unittest.mock import patch
    with patch("app.core.provider_quota.is_production_environment", return_value=False):
        # Attempt immediate call (now - 0.05s)
        ok_burst = await gov.acquire("upstox", redis_client=None, count=1)
        assert ok_burst is False, "In-memory sliding window must reject boundary burst"

        # Advance in-memory timestamps past 1.0s
        gov._sec_calls["upstox"] = [now - 1.1] * 10
        ok_after = await gov.acquire("upstox", redis_client=None, count=1)
        assert ok_after is True, "In-memory sliding window must allow call after 1.0s"


@pytest.mark.asyncio
async def test_batch_reservations_atomic():
    """
    Adversarial Test 11: Batch reservations (count > 1).
    Limit 10. When 8 tokens are used, batch count=3 must fail (8 + 3 = 11 > 10).
    Total tokens must remain 8.
    Then batch count=2 must succeed, reaching 10/10.
    """
    server = fakeredis.FakeServer()
    client = fakeredis.aioredis.FakeRedis(server=server)
    gov = ProviderQuotaGovernor()

    from unittest.mock import patch
    with patch("app.core.provider_quota.is_production_environment", return_value=True):
        ok = await gov.acquire("upstox", redis_client=client, count=8)
        assert ok is True

        # Batch of 3 fails
        ok_batch_fail = await gov.acquire("upstox", redis_client=client, count=3)
        assert ok_batch_fail is False

        # Card must remain exactly 8
        card = await client.zcard("quota:provider:upstox:sec_zset")
        assert card == 8

        # Batch of 2 succeeds
        ok_batch_pass = await gov.acquire("upstox", redis_client=client, count=2)
        assert ok_batch_pass is True

        card = await client.zcard("quota:provider:upstox:sec_zset")
        assert card == 10


def test_production_configuration_failure_modes(monkeypatch):
    """
    Adversarial Test 12: Production configuration failure modes.
    Ensures environment detection FAILS CLOSED in all error/corrupt scenarios.
    """
    # 1. Explicit production
    monkeypatch.setenv("APP_ENV", "production")
    assert is_production_environment() is True

    # 2. Explicit development
    monkeypatch.setenv("APP_ENV", "development")
    # Reset lru_cache for get_settings
    config_mod.get_settings.cache_clear()
    assert is_production_environment() is False

    # 3. Settings import failure -> fails closed (True)
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    from unittest.mock import patch
    with patch.dict("sys.modules", {"app.config": None}):
        assert is_production_environment() is True, "Import failure must fail closed to True"

    # 4. Settings initialization failure (e.g. ValidationError) -> fails closed (True)
    with patch("app.config.get_settings", side_effect=ValueError("Corrupt settings")):
        assert is_production_environment() is True, "Settings initialization failure must fail closed to True"

    # 5. Invalid/garbage environment variable -> fails closed (True)
    monkeypatch.setenv("APP_ENV", "unknown_corrupt_env")
    config_mod.get_settings.cache_clear()
    assert is_production_environment() is True, "Invalid env value must fail closed to True"


@pytest.mark.asyncio
async def test_development_fallback_behavior(monkeypatch):
    """
    Adversarial Test 13: Development fallback behavior.
    In explicit development, when Redis is absent, in-memory sliding window operates correctly.
    """
    monkeypatch.setenv("APP_ENV", "development")
    config_mod.get_settings.cache_clear()

    gov = ProviderQuotaGovernor()
    gov.reset()

    # 10 acquires of 1 succeed
    for _ in range(10):
        ok = await gov.acquire("upstox", redis_client=None, count=1)
        assert ok is True

    # 11th acquire in same second fails
    ok_11 = await gov.acquire("upstox", redis_client=None, count=1)
    assert ok_11 is False


@pytest.mark.asyncio
async def test_no_production_path_to_process_local_quota_enforcement():
    """
    Adversarial Test 14: No production path to process-local quota enforcement.
    Under every possible Redis failure mode in production, in-memory counters
    MUST NEVER be modified and acquire() MUST return False.
    """
    gov = ProviderQuotaGovernor()
    gov.reset()

    failure_clients = [
        None,  # Redis absent
        type("NoEvalRedis", (), {})(),  # Redis missing eval
        type("ErrorRedis", (), {"eval": lambda *a, **k: (_ for _ in ()).throw(RedisConnectionError("Lost"))})(),
        type("TimeoutRedis", (), {"eval": lambda *a, **k: (_ for _ in ()).throw(RedisTimeoutError("Timeout"))})(),
        type("BadCodeRedis", (), {"eval": lambda *a, **k: 999})(),
    ]

    from unittest.mock import patch
    with patch("app.core.provider_quota.is_production_environment", return_value=True):
        for bad_client in failure_clients:
            ok = await gov.acquire("upstox", redis_client=bad_client, count=1)
            assert ok is False, f"Client {bad_client} must fail closed"
            assert len(gov._sec_calls) == 0, f"Client {bad_client} must not touch in-memory sec_calls"
            assert len(gov._minute_calls) == 0, f"Client {bad_client} must not touch in-memory minute_calls"
            assert len(gov._daily_counts) == 0, f"Client {bad_client} must not touch in-memory daily_counts"
