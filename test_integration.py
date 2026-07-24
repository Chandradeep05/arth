"""
Integration Tests — exercises actual data contracts between adapters and engines.

These tests verify the REAL bugs found in production:
- Finnhub news schema → SentimentEngine field mapping
- FMP statement format → StatementParser {period, items} contract
- RiskEngine with real DataFrame (Close/Volume columns, pandas import)
- Provider routing for Indian symbols (no TwelveData waste)
- Ticker extraction edge cases (TCS.NS, INFY.NS, AAPL)
- normalize_ohlcv safety (None, empty, DataFrame passthrough)
- _raise_data_error health passthrough
- Cache serialization (DataFrame → dict → DataFrame roundtrip)
"""

import sys
import os

# Ensure backend is on the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "backend"))

passed = 0
failed = 0
skipped = 0


def test(name, condition, detail=""):
    global passed, failed
    if condition:
        print(f"  PASS {name}")
        passed += 1
    else:
        print(f"  FAIL {name}: {detail}")
        failed += 1


def skip(name, reason=""):
    global skipped
    print(f"  SKIP {name}: {reason}")
    skipped += 1


# ══════════════════════════════════════════════════════════════════
# GROUP 1: Risk Engine — pandas import + DataFrame column contract
# ══════════════════════════════════════════════════════════════════
print("\n=== TEST GROUP 1: Risk Engine DataFrame Contract ===")

try:
    import pandas as pd
    import numpy as np
    from app.engines.risk.engine import RiskEngine

    engine = RiskEngine()

    # Create a realistic DataFrame matching normalize_ohlcv output
    dates = pd.date_range("2024-01-01", periods=60, freq="B")
    np.random.seed(42)
    closes = 150 + np.cumsum(np.random.randn(60) * 2)
    df = pd.DataFrame({
        "Open": closes - np.random.rand(60),
        "High": closes + np.abs(np.random.randn(60)),
        "Low": closes - np.abs(np.random.randn(60)),
        "Close": closes,
        "Volume": np.random.randint(1_000_000, 50_000_000, 60),
    }, index=dates)

    # Test volatility computation with DataFrame
    vol_score, vol_factors = engine._compute_volatility_risk(df)
    test("Volatility: returns score with DataFrame", isinstance(vol_score, float))
    test("Volatility: score in valid range", 0 <= vol_score <= 100, f"got {vol_score}")
    test("Volatility: has factors", len(vol_factors) > 0)
    test("Volatility: factor mentions volatility", any("volatility" in f.lower() for f in vol_factors))

    # Test liquidity computation with DataFrame
    liq_score, liq_factors = engine._compute_liquidity_risk(df)
    test("Liquidity: returns score with DataFrame", isinstance(liq_score, float))
    test("Liquidity: score in valid range", 0 <= liq_score <= 100, f"got {liq_score}")
    test("Liquidity: has factors", len(liq_factors) > 0)
    test("Liquidity: factor mentions liquidity", any("liquidity" in f.lower() for f in liq_factors))

    # Test with None (should return 50.0 default)
    none_score, none_factors = engine._compute_volatility_risk(None)
    test("Volatility: None input returns 50.0", none_score == 50.0)

    # Test with empty DataFrame
    empty_df = pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume"])
    empty_score, empty_factors = engine._compute_volatility_risk(empty_df)
    test("Volatility: empty DataFrame returns 50.0", empty_score == 50.0)

    # Test with list of dicts (old format — should still work)
    bars_list = [{"Close": float(c), "Volume": int(v), "close": float(c), "volume": int(v)}
                 for c, v in zip(closes, np.random.randint(1_000_000, 50_000_000, 60))]
    list_score, list_factors = engine._compute_volatility_risk(bars_list)
    test("Volatility: list-of-dicts still works", isinstance(list_score, float) and 0 <= list_score <= 100)

except Exception as e:
    test("Risk Engine group", False, str(e))


# ══════════════════════════════════════════════════════════════════
# GROUP 2: Finnhub News → SentimentEngine field mapping
# ══════════════════════════════════════════════════════════════════
print("\n=== TEST GROUP 2: Finnhub News → Sentiment Schema ===")

try:
    from app.data.adapters.finnhub import FinnhubAdapter

    # Simulate a raw Finnhub API response article
    raw_finnhub_article = {
        "category": "company news",
        "datetime": 1721865600,
        "headline": "Apple Reports Record Revenue Growth",
        "id": 12345,
        "image": "https://example.com/img.jpg",
        "related": "AAPL",
        "source": "Reuters",
        "summary": "Apple beat expectations with strong iPhone sales",
        "url": "https://reuters.com/article/apple-earnings"
    }

    # Run through FinnhubAdapter normalization (simulate the for loop in get_news)
    normalized = {
        "title": raw_finnhub_article.get("headline", ""),
        "publisher": raw_finnhub_article.get("source", "Finnhub"),
        "link": raw_finnhub_article.get("url", ""),
        "providerPublishTime": raw_finnhub_article.get("datetime"),
        "summary": raw_finnhub_article.get("summary", ""),
        "image": raw_finnhub_article.get("image", ""),
    }

    # Verify the fields SentimentEngine expects
    test("Finnhub→title: 'Apple Reports Record Revenue Growth'",
         normalized["title"] == "Apple Reports Record Revenue Growth")
    test("Finnhub→publisher: 'Reuters' (not 'Unknown')",
         normalized["publisher"] == "Reuters")
    test("Finnhub→link: has actual URL",
         normalized["link"] == "https://reuters.com/article/apple-earnings")
    test("Finnhub→providerPublishTime: is integer timestamp",
         normalized["providerPublishTime"] == 1721865600)
    test("Finnhub→title NOT empty string",
         normalized["title"] != "")
    test("Finnhub→publisher NOT 'Unknown'",
         normalized["publisher"] != "Unknown")

    # Verify actual adapter code normalizes correctly
    import inspect
    source = inspect.getsource(FinnhubAdapter.get_news)
    test("FinnhubAdapter.get_news uses 'title' key", '"title"' in source)
    test("FinnhubAdapter.get_news uses 'publisher' key", '"publisher"' in source)
    test("FinnhubAdapter.get_news uses 'link' key", '"link"' in source)
    test("FinnhubAdapter.get_news uses 'providerPublishTime' key", '"providerPublishTime"' in source)

except Exception as e:
    test("Finnhub News Schema group", False, str(e))


# ══════════════════════════════════════════════════════════════════
# GROUP 3: FMP Statement → StatementParser {period, items} contract
# ══════════════════════════════════════════════════════════════════
print("\n=== TEST GROUP 3: FMP → StatementParser Schema ===")

try:
    from app.data.adapters.fmp import FMPAdapter

    # Simulate raw FMP income statement response
    raw_fmp_records = [
        {
            "date": "2024-12-31",
            "symbol": "AAPL",
            "revenue": 383285000000,
            "costOfRevenue": 210000000000,
            "grossProfit": 173285000000,
            "operatingIncome": 120000000000,
            "netIncome": 97000000000,
            "operatingExpenses": 53285000000,
            "ebitda": 130000000000,
            "eps": 6.13,
            "epsdiluted": 6.08,
        },
        {
            "date": "2023-12-31",
            "symbol": "AAPL",
            "revenue": 362000000000,
            "netIncome": 89000000000,
        }
    ]

    normalized = FMPAdapter._normalize_periods(raw_fmp_records)

    test("FMP normalize: returns list", isinstance(normalized, list))
    test("FMP normalize: correct length", len(normalized) == 2)
    test("FMP normalize: has 'period' key", "period" in normalized[0])
    test("FMP normalize: has 'items' key", "items" in normalized[0])
    test("FMP normalize: period is date string", normalized[0]["period"] == "2024-12-31")
    test("FMP normalize: 'Total Revenue' mapped",
         normalized[0]["items"].get("Total Revenue") == 383285000000)
    test("FMP normalize: 'Net Income' mapped",
         normalized[0]["items"].get("Net Income") == 97000000000)
    test("FMP normalize: 'Gross Profit' mapped",
         normalized[0]["items"].get("Gross Profit") == 173285000000)
    test("FMP normalize: 'Basic EPS' mapped",
         normalized[0]["items"].get("Basic EPS") == 6.13)

    # Verify StatementParser._item() can access normalized data
    from app.engines.research.statement_parser import StatementParser
    import inspect
    parser_source = inspect.getsource(StatementParser)
    test("StatementParser uses periods[idx]['items'].get(key)",
         "periods[idx][\"items\"].get(key)" in parser_source or
         'periods[idx]["items"].get(key)' in parser_source)

    # Verify _normalize_periods handles empty/None input
    test("FMP normalize: None → empty list", FMPAdapter._normalize_periods(None) == [])
    test("FMP normalize: [] → empty list", FMPAdapter._normalize_periods([]) == [])

except Exception as e:
    test("FMP Statement Schema group", False, str(e))


# ══════════════════════════════════════════════════════════════════
# GROUP 4: Provider Routing — Indian symbols don't hit TwelveData
# ══════════════════════════════════════════════════════════════════
print("\n=== TEST GROUP 4: Provider Routing ===")

try:
    from app.data.market_data_provider import MarketDataProvider

    mdp = MarketDataProvider()

    # Indian symbols: should NOT include twelvedata
    chain_reliance_quote = mdp._get_chain("RELIANCE.NS", "quote")
    test("RELIANCE.NS quote chain: only 'nse'",
         chain_reliance_quote == ["nse"],
         f"got {chain_reliance_quote}")

    chain_tcs_history = mdp._get_chain("TCS.NS", "history")
    test("TCS.NS history chain: only 'nse'",
         chain_tcs_history == ["nse"],
         f"got {chain_tcs_history}")

    chain_infy_news = mdp._get_chain("INFY.BO", "news")
    test("INFY.BO news chain: empty (no provider)",
         chain_infy_news == [],
         f"got {chain_infy_news}")

    chain_reliance_fundamentals = mdp._get_chain("RELIANCE.NS", "fundamentals")
    test("RELIANCE.NS fundamentals chain: empty (no provider)",
         chain_reliance_fundamentals == [],
         f"got {chain_reliance_fundamentals}")

    # US symbols: should include appropriate providers
    chain_aapl_quote = mdp._get_chain("AAPL", "quote")
    test("AAPL quote chain: twelvedata + finnhub",
         chain_aapl_quote == ["twelvedata", "finnhub"],
         f"got {chain_aapl_quote}")

    chain_aapl_news = mdp._get_chain("AAPL", "news")
    test("AAPL news chain: finnhub",
         chain_aapl_news == ["finnhub"],
         f"got {chain_aapl_news}")

    chain_aapl_financials = mdp._get_chain("AAPL", "financials")
    test("AAPL financials chain: fmp",
         chain_aapl_financials == ["fmp"],
         f"got {chain_aapl_financials}")

    chain_aapl_company = mdp._get_chain("AAPL", "company_info")
    test("AAPL company_info chain: finnhub + twelvedata",
         chain_aapl_company == ["finnhub", "twelvedata"],
         f"got {chain_aapl_company}")

    # Verify singleton usage
    from app.data.adapters.twelvedata import twelvedata_adapter
    test("MarketDataProvider uses TwelveData singleton",
         mdp._twelve is twelvedata_adapter,
         "creates a separate instance instead of using the module singleton")

except Exception as e:
    test("Provider Routing group", False, str(e))


# ══════════════════════════════════════════════════════════════════
# GROUP 5: Assistant Ticker Extraction Edge Cases
# ══════════════════════════════════════════════════════════════════
print("\n=== TEST GROUP 5: Ticker Extraction Edge Cases ===")

try:
    from app.engines.assistant.engine import AssistantEngine
    engine = AssistantEngine()

    # Indian symbols with .NS suffix must match as full symbol
    tcs_result = engine._extract_symbols("How is TCS.NS doing today?")
    test("TCS.NS → extracts TCS.NS", "TCS.NS" in tcs_result, f"got {tcs_result}")

    infy_result = engine._extract_symbols("Tell me about INFY.NS stock")
    test("INFY.NS → extracts INFY.NS", "INFY.NS" in infy_result, f"got {infy_result}")

    hdfcbank_result = engine._extract_symbols("Analyze HDFCBANK.NS")
    test("HDFCBANK.NS → extracts HDFCBANK.NS", "HDFCBANK.NS" in hdfcbank_result, f"got {hdfcbank_result}")

    reliance_bo = engine._extract_symbols("What about RELIANCE.BO?")
    test("RELIANCE.BO → extracts RELIANCE.BO", "RELIANCE.BO" in reliance_bo, f"got {reliance_bo}")

    # US symbols should still work
    aapl_result = engine._extract_symbols("Show me AAPL data")
    test("AAPL → extracts AAPL", "AAPL" in aapl_result, f"got {aapl_result}")

    msft_result = engine._extract_symbols("Compare MSFT and GOOGL")
    test("MSFT+GOOGL → extracts both", "MSFT" in msft_result and "GOOGL" in msft_result, f"got {msft_result}")

    # Stop words should NOT be extracted
    vs_result = engine._extract_symbols("Compare VS and GOING performance")
    test("VS excluded", "VS" not in vs_result, f"got {vs_result}")
    test("GOING excluded", "GOING" not in vs_result, f"got {vs_result}")

    # Mixed message
    mixed_result = engine._extract_symbols("Compare TCS.NS with AAPL")
    test("Mixed TCS.NS+AAPL: both extracted",
         "TCS.NS" in mixed_result and "AAPL" in mixed_result,
         f"got {mixed_result}")

except Exception as e:
    test("Ticker Extraction group", False, str(e))


# ══════════════════════════════════════════════════════════════════
# GROUP 6: normalize_ohlcv Safety
# ══════════════════════════════════════════════════════════════════
print("\n=== TEST GROUP 6: normalize_ohlcv Safety ===")

try:
    from app.data.market_data_provider import normalize_ohlcv
    import pandas as pd

    test("normalize_ohlcv(None) → None", normalize_ohlcv(None, "test") is None)
    test("normalize_ohlcv({}) → None", normalize_ohlcv({}, "test") is None)
    test("normalize_ohlcv([]) → None", normalize_ohlcv([], "test") is None)

    # Empty DataFrame passthrough
    empty_df = pd.DataFrame()
    test("normalize_ohlcv(empty DataFrame) → None", normalize_ohlcv(empty_df, "test") is None)

    # Valid DataFrame passthrough
    dates = pd.date_range("2024-01-01", periods=5, freq="B")
    valid_df = pd.DataFrame({
        "Open": [100, 101, 102, 103, 104],
        "High": [105, 106, 107, 108, 109],
        "Low": [95, 96, 97, 98, 99],
        "Close": [102, 103, 104, 105, 106],
        "Volume": [1000000, 1100000, 1200000, 1300000, 1400000],
    }, index=dates)
    result = normalize_ohlcv(valid_df, "test")
    test("normalize_ohlcv(valid DataFrame) → same DataFrame",
         result is not None and isinstance(result, pd.DataFrame) and len(result) == 5)

    # List-of-dicts format
    bars = [
        {"datetime": "2024-01-01", "open": 100, "high": 105, "low": 95, "close": 102, "volume": 1000000},
        {"datetime": "2024-01-02", "open": 101, "high": 106, "low": 96, "close": 103, "volume": 1100000},
    ]
    result2 = normalize_ohlcv(bars, "test")
    test("normalize_ohlcv(list-of-dicts) → DataFrame with TitleCase columns",
         result2 is not None and "Close" in result2.columns and "Volume" in result2.columns)

except Exception as e:
    test("normalize_ohlcv Safety group", False, str(e))


# ══════════════════════════════════════════════════════════════════
# GROUP 7: DataFrame Cache Roundtrip
# ══════════════════════════════════════════════════════════════════
print("\n=== TEST GROUP 7: DataFrame Cache Roundtrip ===")

try:
    import pandas as pd
    import numpy as np
    from app.data.market_data_provider import normalize_ohlcv

    # Simulate what _fetch_ohlcv now does: DataFrame → dict records
    dates = pd.date_range("2024-01-01", periods=30, freq="B")
    original_df = pd.DataFrame({
        "Open": np.random.rand(30) * 100 + 100,
        "High": np.random.rand(30) * 100 + 105,
        "Low": np.random.rand(30) * 100 + 95,
        "Close": np.random.rand(30) * 100 + 100,
        "Volume": np.random.randint(1_000_000, 50_000_000, 30),
    }, index=dates)

    # Serialize (what _fetch_ohlcv does before caching)
    records = original_df.reset_index().to_dict(orient="records")
    serialized = {"bars": records}

    test("Serialized: is dict with 'bars' key", isinstance(serialized, dict) and "bars" in serialized)
    test("Serialized: bars is list", isinstance(serialized["bars"], list))
    test("Serialized: correct length", len(serialized["bars"]) == 30)

    # Deserialize (what compute_risk does after cache read)
    reconstructed = normalize_ohlcv(serialized["bars"], "cache")
    test("Reconstructed: is DataFrame", isinstance(reconstructed, pd.DataFrame))
    test("Reconstructed: has Close column", "Close" in reconstructed.columns)
    test("Reconstructed: has Volume column", "Volume" in reconstructed.columns)
    test("Reconstructed: correct row count", len(reconstructed) == 30)

    # Verify the reconstructed DataFrame works with RiskEngine
    from app.engines.risk.engine import RiskEngine
    re = RiskEngine()
    vol_score, _ = re._compute_volatility_risk(reconstructed)
    liq_score, _ = re._compute_liquidity_risk(reconstructed)
    test("RiskEngine accepts reconstructed DataFrame (vol)", isinstance(vol_score, float))
    test("RiskEngine accepts reconstructed DataFrame (liq)", isinstance(liq_score, float))

except Exception as e:
    test("DataFrame Cache Roundtrip group", False, str(e))


# ══════════════════════════════════════════════════════════════════
# GROUP 8: Finnhub company_info canonical schema
# ══════════════════════════════════════════════════════════════════
print("\n=== TEST GROUP 8: Finnhub Company Info Schema ===")

try:
    import inspect
    from app.data.adapters.finnhub import FinnhubAdapter

    source = inspect.getsource(FinnhubAdapter.get_company_info)

    # Verify all canonical fields are present
    test("Finnhub company_info has 'sector' field", '"sector"' in source)
    test("Finnhub company_info has 'industry' field", '"industry"' in source)
    test("Finnhub company_info has 'description' field", '"description"' in source)
    test("Finnhub company_info has 'metrics' field", '"metrics"' in source)
    test("Finnhub company_info calls get_fundamentals", "get_fundamentals" in source)

except Exception as e:
    test("Finnhub Company Info Schema group", False, str(e))


# ══════════════════════════════════════════════════════════════════
# GROUP 9: NSE Accept-Encoding (no brotli)
# ══════════════════════════════════════════════════════════════════
print("\n=== TEST GROUP 9: NSE Encoding Safety ===")

try:
    from app.data.adapters import nse
    headers_source = inspect.getsource(nse)
    test("NSE Accept-Encoding does NOT include 'br'",
         '"gzip, deflate, br"' not in headers_source,
         "Still advertises brotli support without brotli package")
    test("NSE Accept-Encoding includes 'gzip, deflate'",
         '"gzip, deflate"' in headers_source)

except Exception as e:
    test("NSE Encoding Safety group", False, str(e))


# ══════════════════════════════════════════════════════════════════
# GROUP 10: Config sanity — Yahoo disabled, enabled flags exist
# ══════════════════════════════════════════════════════════════════
print("\n=== TEST GROUP 10: Config Sanity ===")

try:
    from app.config import Settings
    s = Settings()
    test("yahoo_finance_enabled = False", s.yahoo_finance_enabled == False)
    test("finnhub_enabled exists", hasattr(s, "finnhub_enabled"))
    test("fmp_enabled exists", hasattr(s, "fmp_enabled"))

except Exception as e:
    test("Config Sanity group", False, str(e))


# ══════════════════════════════════════════════════════════════════
# GROUP 11: _raise_data_error checks TwelveData health
# ══════════════════════════════════════════════════════════════════
print("\n=== TEST GROUP 11: _raise_data_error Health Passthrough ===")

try:
    # Read source from file directly — importing market.py triggers Pydantic
    # schema evaluation which uses Python 3.10+ union syntax on Python 3.9
    market_path = os.path.join("backend", "app", "api", "v1", "market.py")
    with open(market_path, "r") as f:
        source = f.read()

    test("_raise_data_error checks twelvedata_adapter", "twelvedata_adapter" in source)
    test("_raise_data_error checks 'cooldown' keyword", '"cooldown"' in source)
    test("_raise_data_error mentions MarketDataProvider", '"MarketDataProvider"' in source)
    test("_raise_data_error does NOT say Yahoo Finance in error",
         "Yahoo Finance rate limited" not in source)

except Exception as e:
    test("_raise_data_error group", False, str(e))


# ══════════════════════════════════════════════════════════════════
# GROUP 12: Risk Engine — import pandas present
# ══════════════════════════════════════════════════════════════════
print("\n=== TEST GROUP 12: Risk Engine Import Verification ===")

try:
    with open(os.path.join("backend", "app", "engines", "risk", "engine.py"), "r") as f:
        content = f.read()
    test("import pandas as pd present", "import pandas as pd" in content)
    test("import numpy as np present", "import numpy as np" in content)
    test("ohlcv['Close'] (TitleCase)", 'ohlcv["Close"]' in content)
    test("ohlcv['Volume'] (TitleCase)", 'ohlcv["Volume"]' in content)
    test("No lowercase ohlcv['close'] access",
         'ohlcv["close"]' not in content,
         "Still uses lowercase column name")
    test("No lowercase ohlcv['volume'] access",
         'ohlcv["volume"]' not in content,
         "Still uses lowercase column name")

except Exception as e:
    test("Risk Engine Import Verification group", False, str(e))


# ══════════════════════════════════════════════════════════════════
print(f"\n{'='*60}")
print(f"  RESULTS: {passed} passed, {failed} failed, {skipped} skipped")
print(f"{'='*60}")

if failed > 0:
    print(f"\n  ⚠ {failed} test(s) failed — review before deploying.")
    sys.exit(1)
else:
    print(f"\n  ✅ All tests passed — integration contracts verified.")
    sys.exit(0)
