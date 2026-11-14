"""
ARTH Canonical Exchange Calendar Engine (Milestone M2.5 Remediation).

Provides authoritative trading session determination, holiday filtering,
and forward/backward horizon trading session date resolution for:
- National Stock Exchange of India (NSE) / BSE (IST, UTC+5:30)
- New York Stock Exchange (NYSE) / NASDAQ (US Eastern Time)

Features:
- Strict segregation of Confirmed vs Provisional holidays.
- Bounded calendar coverage validation with fail-closed behavior.
- Timezone conversions preserving exact local exchange clock times.
- Forward and backward $n$-session date resolution.
- Integration with observed historical price bars for label generation.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import List, Optional, Set, Tuple, Union
from zoneinfo import ZoneInfo

from app.core.market_calendar import (
    CalendarCoverageError,
    NSE_CONFIRMED_HOLIDAYS_2026,
    NSE_COVERAGE_END,
    NSE_COVERAGE_START,
    NSE_PROVISIONAL_HOLIDAYS_2027,
    NYSE_CONFIRMED_HOLIDAYS_2026,
    NYSE_CONFIRMED_HOLIDAYS_2027,
    NYSE_COVERAGE_END,
    NYSE_COVERAGE_START,
    NYSE_EARLY_CLOSES,
    TZ_ET,
    TZ_IST,
    US_HOLIDAYS,
    get_market_state,
    is_nse_holiday,
    is_nse_special_session,
    is_us_early_close,
    is_us_holiday,
)
from app.core.symbols import is_indian_symbol


class ExchangeCalendar:
    """Authoritative exchange calendar for multi-market trading schedules."""

    def __init__(self) -> None:
        self.tz_ist = TZ_IST
        self.tz_et = TZ_ET

    def _resolve_exchange(self, exchange_or_symbol: str) -> str:
        """Resolve exchange identifier to 'NSE' or 'NYSE'."""
        if not exchange_or_symbol:
            return "NYSE"
        s = exchange_or_symbol.strip().upper()
        if is_indian_symbol(s) or s in ("NSE", "BSE", "INDIA"):
            return "NSE"
        return "NYSE"

    def _to_date(self, dt: Union[date, datetime, str], exchange: str = "NSE") -> date:
        """Coerce date, datetime, or ISO string to exchange-local calendar date."""
        if isinstance(dt, datetime):
            tz = self.tz_ist if self._resolve_exchange(exchange) == "NSE" else self.tz_et
            if dt.tzinfo is None:
                # If naive, assume UTC and convert to local exchange timezone
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(tz).date()
        if isinstance(dt, date):
            return dt
        if isinstance(dt, str):
            return date.fromisoformat(dt[:10])
        raise TypeError(f"Cannot convert type {type(dt)} to date")

    def check_coverage(self, d: date, exchange: str = "NSE", fail_closed: bool = True) -> bool:
        """Verify whether date falls within the supported calendar coverage window."""
        ex = self._resolve_exchange(exchange)
        start = NSE_COVERAGE_START if ex == "NSE" else NYSE_COVERAGE_START
        end = NSE_COVERAGE_END if ex == "NSE" else NYSE_COVERAGE_END

        if start <= d <= end:
            return True

        if fail_closed:
            raise CalendarCoverageError(
                f"Date {d.isoformat()} is outside supported {ex} calendar coverage window "
                f"({start.isoformat()} to {end.isoformat()}). Cannot extrapolate trading session."
            )
        return False

    def is_trading_day(
        self,
        dt: Union[date, datetime, str],
        exchange: str = "NSE",
        fail_closed: bool = False,
        include_provisional: bool = False,
    ) -> bool:
        """
        Check if the given calendar date is an official confirmed trading day.

        Args:
            dt: Date, datetime, or ISO string to inspect
            exchange: Market or symbol identifier ('NSE', 'BSE', 'NYSE', 'AAPL', etc.)
            fail_closed: If True, raises CalendarCoverageError when outside verified coverage window
            include_provisional: If True, considers provisional 2027 holidays

        Returns:
            True if date is a weekday and not an exchange holiday (or has a special session).
        """
        d = self._to_date(dt, exchange=exchange)
        ex = self._resolve_exchange(exchange)

        # Check coverage
        if fail_closed:
            self.check_coverage(d, exchange=ex, fail_closed=True)

        # Special session check (e.g. Diwali Muhurat trading on a weekend)
        if ex == "NSE" and is_nse_special_session(d):
            return True

        # Normal weekend filter
        if d.weekday() >= 5:  # Saturday=5, Sunday=6
            return False

        # Holiday filter
        if ex == "NSE":
            return not is_nse_holiday(d, include_provisional=include_provisional)
        else:
            return not is_us_holiday(d)

    def get_trading_days(
        self,
        start_date: Union[date, datetime, str],
        end_date: Union[date, datetime, str],
        exchange: str = "NSE",
        fail_closed: bool = False,
    ) -> List[date]:
        """
        Return all official trading days between start_date and end_date (inclusive).

        Args:
            start_date: Start date (inclusive)
            end_date: End date (inclusive)
            exchange: Market or symbol identifier
            fail_closed: If True, raises CalendarCoverageError when dates exceed coverage

        Returns:
            Sorted list of trading date objects.
        """
        d_start = self._to_date(start_date, exchange=exchange)
        d_end = self._to_date(end_date, exchange=exchange)
        if d_start > d_end:
            return []

        trading_days: List[date] = []
        curr = d_start
        while curr <= d_end:
            if self.is_trading_day(curr, exchange=exchange, fail_closed=fail_closed):
                trading_days.append(curr)
            curr += timedelta(days=1)

        return trading_days

    def get_horizon_session(
        self,
        as_of: Union[date, datetime, str],
        n_sessions: int,
        exchange: str = "NSE",
        fail_closed: bool = False,
    ) -> date:
        """
        Resolve the exact trading date $n$ sessions forward or backward from `as_of`.

        Args:
            as_of: Reference date or datetime
            n_sessions: Number of trading sessions (+n forward, -n backward, 0 for current/next)
            exchange: Market or symbol identifier
            fail_closed: If True, raises CalendarCoverageError when dates exceed coverage

        Returns:
            date object of the resolved trading session.
        """
        curr = self._to_date(as_of, exchange=exchange)

        if n_sessions == 0:
            while not self.is_trading_day(curr, exchange=exchange, fail_closed=fail_closed):
                curr += timedelta(days=1)
            return curr

        step = 1 if n_sessions > 0 else -1
        remaining = abs(n_sessions)

        while remaining > 0:
            curr += timedelta(days=step)
            if self.is_trading_day(curr, exchange=exchange, fail_closed=fail_closed):
                remaining -= 1

        return curr

    def get_next_trading_day(
        self,
        dt: Union[date, datetime, str],
        exchange: str = "NSE",
        fail_closed: bool = False,
    ) -> date:
        """Return the strictly next trading day after `dt`."""
        return self.get_horizon_session(dt, 1, exchange=exchange, fail_closed=fail_closed)

    def get_previous_trading_day(
        self,
        dt: Union[date, datetime, str],
        exchange: str = "NSE",
        fail_closed: bool = False,
    ) -> date:
        """Return the strictly previous trading day before `dt`."""
        return self.get_horizon_session(dt, -1, exchange=exchange, fail_closed=fail_closed)

    def get_session_open_close(
        self,
        dt: Union[date, datetime, str],
        exchange: str = "NSE",
    ) -> Tuple[datetime, datetime]:
        """
        Return the session open and close datetime objects localized to the exchange timezone.
        """
        d = self._to_date(dt, exchange=exchange)
        ex = self._resolve_exchange(exchange)

        if ex == "NSE":
            tz = self.tz_ist
            special = is_nse_special_session(d)
            if special:
                open_t, close_t = special
                return datetime.combine(d, open_t, tzinfo=tz), datetime.combine(d, close_t, tzinfo=tz)
            open_dt = datetime.combine(d, time(9, 15), tzinfo=tz)
            close_dt = datetime.combine(d, time(15, 30), tzinfo=tz)
            return open_dt, close_dt
        else:
            tz = self.tz_et
            open_dt = datetime.combine(d, time(9, 30), tzinfo=tz)
            if is_us_early_close(d):
                close_dt = datetime.combine(d, time(13, 0), tzinfo=tz)
            else:
                close_dt = datetime.combine(d, time(16, 0), tzinfo=tz)
            return open_dt, close_dt

    def is_market_open(
        self,
        market_or_symbol: str = "us",
        dt: Optional[datetime] = None,
    ) -> bool:
        """Check whether market is currently in regular trading session."""
        state, _ = get_market_state(market_or_symbol=market_or_symbol, dt=dt)
        return state == "open"


# Canonical global calendar singleton
exchange_calendar = ExchangeCalendar()
