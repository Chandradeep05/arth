"""
ARTH — AI Research & Trading Hub

Main FastAPI application entry point.

Configures:
- CORS for frontend origins
- Trace ID middleware (every request gets a UUID)
- Structured JSON logging
- Lifespan events for DB/Redis initialization
- Exception handlers
- API route registration
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import ORJSONResponse

from app.config import get_settings
from app.core.exceptions import register_exception_handlers
from app.core.logging import get_logger, setup_logging
from app.core.tracing import TraceIDMiddleware
from app.dependencies import close_db, close_redis, init_db, init_redis

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan — initialize and cleanup resources.

    This replaces the deprecated @app.on_event("startup"/"shutdown") pattern.
    """
    settings = get_settings()

    # ── Startup ──
    setup_logging(settings.log_level)
    logger.info(
        "application_starting",
        app_name=settings.app_name,
        environment=settings.app_env.value,
        llm_tier=settings.llm_tier.value,
    )

    # Initialize database
    try:
        await init_db(settings)
    except Exception as e:
        logger.error("database_init_failed", error=str(e))
        # Don't crash — allow degraded operation

    # Initialize Redis
    try:
        await init_redis(settings)
    except Exception as e:
        logger.warning("redis_init_failed", error=str(e))
        # Don't crash — cache misses are acceptable

    logger.info("application_started")

    yield  # Application runs here

    # ── Shutdown ──
    logger.info("application_shutting_down")
    await close_db()
    await close_redis()
    logger.info("application_stopped")


def create_app() -> FastAPI:
    """Factory function to create the FastAPI application."""
    settings = get_settings()

    app = FastAPI(
        title="ARTH — AI Research & Trading Hub",
        description=(
            "Institutional-grade decision-support infrastructure combining real-time "
            "market intelligence, AI-generated research, probabilistic forecasting, "
            "sentiment analysis, and risk detection."
        ),
        version="1.0.0",
        docs_url="/docs" if settings.is_development else None,
        redoc_url="/redoc" if settings.is_development else None,
        default_response_class=ORJSONResponse,
        lifespan=lifespan,
    )

    # Store debug flag for exception handler
    app.state.debug = settings.debug

    # ── Middleware (order matters — last added = first executed) ──

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Trace-ID"],
    )

    # Trace ID (adds UUID to every request)
    app.add_middleware(TraceIDMiddleware)

    # ── Exception Handlers ──
    register_exception_handlers(app)

    # ── Routes ──
    from app.api.v1 import system, market, research, sentiment, risk
    app.include_router(system.router, prefix=settings.api_prefix)
    app.include_router(market.router, prefix=settings.api_prefix)
    app.include_router(research.router, prefix=settings.api_prefix)
    app.include_router(sentiment.router, prefix=settings.api_prefix)
    app.include_router(risk.router, prefix=settings.api_prefix)

    # Root health endpoint (no prefix, for Railway health checks)
    @app.get("/health")
    async def root_health():
        return {
            "status": "healthy",
            "service": "ARTH-api",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    # Root info endpoint
    @app.get("/")
    async def root():
        return {
            "name": "ARTH — AI Research & Trading Hub",
            "version": "1.0.0",
            "status": "operational",
            "docs": "/docs" if settings.is_development else "disabled",
            "health": "/health",
        }

    return app


# Create the app instance
app = create_app()
