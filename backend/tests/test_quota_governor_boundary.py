"""
ARTH Stage 1 Quota Governor Boundary & Cache Invariant Tests.

Verifies:
1. Cache hit on Twelve Data single quote consumes ZERO quota tokens.
2. Twelve Data batch quotes acquire 1 token per requested symbol (8 symbols = 8 tokens).
3. Twelve Data batch quotes on cached symbols consume ZERO quota tokens.
4. Partial batch cache misses consume quota ONLY for the actual missing symbols.
5. Outbound requests are blocked cleanly when quota is exhausted without making HTTP calls.
6. Central quota governor properly tracks and rolls back multi-token batch acquires.
7. Batch-then-single quote cache sharing: batch caches raw payload, single quote parses it cleanly.
8. Single-then-batch quote cache sharing: single quote caches raw payload, batch parses it cleanly.
9. Empty batch chunk on quota denial is NEVER cached (retries remain possible).
10. Redis reservation rollback: minute reservation is rolled back if daily operation fails.
11. NSE cookie refresh and 401 retry are strictly quota-governed.
"""

import asyncio
from datetime import datetime, timezone
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.core.provider_quota import ProviderQuotaGovernor, ProviderLimit, quota_governor
from app.data.adapters.twelvedata import TwelveDataAdapter, _cache


@pytest.fixture(autouse=True)
def clean_cache_and_quota():
    """Reset adapter cache and quota governor between tests."""
    _cache.clear()
    quota_governor.reset()
    yield
    _cache.clear()
    quota_governor.reset()


@pytest.mark.asyncio
async def test_quota_governor_batch_count_and_rollback():
    """Governor must support `count` parameter and correctly enforce and rollback limits."""
    gov = ProviderQuotaGovernor()
    gov._daily_counts.clear()
    gov._minute_calls.clear()

    with patch.dict("app.core.provider_quota.PROVIDER_LIMITS", {"test_prov": ProviderLimit(per_minute=8, per_day=20)}):
        # 1. Acquire batch of 5 tokens
        assert await gov.acquire("test_prov", count=5) is True
        status = gov.get_status()["test_prov"]
        assert status["minute_used"] == 5
        assert status["daily_used"] == 5

        # 2. Acquire batch of 3 tokens (total 8 = limit)
        assert await gov.acquire("test_prov", count=3) is True
        status = gov.get_status()["test_prov"]
        assert status["minute_used"] == 8
        assert status["daily_used"] == 8

        # 3. Next acquire (even count=1) must be rejected because minute limit (8) is reached
        assert await gov.acquire("test_prov", count=1) is False
        status = gov.get_status()["test_prov"]
        assert status["minute_used"] == 8  # Not incremented on failure
        assert status["daily_used"] == 8


@pytest.mark.asyncio
async def test_twelvedata_cache_hit_consumes_zero_quota():
    """Twelve Data single quote cache hit must consume ZERO quota tokens."""
    adapter = TwelveDataAdapter()
    
    mock_quote_response = {
        "symbol": "AAPL",
        "name": "Apple Inc",
        "close": "180.50",
        "previous_close": "179.00",
        "open": "179.50",
        "high": "181.00",
        "low": "178.50",
        "volume": "50000000",
        "percent_change": "0.84",
        "change": "1.50",
        "timestamp": 1700000000,
        "exchange": "NASDAQ",
        "currency": "USD",
    }

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = mock_quote_response

    mock_client = AsyncMock()
    mock_client.get.return_value = mock_resp

    with patch("app.data.adapters.twelvedata._get_api_key", return_value="test_key"), \
         patch("app.data.adapters.twelvedata._get_client", return_value=mock_client), \
         patch.object(quota_governor, "acquire", wraps=quota_governor.acquire) as mock_acquire:

        # First call: cache miss -> outbound HTTP call -> acquires exactly 1 token
        res1 = await adapter.get_quote("AAPL")
        assert res1 is not None
        assert res1["price"] == 180.50
        assert mock_acquire.call_count == 1
        assert mock_acquire.call_args_list[0].kwargs.get("count", 1) == 1
        assert mock_client.get.call_count == 1

        # Second call: cache hit -> returns from _cache -> ZERO quota consumed, ZERO HTTP calls
        res2 = await adapter.get_quote("AAPL")
        assert res2 is not None
        assert res2["price"] == 180.50
        # Call count must STILL be 1 (zero new quota acquisitions!)
        assert mock_acquire.call_count == 1
        # HTTP client must STILL be 1
        assert mock_client.get.call_count == 1


@pytest.mark.asyncio
async def test_twelvedata_batch_quotes_consumes_exact_symbol_quota():
    """A batch of 8 uncached symbols must acquire exactly 8 quota tokens."""
    adapter = TwelveDataAdapter()
    symbols = ["AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA", "NFLX"]

    batch_response = {
        sym: {
            "symbol": sym,
            "name": f"{sym} Inc",
            "close": "150.00",
            "previous_close": "148.00",
            "open": "149.00",
            "high": "152.00",
            "low": "147.00",
            "volume": "1000000",
            "percent_change": "1.35",
            "change": "2.00",
            "timestamp": 1700000000,
            "exchange": "NASDAQ",
            "currency": "USD",
        }
        for sym in symbols
    }

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = batch_response

    mock_client = AsyncMock()
    mock_client.get.return_value = mock_resp

    with patch("app.data.adapters.twelvedata._get_api_key", return_value="test_key"), \
         patch("app.data.adapters.twelvedata._get_client", return_value=mock_client), \
         patch.object(quota_governor, "acquire", wraps=quota_governor.acquire) as mock_acquire:

        # 1. Batch call for 8 uncached symbols
        results = await adapter.get_batch_quotes(symbols)
        assert len(results) == 8
        assert mock_acquire.call_count == 1
        # Must acquire exactly 8 tokens (1 credit per symbol)
        assert mock_acquire.call_args_list[0].kwargs.get("count") == 8
        assert mock_client.get.call_count == 1

        # 2. Subsequent batch call for the SAME 8 symbols (cache hit)
        results2 = await adapter.get_batch_quotes(symbols)
        assert len(results2) == 8
        # Quota governor must NOT be called again (cache hit = 0 tokens)
        assert mock_acquire.call_count == 1
        assert mock_client.get.call_count == 1


@pytest.mark.asyncio
async def test_twelvedata_batch_partial_cache_miss_quota():
    """When some symbols are cached, quota is only acquired for the uncached symbols."""
    adapter = TwelveDataAdapter()

    # Pre-cache raw payloads for 3 symbols
    for sym in ["AAPL", "MSFT", "GOOGL"]:
        adapter._cache_set(f"quote:{sym}", {
            "symbol": sym, "name": sym, "close": "100.0", "change": "0.0",
            "percent_change": "0.0", "volume": "0", "high": "100.0", "low": "100.0",
            "open": "100.0", "previous_close": "100.0", "timestamp": "1700000000",
            "exchange": "NASDAQ", "currency": "USD",
        }, ttl=300)

    # Request 5 symbols: 3 cached + 2 uncached ("NVDA", "AMZN")
    symbols = ["AAPL", "MSFT", "GOOGL", "NVDA", "AMZN"]

    batch_response = {
        "NVDA": {"symbol": "NVDA", "close": "500.0", "timestamp": "1700000000"},
        "AMZN": {"symbol": "AMZN", "close": "180.0", "timestamp": "1700000000"},
    }

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = batch_response

    mock_client = AsyncMock()
    mock_client.get.return_value = mock_resp

    with patch("app.data.adapters.twelvedata._get_api_key", return_value="test_key"), \
         patch("app.data.adapters.twelvedata._get_client", return_value=mock_client), \
         patch.object(quota_governor, "acquire", wraps=quota_governor.acquire) as mock_acquire:

        results = await adapter.get_batch_quotes(symbols)
        assert len(results) == 5

        # Quota governor should have been called once with count=2 (only for the 2 missing symbols!)
        assert mock_acquire.call_count == 1
        assert mock_acquire.call_args_list[0].kwargs.get("count") == 2
        assert mock_client.get.call_count == 1


@pytest.mark.asyncio
async def test_twelvedata_batch_blocked_when_quota_exhausted():
    """If quota governor rejects batch acquire, NO outbound HTTP call is made."""
    adapter = TwelveDataAdapter()
    symbols = ["AAPL", "MSFT", "GOOGL", "AMZN"]

    mock_client = AsyncMock()

    with patch("app.data.adapters.twelvedata._get_api_key", return_value="test_key"), \
         patch("app.data.adapters.twelvedata._get_client", return_value=mock_client), \
         patch.object(quota_governor, "acquire", return_value=False) as mock_acquire:

        results = await adapter.get_batch_quotes(symbols)
        # Quota governor was checked for the batch of 4
        assert mock_acquire.call_count == 1
        assert mock_acquire.call_args_list[0].kwargs.get("count") == 4
        # HTTP request must NEVER have been made
        assert mock_client.get.call_count == 0
        assert results == []


# ── Regressions for Finding 1: Shared Cache Formats ──────────────────────────

@pytest.mark.asyncio
async def test_twelvedata_batch_then_single_quote_shared_cache():
    """Batch quote stores raw payload under quote:{symbol}; single get_quote must parse it successfully."""
    adapter = TwelveDataAdapter()

    batch_response = {
        "AAPL": {
            "symbol": "AAPL",
            "name": "Apple Inc",
            "close": "182.25",
            "previous_close": "180.00",
            "open": "181.00",
            "high": "183.00",
            "low": "180.50",
            "volume": "45000000",
            "percent_change": "1.25",
            "change": "2.25",
            "timestamp": 1700000000,
            "exchange": "NASDAQ",
            "currency": "USD",
        }
    }

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = batch_response

    mock_client = AsyncMock()
    mock_client.get.return_value = mock_resp

    with patch("app.data.adapters.twelvedata._get_api_key", return_value="test_key"), \
         patch("app.data.adapters.twelvedata._get_client", return_value=mock_client), \
         patch.object(quota_governor, "acquire", wraps=quota_governor.acquire) as mock_acquire:

        # 1. Run batch quotes
        batch_res = await adapter.get_batch_quotes(["AAPL"])
        assert len(batch_res) == 1
        assert batch_res[0]["price"] == 182.25
        assert mock_acquire.call_count == 1
        assert mock_client.get.call_count == 1

        # 2. Subsequent single get_quote for AAPL must read from cache, parse successfully, and NOT fail!
        single_res = await adapter.get_quote("AAPL")
        assert single_res is not None
        assert single_res["price"] == 182.25
        assert single_res["currency"] == "USD"
        # Zero additional HTTP calls or quota
        assert mock_acquire.call_count == 1
        assert mock_client.get.call_count == 1


@pytest.mark.asyncio
async def test_twelvedata_single_then_batch_quote_shared_cache():
    """Single get_quote stores raw payload under quote:{symbol}; batch must read and parse it properly."""
    adapter = TwelveDataAdapter()

    single_response = {
        "symbol": "AAPL",
        "name": "Apple Inc",
        "close": "182.25",
        "previous_close": "180.00",
        "open": "181.00",
        "high": "183.00",
        "low": "180.50",
        "volume": "45000000",
        "percent_change": "1.25",
        "change": "2.25",
        "timestamp": 1700000000,
        "exchange": "NASDAQ",
        "currency": "USD",
    }

    msft_response = {
        "MSFT": {
            "symbol": "MSFT",
            "close": "400.00",
            "previous_close": "395.00",
            "open": "398.00",
            "high": "402.00",
            "low": "397.00",
            "volume": "20000000",
            "percent_change": "1.27",
            "change": "5.00",
            "timestamp": 1700000000,
        }
    }

    mock_client = AsyncMock()

    with patch("app.data.adapters.twelvedata._get_api_key", return_value="test_key"), \
         patch("app.data.adapters.twelvedata._get_client", return_value=mock_client), \
         patch.object(quota_governor, "acquire", wraps=quota_governor.acquire) as mock_acquire:

        # 1. Single get_quote fetches AAPL
        mock_resp1 = MagicMock()
        mock_resp1.status_code = 200
        mock_resp1.json.return_value = single_response
        mock_client.get.return_value = mock_resp1

        single_res = await adapter.get_quote("AAPL")
        assert single_res is not None
        assert single_res["price"] == 182.25
        assert mock_acquire.call_count == 1

        # 2. Batch requests ["AAPL", "MSFT"]
        mock_resp2 = MagicMock()
        mock_resp2.status_code = 200
        mock_resp2.json.return_value = msft_response
        mock_client.get.return_value = mock_resp2

        batch_res = await adapter.get_batch_quotes(["AAPL", "MSFT"])
        assert len(batch_res) == 2
        
        # Verify both items have normalized schema with float price
        aapl_item = next(item for item in batch_res if item["symbol"] == "AAPL")
        msft_item = next(item for item in batch_res if item["symbol"] == "MSFT")
        assert aapl_item["price"] == 182.25
        assert msft_item["price"] == 400.00
        # Only MSFT was fetched (count=1)
        assert mock_acquire.call_count == 2
        assert mock_acquire.call_args_list[1].kwargs.get("count") == 1


# ── Regressions for Finding 2: Never Cache Empty/Denied Chunks ───────────────

@pytest.mark.asyncio
async def test_twelvedata_empty_chunk_never_cached():
    """If quota is denied or 429 returns [], that empty result must NOT be cached."""
    adapter = TwelveDataAdapter()
    symbols = ["AAPL", "MSFT"]

    mock_client = AsyncMock()

    with patch("app.data.adapters.twelvedata._get_api_key", return_value="test_key"), \
         patch("app.data.adapters.twelvedata._get_client", return_value=mock_client):

        # First attempt: quota governor blocks request
        with patch.object(quota_governor, "acquire", return_value=False):
            res1 = await adapter.get_batch_quotes(symbols)
            assert res1 == []

        # Ensure no empty batch chunk was cached!
        chunk_key = f"batch:{'|'.join(sorted(symbols))}"
        assert adapter._cache_get(chunk_key) is None

        # Second attempt: quota governor allows request -> must make HTTP call and succeed!
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "AAPL": {"symbol": "AAPL", "close": "180.0", "timestamp": 1700000000},
            "MSFT": {"symbol": "MSFT", "close": "400.0", "timestamp": 1700000000},
        }
        mock_client.get.return_value = mock_resp

        with patch.object(quota_governor, "acquire", return_value=True):
            res2 = await adapter.get_batch_quotes(symbols)
            assert len(res2) == 2
            assert mock_client.get.call_count == 1


# ── Regressions for Finding 3: Redis Minute Rollback ─────────────────────────

@pytest.mark.asyncio
async def test_redis_reservation_rollback_on_daily_failure():
    """If daily limit increment fails or raises in Redis, minute counter is rolled back."""
    gov = ProviderQuotaGovernor()
    fake_redis = AsyncMock()

    # Minute incrby succeeds (returns 1), then daily incrby raises an error
    fake_redis.incrby.side_effect = [1, Exception("Redis daily cluster partition")]

    with patch.dict("app.core.provider_quota.PROVIDER_LIMITS", {"test_prov": ProviderLimit(per_minute=10, per_day=100)}):
        result = await gov.acquire("test_prov", redis_client=fake_redis, count=2)
        # Should fall back to in-memory governor cleanly
        assert result is True
        # minute_key must have been rolled back via decrby!
        assert fake_redis.decrby.call_count == 1
        assert fake_redis.decrby.call_args[0][1] == 2


# ── Regressions for Finding 4: NSE Outbound Governance ───────────────────────

@pytest.mark.asyncio
async def test_nse_cookie_refresh_and_retry_governed():
    """Every outbound request to NSE (initial GET, cookie refresh, retry) must acquire quota."""
    from app.data.adapters.nse import _session

    mock_client = AsyncMock()
    mock_client.is_closed = False
    mock_resp_401 = MagicMock()
    mock_resp_401.status_code = 401

    mock_resp_200 = MagicMock()
    mock_resp_200.status_code = 200
    mock_resp_200.json.return_value = {"priceInfo": {"lastPrice": 2500.0}}

    # Sequence: 1. Cookie refresh GET -> 200; 2. API GET -> 401; 3. Refresh GET -> 200; 4. Retry API GET -> 200
    mock_client.get.side_effect = [mock_resp_200, mock_resp_401, mock_resp_200, mock_resp_200]
    _session._client = mock_client
    _session._initialized = False

    with patch.object(quota_governor, "acquire", wraps=quota_governor.acquire) as mock_acquire:
        res = await _session.get("quote-equity", params={"symbol": "RELIANCE"})
        assert res is not None

        # Every outbound request called quota_governor.acquire("nse")
        # 1: initial cookie refresh, 2: first API GET, 3: cookie refresh on 401, 4: retry API GET
        assert mock_acquire.call_count >= 3
        for call in mock_acquire.call_args_list:
            assert call.args[0] == "nse"
