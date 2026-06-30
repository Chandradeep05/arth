"""
Abstract data adapter with circuit breaker pattern.

This is the MOST critical abstraction in the system. Every data source
(Yahoo Finance, Alpha Vantage, NSE, etc.) implements this interface.

Features:
- Circuit breaker: stops calling a failing API to prevent cascade failures
- Exponential backoff: retries with increasing delays (max 3)
- Response normalization: all adapters return the same data shapes
- Health monitoring: each adapter reports its health status

Why this matters:
Financial data sources are unreliable. Yahoo Finance rate-limits without warning,
Alpha Vantage's free tier allows 25 req/day, NSE/BSE unofficial APIs break randomly.
Without this abstraction, a single source failure crashes the entire dashboard.
"""

from __future__ import annotations

import asyncio
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from app.core.logging import get_logger

logger = get_logger(__name__)


class CircuitState(str, Enum):
    CLOSED = "closed"       # Normal operation
    OPEN = "open"           # Failing, rejecting calls
    HALF_OPEN = "half_open" # Testing if service recovered


@dataclass
class CircuitBreaker:
    """
    Circuit breaker implementation.

    - CLOSED: normal, all calls go through
    - OPEN: service is down, calls are rejected immediately (serves cached data)
    - HALF_OPEN: after timeout, allows one test call to check recovery
    """
    failure_threshold: int = 15       # Failures before opening (was 5 — too aggressive)
    recovery_timeout: float = 30.0    # Seconds before trying again (was 60 — too long)
    half_open_max_calls: int = 3      # Test calls in half-open state (was 1)

    state: CircuitState = CircuitState.CLOSED
    failure_count: int = 0
    last_failure_time: float = 0.0
    half_open_calls: int = 0

    def can_execute(self) -> bool:
        """Check if a call is allowed."""
        if self.state == CircuitState.CLOSED:
            return True

        if self.state == CircuitState.OPEN:
            # Check if recovery timeout has elapsed
            if time.monotonic() - self.last_failure_time >= self.recovery_timeout:
                self.state = CircuitState.HALF_OPEN
                self.half_open_calls = 0
                logger.info("circuit_breaker_half_open")
                return True
            return False

        if self.state == CircuitState.HALF_OPEN:
            return self.half_open_calls < self.half_open_max_calls

        return False

    def record_success(self) -> None:
        """Record a successful call."""
        if self.state == CircuitState.HALF_OPEN:
            self.state = CircuitState.CLOSED
            self.failure_count = 0
            logger.info("circuit_breaker_closed", reason="recovery_confirmed")
        elif self.state == CircuitState.CLOSED:
            self.failure_count = 0

    def record_failure(self) -> None:
        """Record a failed call."""
        self.failure_count += 1
        self.last_failure_time = time.monotonic()

        if self.state == CircuitState.HALF_OPEN:
            self.state = CircuitState.OPEN
            logger.warning("circuit_breaker_reopened", failures=self.failure_count)
        elif self.state == CircuitState.CLOSED and self.failure_count >= self.failure_threshold:
            # Only log transition ONCE — from CLOSED to OPEN
            self.state = CircuitState.OPEN
            logger.warning(
                "circuit_breaker_opened",
                failures=self.failure_count,
                threshold=self.failure_threshold,
            )


@dataclass
class AdapterHealth:
    """Health status of a data adapter."""
    adapter_name: str
    is_healthy: bool
    circuit_state: str
    failure_count: int
    last_success: Optional[datetime] = None
    last_failure: Optional[datetime] = None
    avg_latency_ms: float = 0.0
    total_requests: int = 0
    last_error_message: str = ""


class BaseDataAdapter(ABC):
    """
    Abstract base for all data source adapters.

    Subclasses must implement the abstract methods.
    The base class handles circuit breaking, retries, and health tracking.
    """

    adapter_name: str = "base"
    max_retries: int = 2              # 2 retries with exponential backoff (5s, 10s)
    base_retry_delay: float = 5.0     # 5s base — longer cooldown for Yahoo 429s

    def __init__(self):
        self._circuit = CircuitBreaker()
        self._last_success: Optional[datetime] = None
        self._last_failure: Optional[datetime] = None
        self._last_error_message: str = ""  # Exposed so callers can detect rate limiting
        self._total_requests: int = 0
        self._total_latency: float = 0.0

    async def execute_with_resilience(self, coro, *args, **kwargs) -> Any:
        """
        Execute a data fetch with circuit breaker and retry logic.

        This wraps any adapter method call with:
        1. Circuit breaker check
        2. Exponential backoff retries
        3. Latency tracking
        4. Health status updates
        """
        if not self._circuit.can_execute():
            logger.warning(
                "circuit_breaker_rejected",
                adapter=self.adapter_name,
                state=self._circuit.state.value,
            )
            return None  # Caller should fall back to cache

        last_error = None
        for attempt in range(1, self.max_retries + 1):
            try:
                start = time.monotonic()
                result = await coro(*args, **kwargs)
                latency = (time.monotonic() - start) * 1000

                # Record success
                self._circuit.record_success()
                self._last_success = datetime.now(timezone.utc)
                self._total_requests += 1
                self._total_latency += latency

                logger.debug(
                    "adapter_request_success",
                    adapter=self.adapter_name,
                    attempt=attempt,
                    latency_ms=round(latency, 2),
                )
                return result

            except Exception as e:
                last_error = e
                self._circuit.record_failure()
                self._last_failure = datetime.now(timezone.utc)
                self._last_error_message = str(e)

                # Check if circuit opened mid-retry — stop immediately
                if not self._circuit.can_execute():
                    logger.warning(
                        "adapter_circuit_opened_mid_retry",
                        adapter=self.adapter_name,
                        attempt=attempt,
                        error=str(e),
                    )
                    break

                if attempt < self.max_retries:
                    delay = self.base_retry_delay * (2 ** (attempt - 1))
                    logger.warning(
                        "adapter_request_retry",
                        adapter=self.adapter_name,
                        attempt=attempt,
                        delay=delay,
                        error=str(e),
                    )
                    await asyncio.sleep(delay)
                else:
                    logger.error(
                        "adapter_request_exhausted",
                        adapter=self.adapter_name,
                        attempts=self.max_retries,
                        error=str(e),
                    )

        return None  # All retries exhausted, caller should fall back to cache

    def get_health(self) -> AdapterHealth:
        """Get current health status of this adapter."""
        avg_latency = (
            self._total_latency / self._total_requests
            if self._total_requests > 0
            else 0.0
        )
        return AdapterHealth(
            adapter_name=self.adapter_name,
            is_healthy=self._circuit.state == CircuitState.CLOSED,
            circuit_state=self._circuit.state.value,
            failure_count=self._circuit.failure_count,
            last_success=self._last_success,
            last_failure=self._last_failure,
            avg_latency_ms=round(avg_latency, 2),
            total_requests=self._total_requests,
            last_error_message=self._last_error_message,
        )

    # ── Abstract methods for subclasses ──

    @abstractmethod
    async def get_quote(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Get current stock quote."""
        ...

    @abstractmethod
    async def get_ohlcv(
        self, symbol: str, period: str = "1mo", interval: str = "1d"
    ) -> Optional[List[Dict[str, Any]]]:
        """Get historical OHLCV data."""
        ...

    @abstractmethod
    async def get_company_info(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Get company information and fundamentals."""
        ...

    @abstractmethod
    async def search(self, query: str) -> List[Dict[str, Any]]:
        """Search for stocks by name or symbol."""
        ...

    @abstractmethod
    async def health_check(self) -> bool:
        """Check if the data source is reachable."""
        ...
