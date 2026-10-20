"""
Sanitized provider contract fixtures for ARTH unit testing.

Represents verified API response shapes from upstream data providers:
- Upstox (/v2/fundamentals/{isin}/key-ratios)
- Finnhub (/stock/metric)
- Legacy sources (percentage representations)
"""

UPSTOX_KEY_RATIOS_FIXTURES = {
    "RELIANCE": {
        "status": "success",
        "data": {
            "ratios": [
                {"name": "Price to Earnings", "value": 24.8, "key": "pe_ratio"},
                {"name": "Price to Book", "value": 2.15, "key": "pb_ratio"},
                {"name": "Debt to Equity", "value": 0.37, "key": "debt_to_equity"},
                {"name": "Return on Equity", "value": 9.45, "key": "roe"},
                {"name": "Return on Assets", "value": 5.12, "key": "roa"},
                {"name": "Current Ratio", "value": 1.18, "key": "current_ratio"},
            ]
        },
    },
    "TCS": {
        "status": "success",
        "data": {
            "ratios": [
                {"name": "Price to Earnings", "value": 31.2, "key": "pe_ratio"},
                {"name": "Price to Book", "value": 13.8, "key": "pb_ratio"},
                {"name": "Debt to Equity", "value": 0.08, "key": "debt_to_equity"},
                {"name": "Return on Equity", "value": 48.5, "key": "roe"},
                {"name": "Return on Assets", "value": 32.1, "key": "roa"},
                {"name": "Current Ratio", "value": 2.45, "key": "current_ratio"},
            ]
        },
    },
    "INFY": {
        "status": "success",
        "data": {
            "ratios": [
                {"name": "Price to Earnings", "value": 26.4, "key": "pe_ratio"},
                {"name": "Price to Book", "value": 8.1, "key": "pb_ratio"},
                {"name": "Debt to Equity", "value": 0.11, "key": "debt_to_equity"},
                {"name": "Return on Equity", "value": 31.8, "key": "roe"},
                {"name": "Return on Assets", "value": 21.4, "key": "roa"},
                {"name": "Current Ratio", "value": 2.10, "key": "current_ratio"},
            ]
        },
    },
}

FINNHUB_METRIC_FIXTURES = {
    "AAPL": {
        "metric": {
            "peNormalizedAnnual": 32.4,
            "pbAnnual": 45.2,
            "debtToEquityAnnual": 1.45,
            "debtToEquityQuarterly": 1.52,
            "roeTTM": 147.2,
            "roaTTM": 28.5,
            "currentRatioAnnual": 0.98,
        },
        "metricType": "all",
        "symbol": "AAPL",
    },
    "MSFT": {
        "metric": {
            "peNormalizedAnnual": 34.1,
            "pbAnnual": 11.8,
            "debtToEquityAnnual": 0.38,
            "debtToEquityQuarterly": 0.36,
            "roeTTM": 38.4,
            "roaTTM": 18.2,
            "currentRatioAnnual": 1.24,
        },
        "metricType": "all",
        "symbol": "MSFT",
    },
}

LEGACY_PERCENTAGE_FIXTURES = {
    "LEGACY_RELIANCE": {
        "debt_to_equity": 37.0,  # 37.0% represented as 37.0
        "pe_ratio": 24.8,
        "pb_ratio": 2.15,
        "roe": 9.45,
    },
    "LEGACY_HIGH_DEBT": {
        "debt_to_equity": 185.0,  # 185% represented as 185.0
        "pe_ratio": 15.0,
        "roe": 5.0,
    },
}
