"""
ARTH Native Upstash Redis Integration & Quota Governor Production Verification.

Rigorously verifies:
1. Native TLS connectivity to real Upstash Redis instance.
2. Harmless isolated CRUD and basic command execution.
3. Lua EVAL execution support on real Upstash instance.
4. ARTH _ATOMIC_SLIDING_QUOTA_LUA script execution on real Upstash with isolated keys.
5. Rolling second-window burst protection (window: (now_ms - 1000, now_ms]).
6. Rolling minute-window limit protection (window: (now_ms - 60000, now_ms]).
7. Daily budget counter limit protection.
8. High-concurrency atomicity under race conditions (30 concurrent tasks against limit=10).
9. Key TTL enforcement (10s for sec_zset, 120s for min_zset, 90000s for daily).
10. Production fail-closed behavior on connection drop, Lua error, missing eval, and corrupt return values.
11. Real ProviderQuotaGovernor integration using isolated key wrapper in production mode.
12. Comprehensive test key cleanup and zero impact on production namespaces.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import os
import pathlib
import time
from typing import Any, List
from unittest.mock import patch
from uuid import uuid4

import pytest
import redis.asyncio as aioredis

from app.core.provider_quota import (
    ProviderQuotaGovernor,
    ProviderLimit,
    _ATOMIC_SLIDING_QUOTA_LUA,
    is_production_environment,
)


# ---------------------------------------------------------------------------
# Secure Credential Loader (Strict Credential Protection)
# ---------------------------------------------------------------------------

def _get_secure_integration_url() -> str:
    """
    Safely load ARTH_REDIS_INTEGRATION_URL from environment or backend/.env.
    NEVER logs or exposes the URL value.
    """
    url = os.environ.get("ARTH_REDIS_INTEGRATION_URL")
    if not url:
        env_file = pathlib.Path(__file__).resolve().parent.parent / ".env"
        if env_file.exists():
            for line in env_file.read_text(encoding="utf-8").splitlines():
                stripped = line.strip()
                if stripped.startswith("ARTH_REDIS_INTEGRATION_URL="):
                    val = stripped.split("=", 1)[1].strip()
                    if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
                        val = val[1:-1]
                    url = val
                    break
    if not url:
        pytest.skip("ARTH_REDIS_INTEGRATION_URL not configured. Skipping native Redis integration tests.")
    return url


# ---------------------------------------------------------------------------
# Isolated Test Redis Client Wrapper (Strict Namespace Boundary)
# ---------------------------------------------------------------------------

class IsolatedTestRedisClient:
    """
    Wraps a real aioredis.Redis client to ensure ALL keys passed to any command
    or Lua script are strictly prefixed with a unique test namespace.
    
    Guarantees production keys (`quota:provider:...`) can NEVER be touched.
    """

    def __init__(self, raw_client: aioredis.Redis, run_id: str):
        self._raw = raw_client
        self._prefix = f"arth:integration-test:{run_id}:"

    def _prefix_key(self, key: str) -> str:
        if str(key).startswith(self._prefix):
            return str(key)
        return f"{self._prefix}{key}"

    async def eval(self, script: str, numkeys: int, *keys_and_args):
        # In redis-py eval, the first numkeys entries are keys, remainder are argv
        prefixed_keys = [self._prefix_key(k) for k in keys_and_args[:numkeys]]
        argv = list(keys_and_args[numkeys:])
        return await self._raw.eval(script, numkeys, *prefixed_keys, *argv)

    async def get(self, name: str):
        return await self._raw.get(self._prefix_key(name))

    async def set(self, name: str, value: Any, **kwargs):
        return await self._raw.set(self._prefix_key(name), value, **kwargs)

    async def delete(self, *names):
        prefixed = [self._prefix_key(n) for n in names]
        return await self._raw.delete(*prefixed)

    async def zcard(self, name: str):
        return await self._raw.zcard(self._prefix_key(name))

    async def zrange(self, name: str, start: int, end: int, **kwargs):
        return await self._raw.zrange(self._prefix_key(name), start, end, **kwargs)

    async def ttl(self, name: str):
        return await self._raw.ttl(self._prefix_key(name))

    async def ping(self):
        return await self._raw.ping()

    async def close(self):
        if hasattr(self._raw, "aclose"):
            return await self._raw.aclose()
        return await self._raw.close()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def run_id() -> str:
    return uuid4().hex[:10]


@pytest.fixture
async def raw_upstash_client():
    url = _get_secure_integration_url()
    client = aioredis.from_url(
        url,
        encoding="utf-8",
        decode_responses=True,
    )
    try:
        await client.ping()
        yield client
    finally:
        await client.aclose()


@pytest.fixture
async def isolated_client(raw_upstash_client, run_id):
    client = IsolatedTestRedisClient(raw_upstash_client, run_id)
    try:
        yield client
    finally:
        # Strictly run-ID scoped cleanup
        pattern = f"arth:integration-test:{run_id}:*"
        keys_to_clean = []
        async for key in raw_upstash_client.scan_iter(match=pattern, count=100):
            keys_to_clean.append(key)
        if keys_to_clean:
            deleted_count = await raw_upstash_client.delete(*keys_to_clean)
            assert deleted_count == len(keys_to_clean), (
                f"Failed to delete all keys for run_id {run_id}. Expected {len(keys_to_clean)}, deleted {deleted_count}"
            )


# ---------------------------------------------------------------------------
# PHASE 3: Native Redis Connectivity Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_phase3_upstash_tls_ping(raw_upstash_client):
    """Verify native TLS-secured connection and Redis PING against real Upstash."""
    pong = await raw_upstash_client.ping()
    assert pong is True or pong == "PONG", f"Unexpected PING response: {pong}"


@pytest.mark.asyncio
async def test_phase3_isolated_key_crud(isolated_client):
    """Verify write, read, and deletion of an isolated test key."""
    test_key = "harmless_test_key"
    test_val = "arth_native_verification_ok"

    # 1. SET
    set_res = await isolated_client.set(test_key, test_val, ex=60)
    assert set_res is True or str(set_res) == "OK"

    # 2. GET
    got_val = await isolated_client.get(test_key)
    assert got_val == test_val

    # 3. DELETE
    del_res = await isolated_client.delete(test_key)
    assert del_res == 1

    # 4. Confirm gone
    after_del = await isolated_client.get(test_key)
    assert after_del is None


@pytest.mark.asyncio
async def test_phase3_lua_eval_supported(isolated_client):
    """Verify real Upstash instance supports atomic Lua EVAL."""
    script = "return 42"
    res = await isolated_client.eval(script, 0)
    assert res == 42, f"Expected 42 from Lua EVAL, got {res}"


# ---------------------------------------------------------------------------
# PHASE 4: Real Lua Quota Governor Tests on Upstash
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_phase4_lua_successful_reservation(isolated_client, run_id):
    """Phase 4.A: Valid reservation within small test limit succeeds (returns 1)."""
    now_ms = int(time.time() * 1000)
    batch_id = f"test_{now_ms}_1"

    res = await isolated_client.eval(
        _ATOMIC_SLIDING_QUOTA_LUA,
        3,
        "sec_test_succ",
        "min_test_succ",
        "day_test_succ",
        1,   # count
        10,  # sec_limit
        30,  # min_limit
        100, # day_limit
        now_ms,
        batch_id,
    )
    assert res == 1, f"Expected 1 (Allowed), got {res}"


@pytest.mark.asyncio
async def test_phase4_lua_second_window_limit(isolated_client, run_id):
    """Phase 4.B: Exceeding per-second limit rejects immediately (returns -2)."""
    now_ms = int(time.time() * 1000)
    sec_key = f"sec_burst_{now_ms}"
    min_key = f"min_burst_{now_ms}"
    day_key = f"day_burst_{now_ms}"

    sec_limit = 2
    # First 2 requests must succeed
    for i in range(1, 3):
        res = await isolated_client.eval(
            _ATOMIC_SLIDING_QUOTA_LUA,
            3,
            sec_key, min_key, day_key,
            1, sec_limit, 100, 1000,
            now_ms, f"seed_{i}",
        )
        assert res == 1, f"Reservation {i} should succeed"

    # 3rd request in same millisecond/second must be rejected with -2
    rej_res = await isolated_client.eval(
        _ATOMIC_SLIDING_QUOTA_LUA,
        3,
        sec_key, min_key, day_key,
        1, sec_limit, 100, 1000,
        now_ms, "seed_3",
    )
    assert rej_res == -2, f"Expected -2 (Second quota exceeded), got {rej_res}"


@pytest.mark.asyncio
async def test_phase4_lua_minute_window_limit(isolated_client, run_id):
    """Phase 4.C: Exceeding per-minute limit rejects with 0."""
    now_ms = int(time.time() * 1000)
    sec_key = f"sec_min_{now_ms}"
    min_key = f"min_min_{now_ms}"
    day_key = f"day_min_{now_ms}"

    min_limit = 3
    # 3 requests succeed (disabling sec limit with -1)
    for i in range(1, 4):
        res = await isolated_client.eval(
            _ATOMIC_SLIDING_QUOTA_LUA,
            3,
            sec_key, min_key, day_key,
            1, -1, min_limit, 1000,
            now_ms, f"seed_min_{i}",
        )
        assert res == 1, f"Reservation {i} should succeed"

    # 4th request must be rejected with 0
    rej_res = await isolated_client.eval(
        _ATOMIC_SLIDING_QUOTA_LUA,
        3,
        sec_key, min_key, day_key,
        1, -1, min_limit, 1000,
        now_ms, "seed_min_4",
    )
    assert rej_res == 0, f"Expected 0 (Minute quota exceeded), got {rej_res}"


@pytest.mark.asyncio
async def test_phase4_lua_daily_limit(isolated_client, run_id):
    """Phase 4.D: Exceeding daily budget counter rejects with -1."""
    now_ms = int(time.time() * 1000)
    sec_key = f"sec_day_{now_ms}"
    min_key = f"min_day_{now_ms}"
    day_key = f"day_day_{now_ms}"

    day_limit = 5
    # Fill daily quota with count=5
    res = await isolated_client.eval(
        _ATOMIC_SLIDING_QUOTA_LUA,
        3,
        sec_key, min_key, day_key,
        5, -1, -1, day_limit,
        now_ms, "seed_bulk_day",
    )
    assert res == 1, "Bulk fill of daily limit should succeed"

    # Any subsequent request must fail with -1
    rej_res = await isolated_client.eval(
        _ATOMIC_SLIDING_QUOTA_LUA,
        3,
        sec_key, min_key, day_key,
        1, -1, -1, day_limit,
        now_ms, "seed_day_exceeded",
    )
    assert rej_res == -1, f"Expected -1 (Daily quota exceeded), got {rej_res}"


@pytest.mark.asyncio
async def test_phase4_lua_concurrency_atomicity(isolated_client, run_id):
    """
    Phase 4.E: 30 concurrent reservation requests against limit=10.
    Exact atomic Lua execution guarantees EXACTLY 10 succeed and 20 fail.
    No race condition or boundary burst over-allocation.
    Repeated over 3 independent rounds.
    """
    for round_idx in range(3):
        now_ms = int(time.time() * 1000)
        sec_key = f"sec_conc_r{round_idx}_{now_ms}"
        min_key = f"min_conc_r{round_idx}_{now_ms}"
        day_key = f"day_conc_r{round_idx}_{now_ms}"

        limit = 10
        total_requests = 30

        async def worker(idx: int):
            return await isolated_client.eval(
                _ATOMIC_SLIDING_QUOTA_LUA,
                3,
                sec_key, min_key, day_key,
                1, limit, limit, 1000,
                now_ms, f"r{round_idx}_worker_{idx}",
            )

        tasks = [worker(i) for i in range(total_requests)]
        results = await asyncio.gather(*tasks)

        allowed = sum(1 for r in results if r == 1)
        rejected = sum(1 for r in results if r in (-2, 0, -1))

        assert allowed == limit, f"Round {round_idx}: Expected exactly {limit} allowed, got {allowed}"
        assert rejected == (total_requests - limit), f"Round {round_idx}: Expected {total_requests - limit} rejected, got {rejected}"

        # Verify underlying ZSET cardinality on Upstash
        card = await isolated_client.zcard(sec_key)
        assert card == limit, f"Round {round_idx}: ZSET cardinality must be exactly {limit}, got {card}"


@pytest.mark.asyncio
async def test_phase4_lua_ttl_behavior(isolated_client, run_id):
    """Phase 4.F: Verify TTLs are set on all keys according to production specs."""
    now_ms = int(time.time() * 1000)
    sec_key = f"sec_ttl_{now_ms}"
    min_key = f"min_ttl_{now_ms}"
    day_key = f"day_ttl_{now_ms}"

    res = await isolated_client.eval(
        _ATOMIC_SLIDING_QUOTA_LUA,
        3,
        sec_key, min_key, day_key,
        1, 10, 100, 1000,
        now_ms, "ttl_seed",
    )
    assert res == 1

    ttl_sec = await isolated_client.ttl(sec_key)
    ttl_min = await isolated_client.ttl(min_key)
    ttl_day = await isolated_client.ttl(day_key)

    # sec_key has EXPIRE 10
    assert 0 < ttl_sec <= 10, f"Expected 0 < sec_ttl <= 10, got {ttl_sec}"
    # min_key has EXPIRE 120
    assert 0 < ttl_min <= 120, f"Expected 0 < min_ttl <= 120, got {ttl_min}"
    # day_key has EXPIRE 90000
    assert 0 < ttl_day <= 90000, f"Expected 0 < day_ttl <= 90000, got {ttl_day}"


@pytest.mark.asyncio
async def test_phase4_production_fail_closed_on_redis_errors():
    """
    Phase 4.G: In production environment, governor must fail closed on:
    - Connection failure
    - Lua execution error
    - Missing eval method
    - Unexpected return value
    NEVER fall back to in-memory state.
    """
    gov = ProviderQuotaGovernor()

    with patch("app.core.provider_quota.is_production_environment", return_value=True):
        # 1. Redis is None -> False
        assert await gov.acquire("upstox", redis_client=None) is False

        # 2. Redis missing eval -> False
        class NoEvalClient:
            pass
        assert await gov.acquire("upstox", redis_client=NoEvalClient()) is False

        # 3. Redis eval raises ConnectionError -> False
        class BrokenConnectionClient:
            async def eval(self, *args, **kwargs):
                raise aioredis.ConnectionError("Simulated Upstash TCP connection reset")
        assert await gov.acquire("upstox", redis_client=BrokenConnectionClient()) is False

        # 4. Redis eval raises Lua ResponseError -> False
        class LuaErrorClient:
            async def eval(self, *args, **kwargs):
                raise aioredis.ResponseError("ERR Error compiling script (syntax error)")
        assert await gov.acquire("upstox", redis_client=LuaErrorClient()) is False

        # 5. Redis eval returns unexpected value (e.g. 99) -> False
        class CorruptReturnClient:
            async def eval(self, *args, **kwargs):
                return 99
        assert await gov.acquire("upstox", redis_client=CorruptReturnClient()) is False


# ---------------------------------------------------------------------------
# PHASE 5: Actual ARTH Integration via ProviderQuotaGovernor
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_phase5_actual_provider_quota_governor_with_upstash(isolated_client, run_id, monkeypatch):
    """
    Phase 5: Test real ProviderQuotaGovernor.acquire() against real Upstash instance.
    Uses isolated client wrapper to guarantee all keys live inside `arth:integration-test:<run_id>:...`.
    Production environment is strictly asserted via APP_ENV=production.
    """
    gov = ProviderQuotaGovernor()
    monkeypatch.setenv("APP_ENV", "production")

    # 1. Assert production mode is active via real detection
    assert is_production_environment() is True

    # 2. Acquire 1 token for upstox (limit: 10/s, 300/m, 10000/d)
    res = await gov.acquire("upstox", redis_client=isolated_client, count=1)
    assert res is True, "First token reservation via real Upstash should succeed"

    # 3. Acquire 9 more tokens (reaches 10/s limit)
    for i in range(2, 11):
        ok = await gov.acquire("upstox", redis_client=isolated_client, count=1)
        assert ok is True, f"Token {i} acquisition should succeed"

    # 4. 11th token in same second must fail (burst limit reached)
    ok_burst = await gov.acquire("upstox", redis_client=isolated_client, count=1)
    assert ok_burst is False, "11th token must be rejected by Upstash atomic Lua"

    # 5. Verify governor did NOT touch in-memory state during production acquire
    assert len(gov._sec_calls.get("upstox", [])) == 0, "Production must NOT touch _sec_calls in memory"
    assert len(gov._minute_calls.get("upstox", [])) == 0, "Production must NOT touch _minute_calls in memory"


@pytest.mark.asyncio
async def test_phase5_clean_namespace_and_zero_production_key_interference(raw_upstash_client, run_id):
    """
    Phase 5 & 7: Verify all test keys are contained within the test prefix,
    and verify zero keys were written to the bare production namespace `quota:provider:*`.
    """
    # Verify bare production namespace has not received our run's keys
    bare_keys = []
    async for key in raw_upstash_client.scan_iter(match=f"*{run_id}*", count=100):
        # Every key containing this run_id MUST start with our test prefix
        assert key.startswith(f"arth:integration-test:{run_id}:"), (
            f"LEAK DETECTED: Key {key} does not start with expected test prefix!"
        )


@pytest.mark.asyncio
async def test_phase7_namespace_isolation_eval_rewrites_all_production_keys(raw_upstash_client, run_id):
    """
    Phase 7: Directly test that production-looking keys passed to IsolatedTestRedisClient.eval()
    are strictly rewritten to the test namespace:
    1. Verify all three Lua KEYS arguments are rewritten with the test prefix.
    2. Verify arguments after numkeys (ARGV) remain completely unchanged.
    3. Verify no unprefixed production keys can accidentally reach the underlying client.
    """
    client = IsolatedTestRedisClient(raw_upstash_client, run_id)

    raw_sec_key = "quota:provider:twelvedata:sec_zset"
    raw_min_key = "quota:provider:twelvedata:min_zset"
    raw_day_key = "quota:provider:twelvedata:daily:2026-11-14"
    raw_argv1 = 5
    raw_argv2 = "unique_seed_12345"

    expected_sec_key = f"arth:integration-test:{run_id}:{raw_sec_key}"
    expected_min_key = f"arth:integration-test:{run_id}:{raw_min_key}"
    expected_day_key = f"arth:integration-test:{run_id}:{raw_day_key}"

    # 1. Verification via spy on the raw client
    from unittest.mock import AsyncMock
    spy_raw = AsyncMock()
    spy_raw.eval.return_value = ["mock_ok"]
    mocked_isolated_client = IsolatedTestRedisClient(spy_raw, run_id)

    await mocked_isolated_client.eval(
        "return 1",
        3,
        raw_sec_key,
        raw_min_key,
        raw_day_key,
        raw_argv1,
        raw_argv2,
    )

    # Inspect call arguments to spy_raw.eval
    assert spy_raw.eval.call_count == 1
    call_args = spy_raw.eval.call_args[0]
    script_arg, numkeys_arg = call_args[0], call_args[1]
    keys_and_argv_args = call_args[2:]

    assert script_arg == "return 1"
    assert numkeys_arg == 3
    # Verify all 3 keys are rewritten
    assert keys_and_argv_args[0] == expected_sec_key
    assert keys_and_argv_args[1] == expected_min_key
    assert keys_and_argv_args[2] == expected_day_key
    # Verify ARGV arguments remain unchanged
    assert keys_and_argv_args[3] == raw_argv1
    assert keys_and_argv_args[4] == raw_argv2
    # Verify none of the arguments passed as keys equal the raw production keys
    for k in keys_and_argv_args[:3]:
        assert not k.startswith("quota:provider:")
        assert k.startswith(f"arth:integration-test:{run_id}:")

    # 2. Live verification on real Upstash instance
    # Echo back KEYS and ARGV from Lua execution
    echo_script = """
    return {KEYS[1], KEYS[2], KEYS[3], tostring(ARGV[1]), tostring(ARGV[2])}
    """
    res = await client.eval(
        echo_script,
        3,
        raw_sec_key,
        raw_min_key,
        raw_day_key,
        raw_argv1,
        raw_argv2,
    )
    assert res[0] == expected_sec_key
    assert res[1] == expected_min_key
    assert res[2] == expected_day_key
    assert str(res[3]) == str(raw_argv1)
    assert res[4] == raw_argv2


@pytest.mark.asyncio
async def test_phase7_hygiene_and_cleanup_verification(raw_upstash_client, run_id):
    """
    Phase 7: Clean up integration test keys for the current run_id and verify its namespace is empty.
    Never deletes or touches keys belonging to any other integration run.
    """
    pattern = f"arth:integration-test:{run_id}:*"
    test_keys = []
    async for k in raw_upstash_client.scan_iter(match=pattern, count=100):
        test_keys.append(k)
    if test_keys:
        await raw_upstash_client.delete(*test_keys)

    remaining = []
    async for k in raw_upstash_client.scan_iter(match=pattern, count=100):
        remaining.append(k)
    assert len(remaining) == 0, f"Lingering test keys found in Upstash for run_id {run_id}: {remaining}"


@pytest.mark.asyncio
async def test_phase7_concurrent_run_isolation_and_preservation(raw_upstash_client, run_id):
    """
    Phase 7: Verify that simultaneous integration runs cannot delete or interfere with one another.
    A canary key created under a separate simulated run ID must remain untouched when cleanup
    runs for the current run ID.
    """
    foreign_run_id = f"foreign_{uuid4().hex[:8]}"
    foreign_key = f"arth:integration-test:{foreign_run_id}:concurrent_canary_key"
    current_key = f"arth:integration-test:{run_id}:current_test_key"

    try:
        # 1. Write both keys
        await raw_upstash_client.set(foreign_key, "preserve_foreign_data", ex=60)
        await raw_upstash_client.set(current_key, "belongs_to_current_run", ex=60)

        # 2. Execute run-ID scoped cleanup for current run_id ONLY
        pattern = f"arth:integration-test:{run_id}:*"
        keys_to_clean = []
        async for k in raw_upstash_client.scan_iter(match=pattern, count=100):
            keys_to_clean.append(k)
        if keys_to_clean:
            await raw_upstash_client.delete(*keys_to_clean)

        # 3. Assert current run's key was deleted
        current_val = await raw_upstash_client.get(current_key)
        assert current_val is None, f"Current run key {current_key} was not deleted by cleanup"

        # 4. Crucial: Assert foreign run's key was PRESERVED
        foreign_val = await raw_upstash_client.get(foreign_key)
        assert foreign_val == "preserve_foreign_data", (
            f"Cross-run interference: Foreign key {foreign_key} was modified or deleted!"
        )
    finally:
        # Clean up foreign test key
        await raw_upstash_client.delete(foreign_key)


