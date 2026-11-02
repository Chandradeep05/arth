"""
ARTH Stage 1 Quota Governor Boundary & Cache Invariant Tests.

Verifies:
1. Cache hit on Twelve Data single quote consumes ZERO quota tokens.
2. Twelve Data batch quotes acquire 1 token per requested symbol (8 symbols = 8 tokens).
3. Twelve Data batch quotes on cached symbols consume ZERO quota tokens.
4. Partial batch cache misses consume quota ONLY for the actual missing symbols.
5. Outbound requests are blocked cleanly when quota is exhausted without making HTTP calls.
6. Central quota governor properly tracks and rolls back multi-token batch acquires.
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

    # Pre-cache 3 symbols
    for sym in ["AAPL", "MSFT", "GOOGL"]:
        adapter._cache_set(f"quote:{sym}", {
            "symbol": sym, "name": sym, "price": 100.0, "change": 0.0,
            "change_percent": 0.0, "volume": 0, "high": 100.0, "low": 100.0,
            "open": 100.0, "previous_close": 100.0, "market_cap": None,
            "pe_ratio": None, "timestamp": None, "exchange": "NASDAQ",
            "market": "us", "currency": "USD",
        }, ttl=300)

    # Request 5 symbols: 3 cached + 2 uncached ("NVDA", "AMZN")
    symbols = ["AAPL", "MSFT", "GOOGL", "NVDA", "AMZN"]

    batch_response = {
        "NVDA": {"symbol": "NVDA", "close": "500.0", "timestamp": 1700000000},
        "AMZN": {"symbol": "AMZN", "close": "180.0", "timestamp": 1700000000},
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


@pytest.mark.asyncio
async def test_upstox_cache_hit_consumes_zero_quota():
    """Upstox quote cache hit must consume ZERO quota tokens."""
    from app.data.adapters.upstox import UpstoxAdapter, _cache as up_cache
    up_cache.clear()

    adapter = UpstoxAdapter()

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "status": "success",
        "data": {
            "NSE_EQ:RELIANCE": {
                "last_price": 2800.0,
                "net_change": 15.0,
                "ohlc": {"open": 2790.0, "high": 2810.0, "low": 2785.0, "close": 2800.0},
                "volume": 1200000,
            }
        }
    }

    mock_client = AsyncMock()
    mock_client.get.return_value = mock_resp

    with patch("app.data.adapters.upstox._get_token", return_value="fake_token"), \
         patch("app.data.adapters.upstox._get_client", return_value=mock_client), \
         patch.object(adapter, "_get_instrument_key", return_value="NSE_EQ:RELIANCE"), \
         patch.object(quota_governor, "acquire", wraps=quota_governor.acquire) as mock_acquire:

        # 1. First call: cache miss -> outbound HTTP call -> acquires exactly 1 token
        res1 = await adapter.get_quote("RELIANCE.NS")
        assert res1 is not None
        assert res1["price"] == 2800.0
        assert mock_acquire.call_count == 1
        assert mock_acquire.call_args_list[0].args[0] == "upstox"
        assert mock_client.get.call_count == 1

        # 2. Second call: cache hit -> returns from cache -> ZERO quota acquired!
        res2 = await adapter.get_quote("RELIANCE.NS")
        assert res2 is not None
        assert res2["price"] == 2800.0
        assert mock_acquire.call_count == 1
        assert mock_client.get.call_count == 1


@pytest.mark.asyncio
async def test_finnhub_cache_hit_consumes_zero_quota():
    """Finnhub quote cache hit must consume ZERO quota tokens."""
    from app.data.adapters.finnhub import FinnhubAdapter, _cache as fh_cache
    fh_cache.clear()

    adapter = FinnhubAdapter()

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"c": 190.0, "d": 2.5, "dp": 1.33}

    mock_client = AsyncMock()
    mock_client.get.return_value = mock_resp

    with patch("app.data.adapters.finnhub._get_api_key", return_value="fake_key"), \
         patch("app.data.adapters.finnhub._get_client", return_value=mock_client), \
         patch.object(quota_governor, "acquire", wraps=quota_governor.acquire) as mock_acquire:

        # 1. First call: cache miss -> outbound call -> acquires 1 token
        res1 = await adapter._throttled_get("quote", {"symbol": "AAPL"})
        assert res1 == {"c": 190.0, "d": 2.5, "dp": 1.33}
        assert mock_acquire.call_count == 1
        assert mock_acquire.call_args_list[0].args[0] == "finnhub"
        assert mock_client.get.call_count == 1

        # 2. Second call: cache hit -> returns from cache -> ZERO quota acquired!
        res2 = await adapter._throttled_get("quote", {"symbol": "AAPL"})
        assert res2 == {"c": 190.0, "d": 2.5, "dp": 1.33}
        assert mock_acquire.call_count == 1
        assert mock_client.get.call_count == 1
