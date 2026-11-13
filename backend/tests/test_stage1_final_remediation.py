"""
ARTH Stage 1 Final Remediation Regression Test Suite.

Proves remediation for:
- Finding A: Exchange identity & cross-market collision rejection in alert evaluator
- Finding B: Market quote freshness validation (stale rejection, future drift protection, timezone normalization)
- Finding C: Rolling sliding window quota burst prevention under load
- Finding D: Invite-only vs open signup server-side enforcement
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone, timedelta
import os
import time
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import fakeredis
import fakeredis.aioredis
import pytest

from app.api.v1.internal import _is_quote_fresh, _is_quote_identity_valid, _parse_timestamp_to_utc
from app.core.auth import _resolve_or_create_profile, UserContext
from app.core.provider_quota import ProviderQuotaGovernor, _ATOMIC_SLIDING_QUOTA_LUA
import app.config as config_mod


# =============================================================================
# Finding A: Exchange Identity in Alert Quotes
# =============================================================================

class TestQuoteIdentityValidation:
    """Proves that alerts cannot fire on quotes from mismatched exchanges or markets."""

    def test_indian_symbol_rejects_us_exchange(self):
        """HAL.NS (NSE) must reject a quote from NYSE."""
        quote = {
            "symbol": "HAL",
            "exchange": "NYSE",
            "currency": "USD",
            "market": "us",
            "price": 28.50,
        }
        assert _is_quote_identity_valid(quote, "HAL.NS") is False

    def test_indian_symbol_rejects_usd_currency(self):
        """RELIANCE.NS must reject a quote denominated in USD."""
        quote = {
            "symbol": "RELIANCE.NS",
            "exchange": "NSE",
            "currency": "USD",
            "price": 1200.0,
        }
        assert _is_quote_identity_valid(quote, "RELIANCE.NS") is False

    def test_indian_symbol_rejects_us_market(self):
        """TCS.NS must reject a quote with market='us'."""
        quote = {
            "symbol": "TCS.NS",
            "market": "us",
            "price": 3500.0,
        }
        assert _is_quote_identity_valid(quote, "TCS.NS") is False

    def test_nse_symbol_rejects_bse_exchange(self):
        """INFY.NS must reject a quote explicitly tagged as BSE."""
        quote = {
            "symbol": "INFY.NS",
            "exchange": "BSE",
            "currency": "INR",
            "price": 1800.0,
        }
        assert _is_quote_identity_valid(quote, "INFY.NS") is False

    def test_bse_symbol_rejects_nse_exchange(self):
        """INFY.BO must reject a quote explicitly tagged as NSE."""
        quote = {
            "symbol": "INFY.BO",
            "exchange": "NSE",
            "currency": "INR",
            "price": 1800.0,
        }
        assert _is_quote_identity_valid(quote, "INFY.BO") is False

    def test_us_symbol_rejects_indian_exchange(self):
        """AAPL must reject a quote from NSE or with INR currency."""
        quote = {
            "symbol": "AAPL",
            "exchange": "NSE",
            "currency": "INR",
            "price": 220.0,
        }
        assert _is_quote_identity_valid(quote, "AAPL") is False

    def test_ambiguous_hal_ticker_cross_market_protection(self):
        """
        HAL is ambiguous between Hindustan Aeronautics (NSE: HAL.NS) and Halliburton (NYSE: HAL).
        A bare 'HAL' quote with NYSE exchange or USD currency must NOT satisfy HAL.NS.
        """
        nyse_quote = {
            "symbol": "HAL",
            "exchange": "NYSE",
            "currency": "USD",
            "price": 28.50,
        }
        assert _is_quote_identity_valid(nyse_quote, "HAL.NS") is False

        # Legitimate Indian HAL quote from Upstox
        nse_quote = {
            "symbol": "HAL.NS",
            "exchange": "NSE",
            "currency": "INR",
            "price": 4500.0,
        }
        assert _is_quote_identity_valid(nse_quote, "HAL.NS") is True

    def test_ambiguous_hal_fails_closed_without_exchange_or_currency_metadata(self):
        """
        Fail-closed contract: An ambiguous ticker (HAL) with bare symbol and NO exchange/currency
        metadata cannot be established as Indian, and must be strictly rejected for HAL.NS.
        """
        bare_unmetadata_quote = {
            "symbol": "HAL",
            "price": 4500.0,
        }
        assert _is_quote_identity_valid(bare_unmetadata_quote, "HAL.NS") is False

    def test_ambiguous_hal_accepted_with_positive_indian_metadata(self):
        """
        A bare 'HAL' quote that explicitly supplies Indian exchange (NSE) and currency (INR)
        is safely recognized and accepted for HAL.NS.
        """
        bare_with_metadata = {
            "symbol": "HAL",
            "exchange": "NSE",
            "currency": "INR",
            "price": 4500.0,
        }
        assert _is_quote_identity_valid(bare_with_metadata, "HAL.NS") is True

    def test_legitimate_quotes_accepted(self):
        """Valid Indian and US quotes must be accepted for their respective symbols."""
        indian_quote = {
            "symbol": "RELIANCE.NS",
            "exchange": "NSE",
            "currency": "INR",
            "price": 1250.0,
        }
        assert _is_quote_identity_valid(indian_quote, "RELIANCE.NS") is True

        us_quote = {
            "symbol": "MSFT",
            "exchange": "NASDAQ",
            "currency": "USD",
            "price": 420.0,
        }
        assert _is_quote_identity_valid(us_quote, "MSFT") is True


# =============================================================================
# Finding B: Stale Market Quotes
# =============================================================================

class TestQuoteFreshnessValidation:
    """Proves quote freshness validation against actual market timestamp, ingestion, and drift."""

    def test_stale_market_timestamp_rejected_despite_recent_ingestion(self):
        """
        CRITICAL: A quote with fresh ingested_at (cached 5s ago) but STALE market data
        timestamp (e.g. 2 hours old) MUST BE REJECTED.
        """
        now = datetime(2026, 11, 13, 10, 0, 0, tzinfo=timezone.utc)
        data = {
            "price": 100.0,
            "timestamp": (now - timedelta(hours=2)).isoformat(),  # Stale market trade
            "ingested_at": (now - timedelta(seconds=5)).isoformat(),  # Recent cache write
        }
        assert _is_quote_fresh(data, now, max_age_seconds=900.0) is False

    def test_missing_all_timestamps_rejected(self):
        """A quote with no timestamps at all must fail closed."""
        now = datetime(2026, 11, 13, 10, 0, 0, tzinfo=timezone.utc)
        data = {"price": 100.0}
        assert _is_quote_fresh(data, now, max_age_seconds=900.0) is False

    def test_future_timestamp_beyond_tolerance_rejected(self):
        """A quote with a timestamp 2 minutes in the future (>60s clock skew) must be rejected."""
        now = datetime(2026, 11, 13, 10, 0, 0, tzinfo=timezone.utc)
        data = {
            "price": 100.0,
            "timestamp": (now + timedelta(seconds=120)).isoformat(),
        }
        assert _is_quote_fresh(data, now, max_age_seconds=900.0) is False

    def test_minor_clock_drift_within_60s_tolerated(self):
        """A quote timestamp up to 30s in the future (minor clock skew) is tolerated."""
        now = datetime(2026, 11, 13, 10, 0, 0, tzinfo=timezone.utc)
        data = {
            "price": 100.0,
            "timestamp": (now + timedelta(seconds=30)).isoformat(),
        }
        assert _is_quote_fresh(data, now, max_age_seconds=900.0) is True

    def test_epoch_timestamp_handling(self):
        """Accepts unix epoch in seconds or milliseconds."""
        now = datetime(2026, 11, 13, 10, 0, 0, tzinfo=timezone.utc)
        now_ts = now.timestamp()
        
        # 100s ago in seconds
        data_sec = {"price": 100.0, "timestamp": int(now_ts - 100)}
        assert _is_quote_fresh(data_sec, now, max_age_seconds=900.0) is True

        # 100s ago in milliseconds
        data_ms = {"price": 100.0, "timestamp": int((now_ts - 100) * 1000)}
        assert _is_quote_fresh(data_ms, now, max_age_seconds=900.0) is True

    def test_naive_timestamp_normalized_to_utc(self):
        """Naive ISO timestamp is normalized to UTC without crashing."""
        now = datetime(2026, 11, 13, 10, 0, 0, tzinfo=timezone.utc)
        data = {
            "price": 100.0,
            "timestamp": "2026-11-13T09:55:00",  # 5 minutes ago (naive)
        }
        assert _is_quote_fresh(data, now, max_age_seconds=900.0) is True

    def test_malformed_market_timestamp_with_fresh_ingestion_rejected(self):
        """
        CodeRabbit / Stage-1 Hardening: If a market timestamp is present but malformed
        or unparseable, it MUST BE REJECTED IMMEDIATELY. It must NEVER fall back to ingested_at.
        """
        now = datetime(2026, 11, 13, 10, 0, 0, tzinfo=timezone.utc)
        fresh_ingest = (now - timedelta(seconds=5)).isoformat()

        # Unparseable string format
        data_corrupt = {
            "price": 100.0,
            "timestamp": "not-a-valid-timestamp",
            "ingested_at": fresh_ingest,
        }
        assert _is_quote_fresh(data_corrupt, now, max_age_seconds=900.0) is False

        # Unparseable object / structure
        data_struct = {
            "price": 100.0,
            "datetime": {"bad": "type"},
            "ingested_at": fresh_ingest,
        }
        assert _is_quote_fresh(data_struct, now, max_age_seconds=900.0) is False

    def test_empty_or_whitespace_market_timestamp_rejected_as_malformed(self):
        """
        DECISION & DOCUMENTATION: Empty or whitespace-only market timestamp fields.

        In financial systems, an empty string ("") or whitespace-only ("   ") supplied
        as a market timestamp coordinate is classified as MALFORMED (fail-closed -> rejected).

        Rationale:
        1. A market timestamp is a temporal coordinate; an empty string indicates data truncation,
           corrupted upstream payload, or broken field extraction.
        2. Treating empty strings as 'absent' would mask malfunctioning provider feeds by allowing
           them to silently fall back to ingestion freshness.
        3. Truly absent timestamps are represented solely by omitting the key (or explicitly None).
           Any non-null string provided must parse into a valid datetime or fail closed.
        """
        now = datetime(2026, 11, 13, 10, 0, 0, tzinfo=timezone.utc)
        fresh_ingest = (now - timedelta(seconds=5)).isoformat()

        # Empty string
        data_empty = {
            "price": 100.0,
            "timestamp": "",
            "ingested_at": fresh_ingest,
        }
        assert _is_quote_fresh(data_empty, now, max_age_seconds=900.0) is False

        # Whitespace-only string
        data_ws = {
            "price": 100.0,
            "timestamp": "   \t\n ",
            "ingested_at": fresh_ingest,
        }
        assert _is_quote_fresh(data_ws, now, max_age_seconds=900.0) is False

    def test_truly_absent_market_timestamp_with_fresh_ingestion_accepted(self):
        """
        Preserve intended fallback: when no market timestamp is provided at all
        (omitted key or explicit None), a valid fresh ingestion timestamp is accepted.
        """
        now = datetime(2026, 11, 13, 10, 0, 0, tzinfo=timezone.utc)
        fresh_ingest = (now - timedelta(seconds=5)).isoformat()

        # Completely absent market timestamp keys
        data_absent = {
            "price": 100.0,
            "ingested_at": fresh_ingest,
        }
        assert _is_quote_fresh(data_absent, now, max_age_seconds=900.0) is True

        # Explicit None (representing null / unavailable field)
        data_none = {
            "price": 100.0,
            "timestamp": None,
            "ingested_at": fresh_ingest,
        }
        assert _is_quote_fresh(data_none, now, max_age_seconds=900.0) is True

    def test_valid_stale_market_timestamp_with_fresh_ingestion_rejected(self):
        """
        A valid, parseable market timestamp that is stale (older than max_age_seconds)
        must be rejected even if ingested_at is fresh.
        """
        now = datetime(2026, 11, 13, 10, 0, 0, tzinfo=timezone.utc)
        data = {
            "price": 100.0,
            "timestamp": (now - timedelta(minutes=20)).isoformat(),  # 20 min old > 15 min limit
            "ingested_at": (now - timedelta(seconds=2)).isoformat(),  # 2 sec old
        }
        assert _is_quote_fresh(data, now, max_age_seconds=900.0) is False

    def test_valid_fresh_market_timestamp_accepted(self):
        """
        A valid fresh market timestamp is accepted with or without an ingestion timestamp.
        """
        now = datetime(2026, 11, 13, 10, 0, 0, tzinfo=timezone.utc)
        fresh_market = (now - timedelta(seconds=45)).isoformat()

        # Without ingested_at
        data_no_ingest = {
            "price": 100.0,
            "timestamp": fresh_market,
        }
        assert _is_quote_fresh(data_no_ingest, now, max_age_seconds=900.0) is True

        # With fresh ingested_at
        data_with_ingest = {
            "price": 100.0,
            "timestamp": fresh_market,
            "ingested_at": (now - timedelta(seconds=10)).isoformat(),
        }
        assert _is_quote_fresh(data_with_ingest, now, max_age_seconds=900.0) is True

    def test_boolean_market_timestamp_rejected_as_malformed(self):
        """
        Python booleans (True/False are subclasses of int) must not be parsed as
        epoch timestamps (0 or 1); they must be rejected as malformed.
        """
        now = datetime(2026, 11, 13, 10, 0, 0, tzinfo=timezone.utc)
        fresh_ingest = (now - timedelta(seconds=5)).isoformat()

        assert _is_quote_fresh({"price": 100.0, "timestamp": False, "ingested_at": fresh_ingest}, now) is False
        assert _is_quote_fresh({"price": 100.0, "timestamp": True, "ingested_at": fresh_ingest}, now) is False

    def test_zero_epoch_market_timestamp_rejected_as_stale(self):
        """
        Timestamp value 0 (epoch 1970-01-01) is non-None, parseable, and 56 years old;
        it must be rejected as stale even if ingested_at is fresh.
        """
        now = datetime(2026, 11, 13, 10, 0, 0, tzinfo=timezone.utc)
        fresh_ingest = (now - timedelta(seconds=5)).isoformat()

        assert _is_quote_fresh({"price": 100.0, "timestamp": 0, "ingested_at": fresh_ingest}, now) is False

    def test_fresh_market_timestamp_with_malformed_ingested_at_rejected(self):
        """
        If a market timestamp is fresh, but an explicit non-null ingested_at is malformed,
        it MUST BE REJECTED (fail-closed integrity).
        """
        now = datetime(2026, 11, 13, 10, 0, 0, tzinfo=timezone.utc)
        data = {
            "price": 100.0,
            "timestamp": (now - timedelta(seconds=30)).isoformat(),
            "ingested_at": "malformed_ingest_string",
        }
        assert _is_quote_fresh(data, now, max_age_seconds=900.0) is False

    def test_fresh_market_timestamp_with_none_ingested_at_accepted(self):
        """
        If ingested_at is explicitly None, a valid fresh market timestamp is accepted.
        """
        now = datetime(2026, 11, 13, 10, 0, 0, tzinfo=timezone.utc)
        data = {
            "price": 100.0,
            "timestamp": (now - timedelta(seconds=30)).isoformat(),
            "ingested_at": None,
        }
        assert _is_quote_fresh(data, now, max_age_seconds=900.0) is True

    def test_fresh_market_timestamp_with_missing_ingestion_metadata_accepted(self):
        """
        If ingestion metadata is completely absent, a valid fresh market timestamp is accepted.
        """
        now = datetime(2026, 11, 13, 10, 0, 0, tzinfo=timezone.utc)
        data = {
            "price": 100.0,
            "timestamp": (now - timedelta(seconds=30)).isoformat(),
        }
        assert _is_quote_fresh(data, now, max_age_seconds=900.0) is True

    def test_missing_market_timestamp_with_valid_fresh_cached_at_accepted(self):
        """
        When market timestamp is absent, _cached_at (from cache.py) provides a valid fallback.
        """
        now = datetime(2026, 11, 13, 10, 0, 0, tzinfo=timezone.utc)
        data = {
            "price": 100.0,
            "_cached_at": (now - timedelta(seconds=5)).isoformat(),
        }
        assert _is_quote_fresh(data, now, max_age_seconds=900.0) is True

    def test_missing_market_timestamp_malformed_ingested_at_with_valid_cached_at_rejected(self):
        """
        PRECISION & PRECEDENCE DECISION:
        When market timestamp is missing, an explicit non-null 'ingested_at' that is malformed
        MUST FAIL CLOSED immediately. It must NOT silently fall through to '_cached_at'.
        """
        now = datetime(2026, 11, 13, 10, 0, 0, tzinfo=timezone.utc)
        data = {
            "price": 100.0,
            "ingested_at": "corrupt_metadata",
            "_cached_at": (now - timedelta(seconds=5)).isoformat(),
        }
        assert _is_quote_fresh(data, now, max_age_seconds=900.0) is False

    def test_stale_ingestion_timestamp_alongside_fresh_market_timestamp_rejected(self):
        """
        If market timestamp is fresh, but ingestion timestamp is stale (e.g. replayed cache entry),
        the quote must be rejected.
        """
        now = datetime(2026, 11, 13, 10, 0, 0, tzinfo=timezone.utc)
        data = {
            "price": 100.0,
            "timestamp": (now - timedelta(seconds=10)).isoformat(),
            "ingested_at": (now - timedelta(hours=2)).isoformat(),
        }
        assert _is_quote_fresh(data, now, max_age_seconds=900.0) is False


# =============================================================================
# Finding C: Provider Quota Boundary Protection
# =============================================================================

class TestProviderQuotaBoundaryProtection:
    """Proves that sliding window quota does not admit boundary bursts across exact thresholds."""

    @pytest.mark.asyncio
    async def test_exclusive_boundary_prevents_millisecond_burst(self):
        """
        Adversarial: Test that at t = base + 1000ms, entries from t = base are
        strictly retained until > 1000ms has elapsed.
        """
        server = fakeredis.FakeServer()
        client = fakeredis.aioredis.FakeRedis(server=server)

        base_ms = 1_000_000_000
        limit = 5

        # Insert 5 requests at base_ms
        for i in range(limit):
            res = await client.eval(
                _ATOMIC_SLIDING_QUOTA_LUA,
                3,
                "quota:burst_test:sec_zset",
                "quota:burst_test:min_zset",
                "quota:burst_test:daily",
                1,
                limit,  # sec_limit = 5
                -1,
                -1,
                base_ms,
                f"req_{i}",
            )
            assert res == 1

        # At exactly base_ms + 1000, exactly 1000ms has elapsed.
        # With exclusive boundary '(', member at base_ms is NOT purged, so a new request is REJECTED.
        res_at_1000 = await client.eval(
            _ATOMIC_SLIDING_QUOTA_LUA,
            3,
            "quota:burst_test:sec_zset",
            "quota:burst_test:min_zset",
            "quota:burst_test:daily",
            1,
            limit,
            -1,
            -1,
            base_ms + 1000,
            "burst_at_1000",
        )
        assert res_at_1000 == -2, "At t = base + 1000ms, window must still protect against burst!"

        # At base_ms + 1001ms, > 1000ms has elapsed, so member at base_ms is purged.
        res_at_1001 = await client.eval(
            _ATOMIC_SLIDING_QUOTA_LUA,
            3,
            "quota:burst_test:sec_zset",
            "quota:burst_test:min_zset",
            "quota:burst_test:daily",
            1,
            limit,
            -1,
            -1,
            base_ms + 1001,
            "req_at_1001",
        )
        assert res_at_1001 == 1, "At t = base + 1001ms, quota token must become available"


# =============================================================================
# Finding D: Invite-Only Signup Enforcement
# =============================================================================

class TestInviteOnlySignupEnforcement:
    """Proves server-side enforcement of invite_only_mode when database is available."""

    @pytest.mark.asyncio
    async def test_invite_only_mode_disabled_provisions_active_profile(self):
        """When invite_only_mode is False, new users are provisioned with access_status='active'."""
        mock_db = AsyncMock()
        # First call: SELECT returns None (new user)
        # Second call: RETURNING id (INSERT succeeds)
        # Third call: SELECT returns row with access_status='active'
        mock_db.fetchrow.side_effect = [
            None,  # Not found initially
            {"id": uuid4()},  # INSERT RETURNING id
            {"access_status": "active", "role": "user"},  # Final read
        ]
        mock_db.execute.return_value = "UPDATE 0"

        with patch("app.config.get_settings") as mock_get_settings:
            mock_settings = MagicMock()
            mock_settings.invite_only_mode = False
            mock_settings.initial_admin_email = ""
            mock_get_settings.return_value = mock_settings

            status, role = await _resolve_or_create_profile(
                user_id=uuid4(),
                email="newuser@example.com",
                display_name="New User",
                db=mock_db,
            )

        assert status == "active"
        assert role == "user"

        # Verify SQL INSERT received 'active'
        insert_call = mock_db.fetchrow.call_args_list[1]
        assert "active" in insert_call[0]

    @pytest.mark.asyncio
    async def test_invite_only_mode_enabled_provisions_pending_profile(self):
        """When invite_only_mode is True, new uninvited users are provisioned with access_status='pending'."""
        mock_db = AsyncMock()
        mock_db.fetchrow.side_effect = [
            None,  # Not found initially
            {"id": uuid4()},  # INSERT RETURNING id
            {"access_status": "pending", "role": "user"},  # Final read
        ]
        mock_db.execute.return_value = "UPDATE 0"

        with patch("app.config.get_settings") as mock_get_settings:
            mock_settings = MagicMock()
            mock_settings.invite_only_mode = True
            mock_settings.initial_admin_email = ""
            mock_get_settings.return_value = mock_settings

            status, role = await _resolve_or_create_profile(
                user_id=uuid4(),
                email="stranger@example.com",
                display_name="Stranger",
                db=mock_db,
            )

        assert status == "pending"
        assert role == "user"

        # Verify SQL INSERT received 'pending'
        insert_call = mock_db.fetchrow.call_args_list[1]
        assert "pending" in insert_call[0]

    @pytest.mark.asyncio
    async def test_admin_bootstrap_promotes_regardless_of_mode(self):
        """Initial admin email bootstrap promotes user to admin and active even in invite-only mode."""
        admin_id = uuid4()
        admin_email = "admin@arth.ai"

        mock_db = AsyncMock()
        mock_db.fetchrow.side_effect = [
            None,  # Not found initially
            {"id": admin_id},  # INSERT
            {"access_status": "active", "role": "admin"},  # Final read
        ]
        mock_db.execute.return_value = "UPDATE 1"  # Bootstrap update succeeded

        with patch("app.config.get_settings") as mock_get_settings:
            mock_settings = MagicMock()
            mock_settings.invite_only_mode = True
            mock_settings.initial_admin_email = admin_email
            mock_get_settings.return_value = mock_settings

            status, role = await _resolve_or_create_profile(
                user_id=admin_id,
                email=admin_email,
                display_name="Admin",
                db=mock_db,
            )

        assert status == "active"
        assert role == "admin"
