"""
In-memory observability metrics collector.

Provides lightweight application metrics without requiring Prometheus or
any external dependency. All counters are stored in-process and reset on
restart — this is intentional for Phase 2; persistent metrics come later.

Features:
- Singleton MetricsCollector (module-level instance)
- Thread-safe counters (threading.Lock)
- Per-endpoint request counts and latencies
- Cache hit/miss tracking with computed ratios
- Adapter error tracking by adapter name
- Active WebSocket connection gauge
- reset() method for testing
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict

from app.core.logging import get_logger

logger = get_logger(__name__)


class MetricsCollector:
    """
    Singleton-style in-memory metrics collector.

    Use the module-level ``metrics_collector`` instance rather than
    creating your own.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._start_time = time.monotonic()
        self._started_at = datetime.now(timezone.utc)
        self._init_counters()

    def _init_counters(self) -> None:
        """Initialise / reset all internal counters."""
        self._request_count: Dict[str, int] = defaultdict(int)
        self._total_latency_ms: Dict[str, float] = defaultdict(float)
        self._cache_hits: int = 0
        self._cache_misses: int = 0
        self._adapter_errors: Dict[str, int] = defaultdict(int)
        self._active_ws_connections: int = 0
        self._total_requests: int = 0

    # ── Recording methods ────────────────────────────────────────

    def record_request(
        self,
        endpoint: str,
        latency_ms: float,
        cache_hit: bool = False,
    ) -> None:
        """
        Record an API request.

        Args:
            endpoint: The route path, e.g. ``/api/v1/market/quote``.
            latency_ms: Request processing time in milliseconds.
            cache_hit: Whether the response was served from cache.
        """
        with self._lock:
            self._request_count[endpoint] += 1
            self._total_latency_ms[endpoint] += latency_ms
            self._total_requests += 1
            if cache_hit:
                self._cache_hits += 1
            else:
                self._cache_misses += 1

    def record_adapter_error(self, adapter_name: str) -> None:
        """
        Record a data-adapter error (circuit breaker trip, timeout, etc.).

        Args:
            adapter_name: Identifier for the adapter, e.g. ``yahoo_finance``.
        """
        with self._lock:
            self._adapter_errors[adapter_name] += 1

    def record_ws_connection(self, delta: int = 1) -> None:
        """
        Adjust the active WebSocket connection gauge.

        Args:
            delta: ``+1`` on connect, ``-1`` on disconnect.
        """
        with self._lock:
            self._active_ws_connections = max(0, self._active_ws_connections + delta)

    # ── Query methods ────────────────────────────────────────────

    def get_metrics(self) -> Dict[str, Any]:
        """
        Return a snapshot of all collected metrics.

        Includes computed ratios (cache hit rate, average latencies).
        """
        with self._lock:
            total_cache = self._cache_hits + self._cache_misses
            cache_hit_rate = (
                round(self._cache_hits / total_cache * 100, 2) if total_cache > 0 else 0.0
            )

            # Per-endpoint average latency
            avg_latency_by_endpoint: Dict[str, float] = {}
            for ep, total_lat in self._total_latency_ms.items():
                count = self._request_count.get(ep, 1)
                avg_latency_by_endpoint[ep] = round(total_lat / count, 2)

            uptime_seconds = round(time.monotonic() - self._start_time, 1)

            return {
                "uptime_seconds": uptime_seconds,
                "started_at": self._started_at.isoformat(),
                "total_requests": self._total_requests,
                "request_count_by_endpoint": dict(self._request_count),
                "avg_latency_ms_by_endpoint": avg_latency_by_endpoint,
                "cache": {
                    "hits": self._cache_hits,
                    "misses": self._cache_misses,
                    "hit_rate_pct": cache_hit_rate,
                },
                "adapter_errors": dict(self._adapter_errors),
                "active_ws_connections": self._active_ws_connections,
            }

    # ── Utilities ────────────────────────────────────────────────

    def reset(self) -> None:
        """Reset all counters — useful for testing."""
        with self._lock:
            self._init_counters()
            self._start_time = time.monotonic()
            self._started_at = datetime.now(timezone.utc)
            logger.info("metrics_reset")


# ── Module-level singleton ───────────────────────────────────────
metrics_collector = MetricsCollector()
