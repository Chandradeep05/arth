"""
Behavioral tests for V6 fixes.

Tests instantiate real engine/adapter classes and verify actual calculation,
normalization, and routing behavior using mock data. No source-string scraping.
"""

import pytest
import pandas as pd
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone

from app.engines.risk.engine import RiskEngine
from app.engines.research.statement_parser import StatementParser
from app.data.adapters.upstox import UpstoxAdapter
from app.data.adapters.yahoo import HybridAdapter


# =============================================================================
# 1. Risk Engine Composite Score Tests
# =============================================================================

@pytest.mark.asyncio
async def test_risk_composite_excludes_unavailable_dimensions():
    """
    When one or more dimensions are unavailable, the composite score must ONLY
    average the available dimensions with re-normalized weights.
    It must NOT silently include default 50.0 scores from unavailable dimensions.
    """
    engine = RiskEngine()

    with patch("app.data.cache.CacheManager.get_or_fetch", new_callable=AsyncMock, return_value=None), \
         patch.object(engine, "_compute_volatility_risk", return_value=(50.0, [], False)), \
         patch.object(engine, "_compute_liquidity_risk", return_value=(20.0, ["High volume"], True)), \
         patch.object(engine, "_compute_financial_risk", return_value=(50.0, [], False)):
        
        result = await engine.compute_risk("TEST")

        assert result["available"] is True
        # Since liquidity (20.0) is the ONLY available dimension,
        # the re-normalized composite score MUST be exactly 20.0, NOT (50*0.35 + 20*0.25 + 50*0.40 = 42.5)
        assert result["composite_score"] == 20.0
        assert result["confidence"] == pytest.approx(33.3, abs=0.1)


@pytest.mark.asyncio
async def test_risk_composite_all_unavailable_returns_none():
    """When all dimensions are unavailable, composite_score must be None."""
    engine = RiskEngine()

    with patch("app.data.cache.CacheManager.get_or_fetch", new_callable=AsyncMock, return_value=None), \
         patch.object(engine, "_compute_volatility_risk", return_value=(50.0, [], False)), \
         patch.object(engine, "_compute_liquidity_risk", return_value=(50.0, [], False)), \
         patch.object(engine, "_compute_financial_risk", return_value=(50.0, [], False)):
        
        result = await engine.compute_risk("EMPTY")

        assert result["available"] is False
        assert result["composite_score"] is None
        assert result["composite_label"] == "Insufficient data"
        assert result["confidence"] == 0.0


@pytest.mark.asyncio
async def test_risk_composite_all_available_normal_weighting():
    """When all 3 dimensions are available, weights (0.35, 0.25, 0.40) apply normally."""
    engine = RiskEngine()

    # vol=40 (wt 0.35 -> 14), liq=20 (wt 0.25 -> 5), fin=60 (wt 0.40 -> 24) -> sum = 43.0
    with patch("app.data.cache.CacheManager.get_or_fetch", new_callable=AsyncMock, return_value=None), \
         patch.object(engine, "_compute_volatility_risk", return_value=(40.0, ["Normal vol"], True)), \
         patch.object(engine, "_compute_liquidity_risk", return_value=(20.0, ["Good liq"], True)), \
         patch.object(engine, "_compute_financial_risk", return_value=(60.0, ["Mod debt"], True)):
        
        result = await engine.compute_risk("FULL")

        assert result["available"] is True
        assert result["composite_score"] == 43.0
        assert result["confidence"] == 100.0


# =============================================================================
# 2. Statement Parser Health Score Key Names Tests
# =============================================================================

@pytest.mark.asyncio
async def test_health_score_with_actual_ratio_keys():
    """
    Test that StatementParser.get_health_score correctly detects data when
    ratios contain the canonical keys ('roe', 'roa', 'free_cash_flow').
    """
    parser = StatementParser()

    # Mock get_ratios returning data for roe, roa, and free_cash_flow
    mock_ratios = {
        "ratios": {
            "roe": {"value": 0.18, "previous": 0.15, "change": 0.03, "direction": "up"},
            "roa": {"value": 0.08, "previous": 0.07, "change": 0.01, "direction": "up"},
            "free_cash_flow": {"value": 5000000.0, "previous": 4000000.0, "change": 1000000.0, "direction": "up"},
            "profit_margin": None,
            "debt_to_equity": None,
            "current_ratio": None,
            "operating_margin": None,
            "revenue_growth": None,
        }
    }

    with patch.object(parser, "get_ratios", new_callable=AsyncMock, return_value=mock_ratios):
        score_data = await parser.get_health_score("TEST.NS")
        # Since roe, roa, free_cash_flow have data, available MUST be True
        assert score_data["available"] is True
        assert score_data["total_score"] is not None
        assert score_data["total_score"] > 0


@pytest.mark.asyncio
async def test_health_score_all_missing_returns_unavailable():
    """When all canonical ratio keys are None, get_health_score must return available=False."""
    parser = StatementParser()

    mock_ratios = {
        "ratios": {
            "roe": None,
            "roa": None,
            "free_cash_flow": None,
            "profit_margin": None,
            "debt_to_equity": None,
            "current_ratio": None,
            "operating_margin": None,
            "revenue_growth": None,
        }
    }

    with patch.object(parser, "get_ratios", new_callable=AsyncMock, return_value=mock_ratios):
        score_data = await parser.get_health_score("EMPTY.NS")
        assert score_data["available"] is False
        assert score_data["total_score"] is None
        assert score_data["label"] == "Insufficient data"


# =============================================================================
# 3. Upstox Adapter Data Normalization Tests
# =============================================================================

def test_upstox_parse_key_ratios():
    """Test Upstox key-ratios parsing from Upstox array structure into canonical metrics."""
    adapter = UpstoxAdapter()

    sample_api_response = {
        "data": [
            {"name": "P/E", "company_value": "24.15", "sector_value": "18.46"},
            {"name": "P/B", "company_value": "3.50", "sector_value": "2.80"},
            {"name": "ROE", "company_value": "16.8%", "sector_value": "12.0%"},
            {"name": "ROA", "company_value": "8.4%", "sector_value": "6.0%"},
            {"name": "Debt/Equity", "company_value": "0.35", "sector_value": "0.80"},
            {"name": "Current Ratio", "company_value": "1.85", "sector_value": "1.50"},
            {"name": "Dividend Yield", "company_value": "1.2%", "sector_value": "1.5%"},
        ]
    }

    metrics = adapter._parse_key_ratios(sample_api_response)
    assert metrics["pe_ratio"] == 24.15
    assert metrics["pb_ratio"] == 3.50
    assert metrics["roe"] == 16.8  # Cleaned float from "16.8%"
    assert metrics["roa"] == 8.4   # Cleaned float from "8.4%"
    assert metrics["debt_to_equity"] == 0.35
    assert metrics["current_ratio"] == 1.85
    assert metrics["dividend_yield"] == 1.2


def test_upstox_normalize_financial_statements():
    """
    Test that Upstox financial statements are properly normalized into the
    structure StatementParser expects: {"annual": [{"period": str, "items": {...}}], "quarterly": []}.
    """
    adapter = UpstoxAdapter()

    # Sample Upstox income statement payload
    sample_income_stmt = {
        "data": {
            "type": "consolidated",
            "time_period": "yearly",
            "income_statement": [
                {
                    "year": "2024",
                    "Total Revenue": 900000.0,
                    "Operating Income": 150000.0,
                    "Net Income": 110000.0,
                },
                {
                    "year": "2023",
                    "Total Revenue": 800000.0,
                    "Operating Income": 130000.0,
                    "Net Income": 95000.0,
                },
            ]
        }
    }

    normalized = adapter._normalize_statement(sample_income_stmt)
    assert "annual" in normalized
    assert "quarterly" in normalized
    assert len(normalized["annual"]) == 2
    assert normalized["annual"][0]["period"] == "2024"
    assert normalized["annual"][0]["items"]["Total Revenue"] == 900000.0
    assert normalized["annual"][1]["period"] == "2023"
    assert normalized["annual"][1]["items"]["Net Income"] == 95000.0


def test_upstox_normalize_empty_or_none_statement():
    """Test that missing or None statement response safely returns empty lists without error."""
    adapter = UpstoxAdapter()

    normalized_none = adapter._normalize_statement(None)
    assert normalized_none == {"annual": [], "quarterly": []}

    normalized_empty = adapter._normalize_statement({})
    assert normalized_empty == {"annual": [], "quarterly": []}


@pytest.mark.asyncio
async def test_upstox_news_canonical_field_names():
    """
    Test that get_news returns canonical fields expected by DocumentProcessor:
    'title', 'link', 'publisher', 'providerPublishTime'.
    """
    adapter = UpstoxAdapter()

    mock_news_response = {
        "data": {
            "NSE_EQ|INE002A01018": [
                {
                    "headline": "Reliance Q3 Net Profit Surges 12%",
                    "summary": "Reliance Industries reported strong performance in energy and retail.",
                    "article_link": "https://upstox.com/news/reliance-q3",
                    "timestamp": 1708900000000,
                    "thumbnail": "https://upstox.com/images/thumb.jpg",
                }
            ]
        }
    }

    with patch.object(adapter, "_get_instrument_key", new_callable=AsyncMock, return_value="NSE_EQ|INE002A01018"), \
         patch.object(adapter, "_throttled_request", new_callable=AsyncMock, return_value=mock_news_response):

        articles = await adapter.get_news("RELIANCE.NS")
        assert articles is not None
        assert len(articles) == 1
        art = articles[0]

        # Check canonical fields required by DocumentProcessor
        assert art["title"] == "Reliance Q3 Net Profit Surges 12%"
        assert art["link"] == "https://upstox.com/news/reliance-q3"
        assert art["publisher"] == "Upstox News"
        assert art["providerPublishTime"] == 1708900000.0
        assert art["summary"] == "Reliance Industries reported strong performance in energy and retail."


# =============================================================================
# 4. Hybrid Adapter Routing Tests
# =============================================================================

@pytest.mark.asyncio
async def test_hybrid_adapter_routes_indian_stocks_to_upstox():
    """Test that HybridAdapter queries Upstox first for Indian stocks (.NS / .BO) when enabled."""
    hybrid = HybridAdapter()

    mock_upstox = MagicMock()
    mock_upstox.get_quote = AsyncMock(return_value={
        "symbol": "TCS.NS",
        "price": 3850.0,
        "change": 45.0,
        "change_percent": 1.18,
        "currency": "INR",
        "exchange": "NSE",
    })

    with patch.object(hybrid, "_get_upstox", return_value=mock_upstox):
        quote = await hybrid.get_quote("TCS.NS")

        assert quote is not None
        assert quote["price"] == 3850.0
        assert quote["currency"] == "INR"
        mock_upstox.get_quote.assert_awaited_once_with("TCS.NS")


@pytest.mark.asyncio
async def test_hybrid_adapter_routes_us_stocks_to_twelvedata():
    """Test that HybridAdapter routes US symbols (AAPL, MSFT) to TwelveData."""
    hybrid = HybridAdapter()

    mock_td = MagicMock()
    mock_td.get_quote = AsyncMock(return_value={
        "symbol": "AAPL",
        "price": 220.50,
        "change": 2.50,
        "change_percent": 1.15,
        "currency": "USD",
    })

    with patch.object(hybrid, "_get_twelve", return_value=mock_td):
        quote = await hybrid.get_quote("AAPL")

        assert quote is not None
        assert quote["symbol"] == "AAPL"
        assert quote["price"] == 220.50
        mock_td.get_quote.assert_awaited_once_with("AAPL")
