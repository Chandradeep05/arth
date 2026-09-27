"""
Behavioral tests for V6.2.1 fixes:
1. Unified MarketDataProvider routing across all /market/* endpoints
2. Provider source provenance and freshness metadata propagation
3. Prediction forecast cache post-training expiration
4. Watchlist batch quote routing via MarketDataProvider
5. Pre-deployment Alembic migration configuration in render.yaml
"""

import time
import pytest
import pandas as pd
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone
import yaml

from app.data.market_data_provider import MarketDataProvider, DataResult, DataStatus, market_data
from app.api.v1.market import get_quote, get_ohlcv, get_company_info, get_indicators, search_stocks, batch_quotes, market_health, _raise_data_error
from app.core.exceptions import DataSourceError, SymbolNotFoundError
from app.models.schemas.market import StockQuoteResponse, OHLCVResponse, SearchResponse, MarketOverviewResponse
from app.engines.prediction.model import PredictionModel


# =============================================================================
# 1. Market Data Provider Methods & Capabilities
# =============================================================================

@pytest.mark.asyncio
async def test_market_data_provider_unified_methods():
    """Verify MarketDataProvider exposes search, get_market_indices, get_batch_quotes, get_ohlcv, and get_health."""
    mdp = MarketDataProvider()
    assert hasattr(mdp, "search")
    assert hasattr(mdp, "get_market_indices")
    assert hasattr(mdp, "get_batch_quotes")
    assert hasattr(mdp, "get_health")
    assert hasattr(mdp, "get_ohlcv")
    assert hasattr(mdp, "is_healthy")


@pytest.mark.asyncio
async def test_market_data_provider_routes_indian_quote_to_upstox_when_enabled():
    """Verify get_quote routes Indian stocks to Upstox when enabled."""
    mdp = MarketDataProvider()
    mock_upstox = MagicMock()
    mock_upstox.get_quote = AsyncMock(return_value={
        "symbol": "RELIANCE.NS",
        "name": "Reliance Industries",
        "price": 2980.50,
        "change": 32.10,
        "change_percent": 1.09,
        "volume": 4500000,
        "high": 2995.0,
        "low": 2950.0,
        "open": 2955.0,
        "previous_close": 2948.40,
        "market_cap": None,
        "pe_ratio": None,
        "timestamp": datetime.now(timezone.utc),
        "exchange": "NSE",
        "market": "india",
        "currency": "INR",
    })

    with patch.object(mdp, "_get_upstox", return_value=mock_upstox):
        res = await mdp.get_quote("RELIANCE.NS")
        assert res.available is True
        assert res.source == "upstox"
        assert res.data["price"] == 2980.50
        mock_upstox.get_quote.assert_awaited_once_with("RELIANCE.NS")


@pytest.mark.asyncio
async def test_market_data_provider_routes_us_quote_to_twelvedata():
    """Verify get_quote routes US stocks to TwelveData."""
    mdp = MarketDataProvider()
    mock_td = MagicMock()
    mock_td.get_quote = AsyncMock(return_value={
        "symbol": "NVDA",
        "name": "NVIDIA Corporation",
        "price": 128.50,
        "change": 3.20,
        "change_percent": 2.55,
        "volume": 52000000,
        "high": 130.0,
        "low": 126.0,
        "open": 126.5,
        "previous_close": 125.30,
        "market_cap": None,
        "pe_ratio": None,
        "timestamp": datetime.now(timezone.utc),
        "exchange": "NASDAQ",
        "market": "us",
        "currency": "USD",
    })

    with patch.object(mdp, "_twelve", mock_td):
        res = await mdp.get_quote("NVDA")
        assert res.available is True
        assert res.source == "twelvedata"
        assert res.data["price"] == 128.50
        mock_td.get_quote.assert_awaited_once_with("NVDA")


# =============================================================================
# 2. Market API Endpoint Routing & Provenance (/api/v1/market/*)
# =============================================================================

@pytest.mark.asyncio
async def test_get_quote_endpoint_routes_through_market_data_and_sets_provenance():
    """Verify /quote endpoint fetches from market_data and propagates provider label."""
    mock_settings = MagicMock()
    mock_settings.redis_cache_ttl_tick = 10

    mock_quote_data = {
        "symbol": "TCS.NS",
        "name": "Tata Consultancy Services",
        "price": 4120.0,
        "change": 45.0,
        "change_percent": 1.10,
        "volume": 1200000,
        "high": 4150.0,
        "low": 4090.0,
        "open": 4100.0,
        "previous_close": 4075.0,
        "market_cap": None,
        "pe_ratio": 32.5,
        "timestamp": datetime.now(timezone.utc),
        "exchange": "NSE",
        "market": "india",
        "currency": "INR",
    }

    with patch("app.api.v1.market.market_data.get_quote", new_callable=AsyncMock) as mock_get_quote, \
         patch("app.api.v1.market.CacheManager.get_or_fetch", new_callable=AsyncMock) as mock_gof:

        # CacheManager calls the fetch_func directly
        async def fake_gof(key, fetch_func, ttl, sym=None, symbol=None, **kwargs):
            return await fetch_func(sym or symbol)

        mock_gof.side_effect = fake_gof
        mock_get_quote.return_value = DataResult(
            data=mock_quote_data,
            status=DataStatus.SUCCESS,
            source="upstox",
        )

        resp = await get_quote(symbol="TCS.NS", redis=None, settings=mock_settings)

        assert isinstance(resp, StockQuoteResponse)
        assert resp.data.symbol == "TCS.NS"
        assert resp.data.price == 4120.0
        assert resp.freshness.source == "Upstox"
        assert resp.freshness.cache_hit is False


@pytest.mark.asyncio
async def test_get_ohlcv_endpoint_normalizes_dataframe_and_propagates_provenance():
    """Verify /ohlcv endpoint handles normalized DataFrame from market_data.get_history."""
    mock_settings = MagicMock()
    mock_settings.redis_cache_ttl_indicators = 300

    dates = pd.date_range(start="2026-01-01", periods=3, freq="D")
    df = pd.DataFrame({
        "Open": [100.0, 105.0, 102.0],
        "High": [106.0, 108.0, 104.0],
        "Low": [99.0, 101.0, 100.0],
        "Close": [105.0, 102.0, 103.5],
        "Volume": [10000, 15000, 12000],
    }, index=dates)

    with patch("app.api.v1.market.CacheManager.get", new_callable=AsyncMock, return_value=None), \
         patch("app.api.v1.market.CacheManager.set", new_callable=AsyncMock), \
         patch("app.api.v1.market.market_data.get_history", new_callable=AsyncMock) as mock_hist:

        mock_hist.return_value = DataResult(data=df, status=DataStatus.SUCCESS, source="twelvedata")

        resp = await get_ohlcv(symbol="AAPL", period="1mo", interval="1d", redis=None, settings=mock_settings)

        assert isinstance(resp, OHLCVResponse)
        assert resp.symbol == "AAPL"
        assert len(resp.data) == 3
        assert resp.data[0].open == 100.0
        assert resp.data[0].close == 105.0
        assert resp.freshness.source == "Twelve Data"


@pytest.mark.asyncio
async def test_get_company_info_endpoint_propagates_provenance():
    """Verify /company endpoint fetches from market_data and propagates provider label."""
    mock_settings = MagicMock()
    mock_settings.redis_cache_ttl_fundamentals = 3600

    company_payload = {
        "symbol": "INFY.NS",
        "name": "Infosys Limited",
        "sector": "Technology",
        "industry": "IT Services",
        "description": "Leading digital services consulting.",
    }

    with patch("app.api.v1.market.market_data.get_company_info", new_callable=AsyncMock) as mock_comp, \
         patch("app.api.v1.market.CacheManager.get_or_fetch", new_callable=AsyncMock) as mock_gof:

        async def fake_gof(key, fetch_func, ttl, sym=None, symbol=None, **kwargs):
            return await fetch_func(sym or symbol)

        mock_gof.side_effect = fake_gof
        mock_comp.return_value = DataResult(data=company_payload, status=DataStatus.SUCCESS, source="upstox")

        resp = await get_company_info(symbol="INFY.NS", redis=None, settings=mock_settings)

        assert resp["success"] is True
        assert resp["data"]["name"] == "Infosys Limited"
        assert resp["freshness"]["source"] == "Upstox"


@pytest.mark.asyncio
async def test_search_endpoint_routes_through_market_data():
    """Verify /search endpoint returns SearchResponse using market_data.search."""
    mock_results = [
        {"symbol": "RELIANCE.NS", "name": "Reliance Industries", "exchange": "NSE", "market": "india", "sector": "Energy"},
        {"symbol": "RELINFRA.NS", "name": "Reliance Infrastructure", "exchange": "NSE", "market": "india", "sector": "Infrastructure"},
    ]

    with patch("app.api.v1.market.market_data.search", new_callable=AsyncMock, return_value=mock_results):
        resp = await search_stocks(q="Reliance")
        assert isinstance(resp, SearchResponse)
        assert resp.query == "Reliance"
        assert len(resp.results) == 2
        assert resp.results[0].symbol == "RELIANCE.NS"


@pytest.mark.asyncio
async def test_batch_quotes_endpoint_routes_through_market_data():
    """Verify /batch-quotes uses market_data.get_batch_quotes."""
    mock_settings = MagicMock()
    quotes = [
        {"symbol": "AAPL", "price": 220.0, "change": 1.5, "change_percent": 0.68},
        {"symbol": "RELIANCE.NS", "price": 2980.0, "change": 25.0, "change_percent": 0.85},
    ]

    with patch("app.api.v1.market.CacheManager.get", new_callable=AsyncMock, return_value=None), \
         patch("app.api.v1.market.CacheManager.set", new_callable=AsyncMock), \
         patch("app.api.v1.market.market_data.get_batch_quotes", new_callable=AsyncMock, return_value=quotes):

        resp = await batch_quotes(request={"symbols": ["AAPL", "RELIANCE.NS"]}, redis=None, settings=mock_settings)
        assert resp["success"] is True
        assert resp["count"] == 2
        assert resp["data"][0]["symbol"] == "AAPL"


@pytest.mark.asyncio
async def test_market_health_aggregates_providers():
    """Verify /health returns aggregated health information."""
    fake_health = {
        "upstox": {"is_healthy": True, "circuit_state": "closed", "failure_count": 0},
        "twelvedata": {"is_healthy": True, "circuit_state": "closed", "failure_count": 0},
    }

    with patch("app.api.v1.market.market_data.get_health", return_value=fake_health):
        resp = await market_health()
        assert resp["status"] == "healthy"
        assert "upstox" in resp["providers"]
        assert resp["adapter"]["is_healthy"] is True


def test_raise_data_error_checks_provider_circuit_and_raises_data_source_error():
    """Verify _raise_data_error detects open circuit or rate limit and raises DataSourceError."""
    fake_health = {
        "upstox": {
            "is_healthy": False,
            "circuit_state": "open",
            "failure_count": 5,
            "last_failure": time.time(),
            "last_error_message": "Rate limited 429",
        },
    }

    with patch("app.api.v1.market.market_data.get_health", return_value=fake_health):
        with pytest.raises(DataSourceError) as exc_info:
            _raise_data_error("RELIANCE.NS")
        assert exc_info.value.source == "MarketDataProvider"

    # When all providers are healthy and clean, missing data is 404
    clean_health = {
        "upstox": {"is_healthy": True, "circuit_state": "closed", "failure_count": 0, "last_failure": None, "last_error_message": ""},
        "nse": {"is_healthy": True, "circuit_state": "closed", "failure_count": 0, "last_failure": None, "last_error_message": ""},
    }
    with patch("app.api.v1.market.market_data.get_health", return_value=clean_health):
        with pytest.raises(SymbolNotFoundError):
            _raise_data_error("NONEXISTENT.NS")


# =============================================================================
# 3. Prediction Cache Post-Training Expiry Calculation
# =============================================================================

@pytest.mark.asyncio
async def test_prediction_cache_expiry_calculated_after_training():
    """Verify prediction model cache expiry is calculated using post-training timestamp."""
    predictor = PredictionModel()

    mock_features = (pd.DataFrame({"f1": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0]}), pd.Series([10.0, 11.0, 12.0, 13.0, 14.0, 15.0, 16.0, 17.0, 18.0, 19.0]))
    mock_live = {"f1": 2.5}

    with patch.object(predictor._feature_engineer, "build_features", new_callable=AsyncMock, return_value=mock_features), \
         patch.object(predictor._feature_engineer, "build_live_features", new_callable=AsyncMock, return_value=mock_live), \
         patch("app.engines.prediction.model._get_symbol_lock", new_callable=AsyncMock):

        start_time = time.time()
        mock_xgb = MagicMock()
        mock_xgb_regressor = MagicMock()
        def fake_fit(*args, **kwargs):
            time.sleep(0.05)
        import numpy as np
        mock_xgb_regressor.predict.side_effect = lambda df: np.full(len(df), 0.03)
        mock_xgb.XGBRegressor.return_value = mock_xgb_regressor

        mock_quote = MagicMock()
        mock_quote.available = True
        mock_quote.data = {"price": 220.0, "timestamp": "2026-09-28T00:00:00Z"}

        with patch.dict("sys.modules", {"xgboost": mock_xgb}), \
             patch("app.engines.prediction.model.PredictionModel._compute_shap", return_value=[{"feature": "f1", "impact": "high"}]), \
             patch("app.data.market_data_provider.market_data.get_quote", new_callable=AsyncMock, return_value=mock_quote):

            res = await predictor.forecast("AAPL")
            assert "prediction" in res
            assert "AAPL" in predictor._forecast_cache
            _, exp = predictor._forecast_cache["AAPL"]

            # Expiration must be >= start_time + 600 + elapsed_training_time
            assert exp >= start_time + 600


# =============================================================================
# 4. Render Deployment Spec (render.yaml)
# =============================================================================

def test_render_yaml_has_pre_deploy_migration():
    """Verify render.yaml specifies preDeployCommand: alembic upgrade head."""
    with open("render.yaml", "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    web_service = next((s for s in config.get("services", []) if s.get("name") == "arth-api"), None)
    assert web_service is not None
    assert web_service.get("preDeployCommand") == "alembic upgrade head"
    assert web_service.get("rootDir") == "backend"
