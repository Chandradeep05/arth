"""
Unit tests for ARTH Milestone M2.5: Data Foundation Remediation.

Validates:
1. Unified OHLCV Normalization parity between DataFrames, dicts, and lists.
2. Physical OHLC consistency validation (High >= Low, High >= Open, High >= Close, etc.).
3. Price positivity and non-negative volume filtering.
4. Timestamp sorting and deduplication.
5. Provider adjustment metadata recording in DataFrame attributes.
6. Indian index batch routing in market data provider.
7. Feature engineering abstention (no silent zero imputation on missing/unwarmed indicators).
8. Train/serve lookback parity (1y / 250+ bars) and scale-invariant feature definitions.
"""

from __future__ import annotations

import datetime
from unittest.mock import AsyncMock, MagicMock, patch
import numpy as np
import pandas as pd
import pytest

from app.data.market_data_provider import (
    DataResult,
    DataStatus,
    MarketDataProvider,
    normalize_ohlcv,
)
from app.engines.prediction.feature_engineering import (
    FEATURE_NAMES,
    FEATURE_NAMES_V1,
    FEATURE_NAMES_V2,
    FeatureEngineer,
)


# ─────────────────────────────────────────────────────────────────────────────
# 1. Unified OHLCV Normalization Tests
# ─────────────────────────────────────────────────────────────────────────────

def _make_sample_raw_bars():
    base = datetime.datetime(2026, 1, 1, 9, 30)
    bars = []
    for i in range(10):
        t = (base + datetime.timedelta(days=i)).isoformat()
        bars.append({
            "timestamp": t,
            "open": 100.0 + i,
            "high": 105.0 + i,
            "low": 95.0 + i,
            "close": 102.0 + i,
            "volume": 1000.0 + i * 50,
        })
    return bars


def test_normalize_ohlcv_dataframe_list_parity():
    """DataFrames and lists of dicts must pass through identical normalization and yield identical output."""
    raw_list = _make_sample_raw_bars()
    raw_df = pd.DataFrame(raw_list)

    df_from_list = normalize_ohlcv(raw_list, source="test", adjustment_mode="SPLIT_ADJUSTED")
    df_from_df = normalize_ohlcv(raw_df, source="test", adjustment_mode="SPLIT_ADJUSTED")

    assert df_from_list is not None
    assert df_from_df is not None
    pd.testing.assert_frame_equal(df_from_list, df_from_df)
    assert df_from_list.attrs.get("adjustment_mode") == "SPLIT_ADJUSTED"
    assert df_from_df.attrs.get("adjustment_mode") == "SPLIT_ADJUSTED"
    assert df_from_list.attrs.get("source") == "test"


def test_normalize_ohlcv_physical_violations_filtered():
    """Physical OHLC consistency violations (High < Low, High < Open, Low > Close) must be filtered out."""
    # High < Low -> invalid, returns None when all rows are invalid
    bad_hl = [{
        "timestamp": "2026-01-01T10:00:00",
        "open": 100.0,
        "high": 90.0,
        "low": 95.0,
        "close": 92.0,
        "volume": 100.0,
    }]
    assert normalize_ohlcv(bad_hl) is None

    # High < Open -> invalid
    bad_ho = [{
        "timestamp": "2026-01-01T10:00:00",
        "open": 110.0,
        "high": 105.0,
        "low": 95.0,
        "close": 100.0,
        "volume": 100.0,
    }]
    assert normalize_ohlcv(bad_ho) is None

    # Low > Close -> invalid
    bad_lc = [{
        "timestamp": "2026-01-01T10:00:00",
        "open": 100.0,
        "high": 105.0,
        "low": 95.0,
        "close": 90.0,
        "volume": 100.0,
    }]
    assert normalize_ohlcv(bad_lc) is None


def test_normalize_ohlcv_negative_price_and_volume():
    """Negative prices or negative volume must be rejected (returning None if all rows invalid)."""
    bad_price = [{
        "timestamp": "2026-01-01T10:00:00",
        "open": -10.0,
        "high": 10.0,
        "low": -20.0,
        "close": 5.0,
        "volume": 100.0,
    }]
    assert normalize_ohlcv(bad_price) is None

    bad_vol = [{
        "timestamp": "2026-01-01T10:00:00",
        "open": 10.0,
        "high": 15.0,
        "low": 8.0,
        "close": 12.0,
        "volume": -50.0,
    }]
    assert normalize_ohlcv(bad_vol) is None


def test_normalize_ohlcv_sorting_and_deduplication():
    """Unordered bars must be sorted chronologically and duplicates deduplicated."""
    t1 = "2026-01-01T10:00:00"
    t2 = "2026-01-02T10:00:00"
    t3 = "2026-01-03T10:00:00"

    bars = [
        {"timestamp": t2, "open": 102.0, "high": 105.0, "low": 98.0, "close": 101.0, "volume": 100.0},
        {"timestamp": t1, "open": 100.0, "high": 103.0, "low": 97.0, "close": 99.0, "volume": 100.0},
        # Duplicate timestamp t2 with newer close and volume
        {"timestamp": t2, "open": 102.0, "high": 106.0, "low": 98.0, "close": 103.0, "volume": 150.0},
        {"timestamp": t3, "open": 104.0, "high": 107.0, "low": 101.0, "close": 105.0, "volume": 120.0},
    ]

    norm = normalize_ohlcv(bars)
    assert norm is not None
    assert len(norm) == 3
    # Ascending sort
    assert norm.index[0] == pd.to_datetime(t1, utc=True)
    assert norm.index[1] == pd.to_datetime(t2, utc=True)
    assert norm.index[2] == pd.to_datetime(t3, utc=True)
    # Deduplication kept last
    assert norm["Close"].iloc[1] == 103.0
    assert norm["Volume"].iloc[1] == 150.0


# ─────────────────────────────────────────────────────────────────────────────
# 2. Indian Index Batch Routing
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_batch_quotes_indian_index_routing():
    """Verify Indian indices (^NSEI, ^BSESN) route to Indian provider and not TwelveData."""
    provider = MarketDataProvider()

    mock_upstox = AsyncMock()
    mock_upstox.get_quote = AsyncMock(return_value={"price": 25000.0, "change": 100.0, "change_percent": 0.4})

    mock_twelve = AsyncMock()
    mock_twelve.get_batch_quotes = AsyncMock(return_value=[{"symbol": "AAPL", "price": 220.0}])

    provider._twelve = mock_twelve
    with patch.object(provider, "_get_upstox", return_value=mock_upstox):
        quotes = await provider.get_batch_quotes(["^NSEI", "RELIANCE.NS", "AAPL", "^GSPC"])

        # Upstox should be called for ^NSEI and RELIANCE.NS
        upstox_symbols = [call.args[0] for call in mock_upstox.get_quote.call_args_list]
        assert "^NSEI" in upstox_symbols
        assert "RELIANCE.NS" in upstox_symbols

        # TwelveData should be called for US symbols (AAPL, ^GSPC)
        td_symbols = mock_twelve.get_batch_quotes.call_args[0][0]
        assert "AAPL" in td_symbols
        assert "^GSPC" in td_symbols
        assert "^NSEI" not in td_symbols


# ─────────────────────────────────────────────────────────────────────────────
# 3. Feature Engineering Parity & Abstention
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_feature_engineering_abstention_on_unwarmed_indicators():
    """When indicator series cannot be computed, build_live_features must raise ValueError (no silent 0.0)."""
    # Create insufficient length data (e.g. only 20 bars, while MACD requires 35+)
    insufficient_bars = [
        {
            "Open": 100.0 + i,
            "High": 105.0 + i,
            "Low": 95.0 + i,
            "Close": 102.0 + i,
            "Volume": 1000.0,
        }
        for i in range(20)
    ]
    df = pd.DataFrame(insufficient_bars)

    mock_result = DataResult(
        data=df,
        status=DataStatus.SUCCESS,
        source="test",
    )

    fe = FeatureEngineer()
    with patch("app.engines.prediction.feature_engineering.market_data.get_history", AsyncMock(return_value=mock_result)):
        with pytest.raises(ValueError, match="need 35\\+ daily bars for indicator warm-up"):
            await fe.build_live_features("TEST")


@pytest.mark.asyncio
async def test_feature_engineering_lookback_parity():
    """Feature engineering build_live_features requests 1y lookback (~252 bars) for warm-up parity."""
    # Create 260 valid bars
    bars = [
        {
            "Open": 100.0 + i * 0.1,
            "High": 105.0 + i * 0.1,
            "Low": 95.0 + i * 0.1,
            "Close": 102.0 + i * 0.1,
            "Volume": 1000.0 + i * 10,
        }
        for i in range(260)
    ]
    df = pd.DataFrame(bars)
    dates = pd.date_range("2025-01-01", periods=260, freq="B")
    df.index = dates

    mock_result = DataResult(
        data=df,
        status=DataStatus.SUCCESS,
        source="test",
    )

    fe = FeatureEngineer()
    mock_history = AsyncMock(return_value=mock_result)
    with patch("app.engines.prediction.feature_engineering.market_data.get_history", mock_history):
        feats = await fe.build_live_features("RELIANCE.NS")
        # Verify get_history was called with period="1y"
        mock_history.assert_awaited_once_with("RELIANCE.NS", period="1y", interval="1d")
        assert "rsi_14" in feats
        assert "macd_signal" in feats
        assert "macd_signal_norm" in feats
        assert "bb_position" in feats


def test_feature_names_v2_scale_invariance():
    """FEATURE_NAMES_V2 includes scale-invariant macd_signal_norm."""
    assert "macd_signal_norm" in FEATURE_NAMES_V2
    assert "macd_signal" in FEATURE_NAMES_V1
    assert "macd_signal_norm" not in FEATURE_NAMES_V1
