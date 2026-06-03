"""
Trace ID middleware for request tracing.

Every incoming request is assigned a unique trace ID (UUID4).
This ID propagates through:
- All log entries via structlog contextvars
- Response headers (X-Trace-ID)
- Error responses
- Downstream service calls

This is critical for debugging in production — every error can be
traced through the full log chain.
"""

from __future__ import annotations

import uuid
from typing import Callable

import structlog
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response


class TraceIDMiddleware(BaseHTTPMiddleware):
    """Assigns a unique trace ID to every request."""

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        # Use client-provided trace ID or generate a new one
        trace_id = request.headers.get("X-Trace-ID", str(uuid.uuid4()))

        # Bind trace ID to structlog context for this request
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(
            trace_id=trace_id,
            method=request.method,
            path=str(request.url.path),
        )

        # Store trace_id in request state for access in route handlers
        request.state.trace_id = trace_id

        # Process request
        response = await call_next(request)

        # Add trace ID to response headers
        response.headers["X-Trace-ID"] = trace_id

        return response


def get_trace_id(request: Request) -> str:
    """Extract trace ID from request state."""
    return getattr(request.state, "trace_id", "unknown")
