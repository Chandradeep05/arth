"""
Custom exception handlers for the ARTH API.

All exceptions are caught and returned with:
- Consistent JSON structure
- Trace ID for debugging
- Appropriate HTTP status codes
- No internal details leaked in production
"""

from __future__ import annotations

from typing import Any, Dict

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import ORJSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.logging import get_logger

logger = get_logger(__name__)


class ARTHException(Exception):
    """Base exception for all ARTH application errors."""

    def __init__(
        self,
        message: str,
        status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail: str | None = None,
    ):
        self.message = message
        self.status_code = status_code
        self.detail = detail
        super().__init__(message)


class DataSourceError(ARTHException):
    """Raised when a data source (Yahoo Finance, etc.) fails."""

    def __init__(self, source: str, message: str):
        super().__init__(
            message=f"Data source '{source}' error: {message}",
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"External data source '{source}' is currently unavailable. Cached data may be served.",
        )


class DataStaleError(ARTHException):
    """Raised when data is stale beyond acceptable thresholds."""

    def __init__(self, data_type: str, age_seconds: int):
        super().__init__(
            message=f"Stale data: {data_type} is {age_seconds}s old",
            status_code=status.HTTP_200_OK,  # Still return data, but flag it
        )


class LLMError(ARTHException):
    """Raised when LLM inference fails."""

    def __init__(self, provider: str, message: str):
        super().__init__(
            message=f"LLM provider '{provider}' error: {message}",
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="AI analysis is temporarily unavailable. Please try again.",
        )


class RateLimitError(ARTHException):
    """Raised when rate limit is exceeded."""

    def __init__(self):
        super().__init__(
            message="Rate limit exceeded",
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many requests. Please wait before trying again.",
        )


class SymbolNotFoundError(ARTHException):
    """Raised when a stock symbol is not found."""

    def __init__(self, symbol: str):
        super().__init__(
            message=f"Symbol '{symbol}' not found",
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Stock symbol '{symbol}' was not found. Check the symbol and try again.",
        )


def _build_error_response(
    request: Request, status_code: int, message: str, detail: str | None = None
) -> Dict[str, Any]:
    """Build consistent error response body."""
    trace_id = getattr(request.state, "trace_id", "unknown")
    return {
        "error": True,
        "message": message,
        "detail": detail or message,
        "trace_id": trace_id,
        "status_code": status_code,
    }


def register_exception_handlers(app: FastAPI) -> None:
    """Register all exception handlers on the FastAPI app."""

    @app.exception_handler(ARTHException)
    async def arth_exception_handler(
        request: Request, exc: ARTHException
    ) -> ORJSONResponse:
        logger.error(
            "application_error",
            error_type=type(exc).__name__,
            message=exc.message,
            status_code=exc.status_code,
        )
        return ORJSONResponse(
            status_code=exc.status_code,
            content=_build_error_response(
                request, exc.status_code, exc.message, exc.detail
            ),
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(
        request: Request, exc: StarletteHTTPException
    ) -> ORJSONResponse:
        return ORJSONResponse(
            status_code=exc.status_code,
            content=_build_error_response(
                request, exc.status_code, str(exc.detail)
            ),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request, exc: RequestValidationError
    ) -> ORJSONResponse:
        logger.warning("validation_error", errors=str(exc.errors()))
        return ORJSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content=_build_error_response(
                request,
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "Validation error",
                str(exc.errors()),
            ),
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(
        request: Request, exc: Exception
    ) -> ORJSONResponse:
        logger.exception("unhandled_error", error=str(exc))
        return ORJSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=_build_error_response(
                request,
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                "Internal server error",
                "An unexpected error occurred. This has been logged for investigation."
                if not getattr(request.app.state, "debug", False)
                else str(exc),
            ),
        )
