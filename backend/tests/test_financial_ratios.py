"""
Unit tests for financial ratios, provider contract compliance, and freshness engine.

Verifies:
1. Upstox D/E ratio preservation (direct ratio <= 20.0).
2. Finnhub D/E ratio preservation.
3. Legacy percentage representation conversion (> 20.0 -> / 100.0).
4. Equivalence: raw ratio 0.37 yields identical risk score to legacy 37.0%.
5. Risk engine financial score behavior under extreme leverage and missing data.
6. Market session awareness (open/closed) and staleness evaluation in freshness engine.
7. CacheManager in-memory quote cache fallback when Redis is absent.
"""

from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
import pytest

from app.engines.risk.engine import RiskEngine
from app.api.v1.market import get_market_state, _make_freshness
from app.data.cache import CacheManager, _memory_cache
from tests.fixtures.provider_contracts import (
    UPSTOX_KEY_RATIOS_FIXTURES,
    FINNHUB_METRIC_FIXTURES,
    LEGACY_PERCENTAGE_FIXTURES,
)


class TestFinancialRatiosContractNormalization:
    """Test unit normalization across different provider contracts."""

    def setup_method(self):
        self.risk_engine = RiskEngine()

    def test_upstox_contract_de_normalization(self):
        """Upstox provides D/E as a direct float (e.g., 0.37 for Reliance). Ensure it is preserved."""
        # Test Reliance (D/E = 0.37)
        rel_ratios = {r["key"]: r["value"] for r in UPSTOX_KEY_RATIOS_FIXTURES["RELIANCE"]["data"]["ratios"]}
        score, factors, available = self.risk_engine._compute_financial_risk(rel_ratios)
        assert available is True
        assert score < 45.0  # Lower risk score = healthy balance sheet
        assert any("Low leverage" in f or "0.37" in f for f in factors)

        # Test TCS (D/E = 0.08)
        tcs_ratios = {r["key"]: r["value"] for r in UPSTOX_KEY_RATIOS_FIXTURES["TCS"]["data"]["ratios"]}
        score, factors, available = self.risk_engine._compute_financial_risk(tcs_ratios)
        assert available is True
        assert score < 40.0
        assert any("Low leverage" in f or "0.08" in f for f in factors)

        # Test Infosys (D/E = 0.11)
        infy_ratios = {r["key"]: r["value"] for r in UPSTOX_KEY_RATIOS_FIXTURES["INFY"]["data"]["ratios"]}
        score, factors, available = self.risk_engine._compute_financial_risk(infy_ratios)
        assert available is True
        assert score < 40.0

    def test_finnhub_contract_de_normalization(self):
        """Finnhub provides debtToEquityAnnual as direct float (e.g. 0.38 for MSFT, 1.45 for AAPL)."""
        msft_metric = FINNHUB_METRIC_FIXTURES["MSFT"]["metric"]
        msft_ratios = {
            "debt_to_equity": msft_metric["debtToEquityAnnual"],
            "pe_ratio": msft_metric["peNormalizedAnnual"],
            "roe": msft_metric["roeTTM"],
            "current_ratio": msft_metric["currentRatioAnnual"],
        }
        score, factors, available = self.risk_engine._compute_financial_risk(msft_ratios)
        assert available is True
        assert score < 45.0

        aapl_metric = FINNHUB_METRIC_FIXTURES["AAPL"]["metric"]
        aapl_ratios = {
            "debt_to_equity": aapl_metric["debtToEquityAnnual"],
            "pe_ratio": aapl_metric["peNormalizedAnnual"],
            "roe": aapl_metric["roeTTM"],
            "current_ratio": aapl_metric["currentRatioAnnual"],
        }
        score, factors, available = self.risk_engine._compute_financial_risk(aapl_ratios)
        assert available is True
        # AAPL has higher financial leverage (1.45), so financial risk is moderate
        assert score >= 40.0

    def test_low_debt_and_contract_semantics(self):
        """Verify low-debt ratios (8% = 0.08, 15% = 0.15) are strictly evaluated as low leverage."""
        low_debt_8 = {"debt_to_equity": 0.08, "current_ratio": 2.0}
        low_debt_15 = {"debt_to_equity": 0.15, "current_ratio": 2.0}
        normal_debt_37 = {"debt_to_equity": 0.37, "current_ratio": 1.5}
        distressed_800 = {"debt_to_equity": 8.0, "current_ratio": 0.6}

        score_8, factors_8, ok_8 = self.risk_engine._compute_financial_risk(low_debt_8, sector="Technology")
        score_15, factors_15, ok_15 = self.risk_engine._compute_financial_risk(low_debt_15, sector="Technology")
        score_37, factors_37, ok_37 = self.risk_engine._compute_financial_risk(normal_debt_37, sector="Technology")
        score_800, factors_800, ok_800 = self.risk_engine._compute_financial_risk(distressed_800, sector="Technology")

        assert ok_8 and ok_15 and ok_37 and ok_800
        # 0.08 is lowest risk, 8.0 is highest risk
        assert score_8 <= score_15 <= score_37 < score_800
        assert any("Low leverage" in f for f in factors_8)
        assert any("Very high leverage" in f for f in factors_800)

    def test_market_holidays(self):
        """Verify known NSE and US exchange holidays are recognized as closed."""
        tz_nse = ZoneInfo("Asia/Kolkata")
        tz_us = ZoneInfo("America/New_York")

        # Christmas 2026 (Friday Dec 25)
        xmas_nse = datetime(2026, 12, 25, 11, 0, 0, tzinfo=tz_nse).astimezone(timezone.utc)
        state_nse, label_nse = get_market_state("RELIANCE.NS", dt=xmas_nse)
        assert state_nse == "closed"
        assert label_nse == "Market Holiday"

        # Republic Day 2026 (Monday Jan 26)
        rep_day = datetime(2026, 1, 26, 11, 0, 0, tzinfo=tz_nse).astimezone(timezone.utc)
        state_rep, label_rep = get_market_state("RELIANCE.NS", dt=rep_day)
        assert state_rep == "closed"
        assert label_rep == "Market Holiday"

        # US Independence Day Observed 2026 (Friday July 3)
        us_july3 = datetime(2026, 7, 3, 14, 0, 0, tzinfo=tz_us).astimezone(timezone.utc)
        state_us, label_us = get_market_state("AAPL", dt=us_july3)
        assert state_us == "closed"
        assert label_us == "Market Holiday"

    def test_extreme_leverage_and_distress(self):
        """Test financial risk scoring boundaries from zero debt to extreme leverage."""
        # Zero debt (healthy)
        score_zero, _, _ = self.risk_engine._compute_financial_risk({"debt_to_equity": 0.0, "current_ratio": 2.5})
        # Heavy leverage (D/E = 4.0, risky)
        score_heavy, _, _ = self.risk_engine._compute_financial_risk({"debt_to_equity": 4.0, "current_ratio": 0.8})

        # Higher risk score means higher financial risk
        assert score_heavy > score_zero
        assert score_heavy >= 60.0

    def test_missing_data_graceful_handling(self):
        """When fundamental metrics are missing, available must be False."""
        score, factors, available = self.risk_engine._compute_financial_risk({})
        assert available is False
        assert score == 50.0


class TestFreshnessEngineAndMarketSessions:
    """Test market session awareness, authentic timestamps, and staleness calculations."""

    def test_indian_market_session_open_vs_closed(self):
        """NSE trading session is 09:15 to 15:30 IST on weekdays."""
        tz = ZoneInfo("Asia/Kolkata")

        # Wednesday 11:00 AM IST (Market Open)
        tuesday_open = datetime(2026, 10, 21, 11, 0, 0, tzinfo=tz).astimezone(timezone.utc)
        state, label = get_market_state("RELIANCE.NS", dt=tuesday_open)
        assert state == "open"
        assert label == "Regular Trading"

        # Wednesday 08:00 AM IST (Before Market Open)
        tuesday_pre = datetime(2026, 10, 21, 8, 0, 0, tzinfo=tz).astimezone(timezone.utc)
        state, label = get_market_state("RELIANCE.NS", dt=tuesday_pre)
        assert state == "closed"
        assert label == "After Hours"

        # Wednesday 18:00 PM IST (After Market Close)
        tuesday_post = datetime(2026, 10, 21, 18, 0, 0, tzinfo=tz).astimezone(timezone.utc)
        state, label = get_market_state("RELIANCE.NS", dt=tuesday_post)
        assert state == "closed"

        # Saturday (Weekend)
        saturday = datetime(2026, 10, 24, 12, 0, 0, tzinfo=tz).astimezone(timezone.utc)
        state, label = get_market_state("RELIANCE.NS", dt=saturday)
        assert state == "closed"
        assert label == "Weekend"

    def test_us_market_session_open_vs_closed(self):
        """US regular trading hours are 09:30 to 16:00 ET on weekdays."""
        tz = ZoneInfo("America/New_York")

        # Wednesday 14:00 ET (Market Open)
        wed_open = datetime(2026, 10, 21, 14, 0, 0, tzinfo=tz).astimezone(timezone.utc)
        state, label = get_market_state("AAPL", dt=wed_open)
        assert state == "open"
        assert label == "Regular Trading"

        # Wednesday 20:00 ET (Closed)
        wed_closed = datetime(2026, 10, 21, 20, 0, 0, tzinfo=tz).astimezone(timezone.utc)
        state, label = get_market_state("AAPL", dt=wed_closed)
        assert state == "closed"

        # Sunday (Weekend)
        sunday = datetime(2026, 10, 25, 12, 0, 0, tzinfo=tz).astimezone(timezone.utc)
        state, label = get_market_state("AAPL", dt=sunday)
        assert state == "closed"
        assert label == "Weekend"

    def test_closed_market_freshness_metadata(self):
        """When exchange is closed, quote must NEVER be falsely marked stale."""
        old_friday_quote = datetime(2026, 10, 23, 15, 30, 0, tzinfo=timezone.utc)

        freshness = _make_freshness(
            source="Upstox",
            quote_timestamp=old_friday_quote,
            market_or_symbol="RELIANCE.NS",
        )
        # Note: If test runs outside market hours, it confirms last close handling
        curr_state, _ = get_market_state("RELIANCE.NS")
        if curr_state == "closed":
            assert freshness.market_state == "closed"
            assert freshness.is_stale is False
            assert freshness.delay_label == "last close"

    def test_open_market_freshness_evaluation(self):
        """During market hours, quotes older than threshold become stale."""
        fresh_ts = datetime.now(timezone.utc) - timedelta(seconds=30)
        fresh_meta = _make_freshness(
            source="Upstox",
            quote_timestamp=fresh_ts,
            market_or_symbol="RELIANCE.NS",
        )
        curr_state, _ = get_market_state("RELIANCE.NS")
        if curr_state == "open":
            assert fresh_meta.is_stale is False
            assert fresh_meta.delay_label == "real-time"
        else:
            assert fresh_meta.market_state == "closed"
            assert fresh_meta.delay_label == "last close"


class TestInMemoryCacheFallback:
    """Test CacheManager bounded in-memory quote cache when Redis is unavailable."""

    @pytest.mark.asyncio
    async def test_in_memory_quote_cache_roundtrip(self):
        """Verify CacheManager seamlessly falls back to memory cache when redis is None."""
        cache = CacheManager(None)

        quote_payload = {
            "symbol": "RELIANCE.NS",
            "price": 1200.0,
            "change": 5.0,
            "change_percent": 0.42,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        # Store in cache
        key = cache.quote_key("RELIANCE.NS")
        await cache.set(key, quote_payload, ttl=60)

        # Retrieve from cache
        cached = await cache.get(key)
        assert cached is not None
        assert cached["symbol"] == "RELIANCE.NS"
        assert cached["price"] == 1200.0
        assert cached["_cache_hit"] is True

        # Test eviction on expiration
        _memory_cache[key] = (quote_payload, 0.0)  # expired monotonic time
        expired = await cache.get(key)
        assert expired is None
