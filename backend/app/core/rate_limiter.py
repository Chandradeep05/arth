"""
ARTH — In-Memory Sliding Window Rate Limiter

Provides per-IP rate limiting without Redis dependency.
Designed to protect against:
- Groq API credit burn via /assistant/chat
- Compute abuse via /prediction/forecast and /research/generate
- General brute-force on all endpoints

Uses a sliding window counter per IP address with configurable
limits per endpoint group. Automatically cleans up stale entries.
"""

from __future__ import annotations

import time
from collections import defaultdict
from typing import Dict, List, Optional, Tuple

from fastapi import Request, Response
from fastapi.responses import ORJSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.logging import get_logger

logger = get_logger(__name__)

# ── Rate Limit Configuration ─────────────────────────────────────
# Each group defines: (max_requests, window_seconds)
RATE_LIMITS: Dict[str, Tuple[int, int]] = {
    # Endpoint prefix → (max_requests_per_window, window_seconds)
    "/api/v1/assistant/chat": (10, 60),        # 10 req/min — Groq credits are scarce
    "/api/v1/research/generate": (5, 60),      # 5 req/min — each call burns Groq + RAG
    "/api/v1/prediction/": (10, 60),           # 10 req/min — XGBoost training is CPU-heavy
    "/api/v1/research/index": (3, 60),         # 3 req/min — document ingestion is expensive
}

# Global fallback for all /api/ endpoints not in a specific group
GLOBAL_LIMIT = (60, 60)  # 60 req/min per IP

# Cleanup stale IPs every N seconds
_CLEANUP_INTERVAL = 120.0


class _SlidingWindowCounter:
    """Per-IP sliding window request counter."""

    __slots__ = ("_windows",)

    def __init__(self):
        # key: (ip, endpoint_group) → list of request timestamps
        self._windows: Dict[Tuple[str, str], List[float]] = defaultdict(list)

    def is_allowed(self, ip: str, group: str, max_requests: int, window_seconds: int) -> bool:
        """Check if a request is allowed and record it if so."""
        key = (ip, group)
        now = time.monotonic()
        cutoff = now - window_seconds

        # Remove expired timestamps
        timestamps = self._windows[key]
        self._windows[key] = [t for t in timestamps if t > cutoff]

        if len(self._windows[key]) >= max_requests:
            return False

        self._windows[key].append(now)
        return True

    def get_retry_after(self, ip: str, group: str, window_seconds: int) -> int:
        """Calculate seconds until the oldest request in the window expires."""
        key = (ip, group)
        timestamps = self._windows.get(key, [])
        if not timestamps:
            return 0
        oldest = min(timestamps)
        retry_after = int(window_seconds - (time.monotonic() - oldest)) + 1
        return max(retry_after, 1)

    def cleanup(self):
        """Remove entries with no recent requests."""
        now = time.monotonic()
        stale_keys = []
        for key, timestamps in self._windows.items():
            if not timestamps or (now - max(timestamps)) > 300:
                stale_keys.append(key)
        for key in stale_keys:
            del self._windows[key]


# Module-level singleton
_counter = _SlidingWindowCounter()
_last_cleanup = 0.0


def _get_client_ip(request: Request) -> str:
    """Extract client IP, respecting X-Forwarded-For behind reverse proxies."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        # Take the first IP (original client)
        return forwarded.split(",")[0].strip()
    if request.client:
        return request.client.host
    return "unknown"


def _match_rate_limit(path: str) -> Tuple[str, int, int]:
    """Find the most specific rate limit group for a path."""
    for prefix, (max_req, window) in RATE_LIMITS.items():
        if path.startswith(prefix):
            return prefix, max_req, window
    # Global fallback
    return "global", GLOBAL_LIMIT[0], GLOBAL_LIMIT[1]


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Per-IP sliding window rate limiter.

    Skips rate limiting for:
    - Health check endpoints (/health)
    - Non-API paths (docs, static files)
    - OPTIONS preflight requests
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        global _last_cleanup

        path = request.url.path

        # Skip non-API paths and health checks
        if not path.startswith("/api/") or request.method == "OPTIONS":
            return await call_next(request)

        # Periodic cleanup
        now = time.monotonic()
        if now - _last_cleanup > _CLEANUP_INTERVAL:
            _counter.cleanup()
            _last_cleanup = now

        client_ip = _get_client_ip(request)
        group, max_requests, window_seconds = _match_rate_limit(path)

        if not _counter.is_allowed(client_ip, group, max_requests, window_seconds):
            retry_after = _counter.get_retry_after(client_ip, group, window_seconds)
            logger.warning(
                "rate_limit_exceeded",
                client_ip=client_ip,
                path=path,
                group=group,
                retry_after=retry_after,
            )
            return ORJSONResponse(
                status_code=429,
                content={
                    "error": "rate_limit_exceeded",
                    "message": f"Too many requests. Limit: {max_requests} per {window_seconds}s for this endpoint.",
                    "retry_after_seconds": retry_after,
                },
                headers={"Retry-After": str(retry_after)},
            )

        return await call_next(request)
