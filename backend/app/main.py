"""
ARTH — AI Research & Trading Hub

Main FastAPI application entry point.

Configures:
- CORS for frontend origins
- Trace ID middleware (every request gets a UUID)
- Structured JSON logging
- Lifespan events for DB/Redis initialization
- Self-ping keepalive (prevents Render free-tier cold starts)
- Exception handlers
- API route registration
"""

from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import httpx
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import ORJSONResponse

from app.config import get_settings
from app.core.exceptions import register_exception_handlers
from app.core.logging import get_logger, setup_logging
from app.core.tracing import TraceIDMiddleware
from app.dependencies import close_db, close_redis, init_db, init_redis

logger = get_logger(__name__)

# ── Self-Ping Keepalive ──────────────────────────────────────────
# Render free tier spins down after 15 min of inactivity.
# This background task pings /health every 4 minutes to stay warm.
# Works in tandem with UptimeRobot (external, every 5 min).

SELF_PING_INTERVAL = 4 * 60  # 4 minutes


async def _keepalive_loop():
    """Background task: ping own /health endpoint to prevent cold starts."""
    # Detect own URL — Render sets RENDER_EXTERNAL_URL automatically
    base_url = os.environ.get("RENDER_EXTERNAL_URL", "")
    if not base_url:
        logger.info("keepalive_disabled", reason="RENDER_EXTERNAL_URL not set (local dev)")
        return

    health_url = f"{base_url}/health"
    logger.info("keepalive_started", url=health_url, interval_s=SELF_PING_INTERVAL)

    async with httpx.AsyncClient(timeout=10) as client:
        while True:
            await asyncio.sleep(SELF_PING_INTERVAL)
            try:
                resp = await client.get(health_url)
                logger.debug("keepalive_ping", status=resp.status_code)
            except Exception as e:
                logger.warning("keepalive_ping_failed", error=str(e))


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

    # Start self-ping keepalive (Render free tier anti-sleep)
    keepalive_task = asyncio.create_task(_keepalive_loop())

    logger.info("application_started")

    yield  # Application runs here

    # ── Shutdown ──
    logger.info("application_shutting_down")
    keepalive_task.cancel()
    try:
        await keepalive_task
    except asyncio.CancelledError:
        pass
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
        docs_url="/docs",
        redoc_url="/redoc",
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

    # Root health endpoint (no prefix, for Render health checks + self-ping keepalive)
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
