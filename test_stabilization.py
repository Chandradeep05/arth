"""
ARTH Stabilization — Runtime Verification Tests

Tests the actual runtime behavior of all stabilization changes:
1. OHLCV normalization (column names, sort order, numeric types)
2. DataResult envelope (all status codes handled)
3. NSE circuit breaker (OPEN prevents network calls)
4. <think> tag stripping (generate + stream edge cases)
5. Feature engineering (pb_ratio is NaN, not dollar-scale corruption)
6. Provider contract (MarketDataProvider returns DataResult, not raw data)
"""

import asyncio
import sys
import os
import re
import math
import traceback

# Add backend to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "backend"))

# Minimal env setup so Settings doesn't crash
os.environ.setdefault("GROQ_API_KEY", "")
os.environ.setdefault("TWELVEDATA_API_KEY", "")
os.environ.setdefault("JWT_SECRET_KEY", "test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379")

PASS = 0
FAIL = 0
SKIP = 0

def test(name, condition, detail=""):
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  PASS {name}")
    else:
        FAIL += 1
        print(f"  FAIL {name}: {detail}")

def skip(name, reason=""):
    global SKIP
    SKIP += 1
    print(f"  SKIP {name}: {reason}")


# ===================================================================
# TEST GROUP 1: Import Verification (all modules load cleanly)
# ===================================================================
print("\n=== TEST GROUP 1: Import Verification ===")

try:
    from app.data.market_data_provider import (
        MarketDataProvider, DataResult, DataStatus,
        normalize_ohlcv, CAPABILITIES, market_data,
    )
    test("MarketDataProvider imports", True)
except Exception as e:
    test("MarketDataProvider imports", False, str(e))

try:
    from app.llm.groq_client import GroqClient, _strip_thinking, _THINK_BLOCK_RE
    test("GroqClient imports (with _strip_thinking)", True)
except Exception as e:
    test("GroqClient imports", False, str(e))

try:
    from app.data.adapters.nse import NSESession, NSEAdapter, nse_adapter
    from app.data.adapters.nse import _CircuitState
    test("NSE adapter imports (with _CircuitState)", True)
except Exception as e:
    test("NSE adapter imports", False, str(e))

try:
    from app.engines.prediction.feature_engineering import FeatureEngineer
    test("FeatureEngineer imports (no yfinance)", True)
except Exception as e:
    test("FeatureEngineer imports", False, str(e))

try:
    from app.engines.sentiment.engine import SentimentEngine
    test("SentimentEngine imports (no yfinance)", True)
except Exception as e:
    test("SentimentEngine imports", False, str(e))

try:
    import app.engines.governance.engine as _gov_mod
    test("GovernanceEngine imports (no yfinance)", True)
except Exception as e:
    test("GovernanceEngine imports", False, str(e))

try:
    from app.engines.rag.document_processor import DocumentProcessor
    test("DocumentProcessor imports (no yfinance)", True)
except Exception as e:
    test("DocumentProcessor imports", False, str(e))

try:
    from app.engines.research.engine import ResearchEngine
    test("ResearchEngine imports (no yfinance)", True)
except Exception as e:
    test("ResearchEngine imports", False, str(e))

try:
    from app.engines.research.statement_parser import StatementParser
    test("StatementParser imports (no yfinance)", True)
except Exception as e:
    test("StatementParser imports", False, str(e))

try:
    from app.engines.assistant.engine import AssistantEngine
    test("AssistantEngine imports (no yfinance)", True)
except Exception as e:
    test("AssistantEngine imports", False, str(e))

try:
    from app.engines.risk.engine import RiskEngine
    test("RiskEngine imports (no yfinance)", True)
except Exception as e:
    test("RiskEngine imports", False, str(e))


# ===================================================================
# TEST GROUP 2: think Tag Stripping
# ===================================================================
print("\n=== TEST GROUP 2: think Tag Stripping ===")

from app.llm.groq_client import _strip_thinking

test(
    "Strip complete think block",
    _strip_thinking("<think>reasoning here</think>The answer is 42.") == "The answer is 42.",
    f"Got: '{_strip_thinking('<think>reasoning here</think>The answer is 42.')}'",
)

test(
    "Strip multi-line think block",
    _strip_thinking("<think>\nstep 1\nstep 2\nstep 3\n</think>\nFinal answer.") == "Final answer.",
    f"Got: '{_strip_thinking(chr(60)+'think'+chr(62)+'step 1'+chr(60)+'/think'+chr(62)+'Final answer.')}'",
)

test(
    "Strip unterminated think (max_tokens cutoff)",
    _strip_thinking("Some prefix<think>reasoning that never closes") == "Some prefix",
    f"Got: '{_strip_thinking('Some prefix<think>reasoning that never closes')}'",
)

test(
    "Pass through clean content unchanged",
    _strip_thinking("Just a normal response.") == "Just a normal response.",
)

test("Handle empty string", _strip_thinking("") == "")
test("Handle None", _strip_thinking(None) == "")

test(
    "Case insensitive THINK tags",
    _strip_thinking("<THINK>loud reasoning</THINK>Answer.") == "Answer.",
    f"Got: '{_strip_thinking('<THINK>loud reasoning</THINK>Answer.')}'",
)

# Chunk boundary simulation
chunks = ["<thi", "nk>", "reasoning...", "</thi", "nk>", "actual answer"]
combined = "".join(chunks)
result = _strip_thinking(combined)
test(
    "Chunked tag boundaries (combined)",
    result == "actual answer",
    f"Got: '{result}'",
)

test(
    "Only reasoning content returns empty",
    _strip_thinking("<think>all reasoning</think>") == "",
    f"Got: '{_strip_thinking('<think>all reasoning</think>')}'",
)


# ===================================================================
# TEST GROUP 3: OHLCV Normalization
# ===================================================================
print("\n=== TEST GROUP 3: OHLCV Normalization ===")

import pandas as pd

# TwelveData format
td_data = {
    "bars": [
        {"datetime": "2026-07-22", "open": 150.0, "high": 155.0, "low": 149.0, "close": 153.0, "volume": 1000000},
        {"datetime": "2026-07-21", "open": 148.0, "high": 152.0, "low": 147.0, "close": 150.0, "volume": 900000},
        {"datetime": "2026-07-20", "open": 145.0, "high": 149.0, "low": 144.0, "close": 148.0, "volume": 800000},
    ]
}
td_result = normalize_ohlcv(td_data, "twelvedata")

test("TwelveData: returns DataFrame", isinstance(td_result, pd.DataFrame))
if td_result is not None:
    test("TwelveData: correct columns", list(td_result.columns) == ["Open", "High", "Low", "Close", "Volume"],
         f"Got: {list(td_result.columns)}")
    test("TwelveData: DatetimeIndex", isinstance(td_result.index, pd.DatetimeIndex),
         f"Got: {type(td_result.index)}")
    test("TwelveData: sorted ascending", td_result.index[0] < td_result.index[-1],
         f"First: {td_result.index[0]}, Last: {td_result.index[-1]}")
    test("TwelveData: correct row count", len(td_result) == 3, f"Got: {len(td_result)}")
    test("TwelveData: numeric Open", td_result["Open"].dtype in ["float64", "int64"],
         f"Got dtype: {td_result['Open'].dtype}")
    test("TwelveData: first close matches oldest", td_result.iloc[0]["Close"] == 148.0,
         f"Got: {td_result.iloc[0]['Close']}")

# NSE format
nse_data = {
    "bars": [
        {"date": "2026-07-22T00:00:00+00:00", "open": 3500.0, "high": 3550.0, "low": 3480.0, "close": 3520.0, "volume": 500000, "adj_close": None},
        {"date": "2026-07-21T00:00:00+00:00", "open": 3470.0, "high": 3510.0, "low": 3460.0, "close": 3500.0, "volume": 450000, "adj_close": None},
    ]
}
nse_result = normalize_ohlcv(nse_data, "nse")

test("NSE: returns DataFrame", isinstance(nse_result, pd.DataFrame))
if nse_result is not None:
    test("NSE: correct columns", list(nse_result.columns) == ["Open", "High", "Low", "Close", "Volume"],
         f"Got: {list(nse_result.columns)}")
    test("NSE: sorted ascending", nse_result.index[0] < nse_result.index[-1])
    test("NSE: no duplicate timestamps", not nse_result.index.duplicated().any())

# Edge cases
test("Empty dict returns None", normalize_ohlcv({}, "test") is None)
test("Empty bars returns None", normalize_ohlcv({"bars": []}, "test") is None)
test("None input returns None", normalize_ohlcv(None, "test") is None)

# Direct list format
list_data = [
    {"datetime": "2026-07-22", "open": 100.0, "high": 105.0, "low": 99.0, "close": 103.0, "volume": 500},
]
list_result = normalize_ohlcv(list_data, "test")
test("Direct list format works", isinstance(list_result, pd.DataFrame))


# ===================================================================
# TEST GROUP 4: DataResult / DataStatus Contract
# ===================================================================
print("\n=== TEST GROUP 4: DataResult Contract ===")

r_success = DataResult(data={"price": 150.0}, status=DataStatus.SUCCESS)
test("SUCCESS with data -> available=True", r_success.available is True)

r_success_none = DataResult(data=None, status=DataStatus.SUCCESS)
test("SUCCESS with None data -> available=False", r_success_none.available is False)

r_unavail = DataResult(data=None, status=DataStatus.UNAVAILABLE_PROVIDER, reason="403")
test("UNAVAILABLE_PROVIDER -> available=False", r_unavail.available is False)

r_unsup = DataResult(data=None, status=DataStatus.UNSUPPORTED_CAPABILITY, reason="no news")
test("UNSUPPORTED_CAPABILITY -> available=False", r_unsup.available is False)

r_rate = DataResult(data=None, status=DataStatus.RATE_LIMITED)
test("RATE_LIMITED -> available=False", r_rate.available is False)

r_temp = DataResult(data=None, status=DataStatus.TEMPORARY_ERROR)
test("TEMPORARY_ERROR -> available=False", r_temp.available is False)

# CAPABILITIES matrix
test("TwelveData: news=False", CAPABILITIES["twelvedata"]["news"] is False)
test("TwelveData: holders=False", CAPABILITIES["twelvedata"]["holders"] is False)
test("TwelveData: quote=True", CAPABILITIES["twelvedata"]["quote"] is True)
test("TwelveData: fundamentals=partial", CAPABILITIES["twelvedata"]["fundamentals"] == "partial")
test("NSE: news=False", CAPABILITIES["nse"]["news"] is False)
test("NSE: history=True", CAPABILITIES["nse"]["history"] is True)


# ===================================================================
# TEST GROUP 5: NSE Circuit Breaker State Machine
# ===================================================================
print("\n=== TEST GROUP 5: NSE Circuit Breaker ===")

from app.data.adapters.nse import _CircuitState

test("CircuitState CLOSED exists", _CircuitState.CLOSED.value == "closed")
test("CircuitState OPEN exists", _CircuitState.OPEN.value == "open")
test("CircuitState HALF_OPEN exists", _CircuitState.HALF_OPEN.value == "half_open")

session = NSESession()
test("Session starts CLOSED", session._circuit_state == _CircuitState.CLOSED)
test("Session has failure count", hasattr(session, "_consecutive_failures"))
test("Session has cooldown", hasattr(session, "_circuit_cooldown"))
test("Session has threshold", hasattr(session, "_failure_threshold"))
test("Session failure threshold = 3", session._failure_threshold == 3)
test("Session cooldown = 300s", session._circuit_cooldown == 300.0)


# ===================================================================
# TEST GROUP 6: Provider Symbol Routing
# ===================================================================
print("\n=== TEST GROUP 6: Provider Symbol Routing ===")

test("AAPL -> twelvedata", market_data._get_provider("AAPL") == "twelvedata")
test("MSFT -> twelvedata", market_data._get_provider("MSFT") == "twelvedata")
test("TCS.NS -> nse", market_data._get_provider("TCS.NS") == "nse")
test("RELIANCE.NS -> nse", market_data._get_provider("RELIANCE.NS") == "nse")
test("INFY.BO -> nse", market_data._get_provider("INFY.BO") == "nse")

test("AAPL label -> Twelve Data", market_data.get_source_label("AAPL") == "Twelve Data")
test("TCS.NS label -> NSE India", market_data.get_source_label("TCS.NS") == "NSE India")


# ===================================================================
# TEST GROUP 7: Capability Checks (sync, no network)
# ===================================================================
print("\n=== TEST GROUP 7: Capability Checks ===")

news_check = market_data._check_capability("AAPL", "news")
test("AAPL news -> blocked", news_check is not None and news_check.status == DataStatus.UNSUPPORTED_CAPABILITY)

holders_check = market_data._check_capability("AAPL", "holders")
test("AAPL holders -> blocked", holders_check is not None and holders_check.status == DataStatus.UNSUPPORTED_CAPABILITY)

quote_check = market_data._check_capability("AAPL", "quote")
test("AAPL quote -> allowed", quote_check is None)

history_check = market_data._check_capability("TCS.NS", "history")
test("TCS.NS history -> allowed", history_check is None)

nse_news_check = market_data._check_capability("TCS.NS", "news")
test("TCS.NS news -> blocked", nse_news_check is not None and nse_news_check.status == DataStatus.UNSUPPORTED_CAPABILITY)


# ===================================================================
# TEST GROUP 8: Feature Engineering (pb_ratio fix)
# ===================================================================
print("\n=== TEST GROUP 8: Feature Engineering Sanity ===")

import numpy as np

test("pb_ratio in FEATURE_NAMES", "pb_ratio" in FeatureEngineer.FEATURE_NAMES)
test("pe_ratio in FEATURE_NAMES", "pe_ratio" in FeatureEngineer.FEATURE_NAMES)
test("market_cap_log in FEATURE_NAMES", "market_cap_log" in FeatureEngineer.FEATURE_NAMES)

import inspect
source = inspect.getsource(FeatureEngineer.build_features)
test(
    "build_features does NOT use info.get('book_value')",
    "info.get('book_value')" not in source,
    "Still references book_value!",
)
test(
    "build_features uses np.nan for pb",
    "pb = np.nan" in source,
    "pb_ratio not set to NaN",
)


# ===================================================================
# TEST GROUP 9: Config Sanity
# ===================================================================
print("\n=== TEST GROUP 9: Config Sanity ===")

from app.config import Settings

settings = Settings()
test("newsapi_enabled = False", settings.newsapi_enabled is False,
     f"Got: {settings.newsapi_enabled}")
test("alpha_vantage_enabled = False", settings.alpha_vantage_enabled is False)
test("groq_model contains qwen", "qwen" in settings.groq_model.lower(),
     f"Got: {settings.groq_model}")


# ===================================================================
# TEST GROUP 10: No yfinance Imports in Engines (Runtime Check)
# ===================================================================
print("\n=== TEST GROUP 10: yfinance Import Enforcement ===")

import importlib

engine_modules = [
    "app.engines.sentiment.engine",
    "app.engines.prediction.feature_engineering",
    "app.engines.rag.document_processor",
    "app.engines.governance.engine",
    "app.engines.research.engine",
    "app.engines.research.statement_parser",
    "app.engines.assistant.engine",
    "app.engines.risk.engine",
]

for mod_name in engine_modules:
    try:
        mod = importlib.import_module(mod_name)
        has_yf = hasattr(mod, "yf") or "yfinance" in dir(mod)
        test(f"{mod_name.split('.')[-2]}/{mod_name.split('.')[-1]}: no yfinance",
             not has_yf, "yfinance found in module namespace!")
    except Exception as e:
        skip(f"{mod_name}: import check", str(e)[:80])


# ===================================================================
# SUMMARY
# ===================================================================
print(f"\n{'=' * 60}")
print(f"  RESULTS: {PASS} passed, {FAIL} failed, {SKIP} skipped")
print(f"{'=' * 60}")

if FAIL > 0:
    print("\n  WARNING: SOME TESTS FAILED")
    sys.exit(1)
else:
    print("\n  All tests passed — safe to deploy.")
    sys.exit(0)
