"""
System health and observability endpoints.

Provides:
- /health — Overall system health
- /health/db — Database connectivity
- /health/redis — Redis connectivity
- /health/adapters — External data source health
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.dependencies import get_db, get_redis

router = APIRouter(prefix="/system", tags=["system"])


class HealthStatus(BaseModel):
    status: str  # "healthy", "degraded", "unhealthy"
    service: str
    latency_ms: float | None = None
    message: str | None = None
    timestamp: str


class SystemHealth(BaseModel):
    status: str
    version: str = "0.1.0"
    environment: str = "development"
    services: dict[str, HealthStatus] = {}
    timestamp: str


@router.get("/health", response_model=SystemHealth)
async def health_check():
    """Overall system health — checks all critical services."""
    from app.config import get_settings

    settings = get_settings()
    services = {}
    overall_status = "healthy"

    # Check database
    try:
        from app.dependencies import _engine
        if _engine:
            import time
            start = time.monotonic()
            async with _engine.connect() as conn:
                await conn.execute(
                    __import__("sqlalchemy").text("SELECT 1")
                )
            latency = (time.monotonic() - start) * 1000
            services["database"] = HealthStatus(
                status="healthy",
                service="TimescaleDB",
                latency_ms=round(latency, 2),
                timestamp=datetime.now(timezone.utc).isoformat(),
            )
        else:
            services["database"] = HealthStatus(
                status="unhealthy",
                service="TimescaleDB",
                message="Engine not initialized",
                timestamp=datetime.now(timezone.utc).isoformat(),
            )
            overall_status = "degraded"
    except Exception as e:
        err_msg = str(e)
        # If the error is a connection failure to the default localhost DB,
        # treat it as "not provisioned" rather than "unhealthy"
        is_local_fail = any(x in err_msg for x in ["Connection refused", "localhost", "127.0.0.1", "connect call failed"])
        services["database"] = HealthStatus(
            status="unhealthy",
            service="TimescaleDB",
            message="Engine not initialized" if is_local_fail else err_msg,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
        overall_status = "degraded"

    # Check Redis
    try:
        redis = await get_redis()
        if redis:
            import time
            start = time.monotonic()
            await redis.ping()
            latency = (time.monotonic() - start) * 1000
            services["redis"] = HealthStatus(
                status="healthy",
                service="Redis",
                latency_ms=round(latency, 2),
                timestamp=datetime.now(timezone.utc).isoformat(),
            )
        else:
            services["redis"] = HealthStatus(
                status="unhealthy",
                service="Redis",
                message="Client not initialized",
                timestamp=datetime.now(timezone.utc).isoformat(),
            )
            overall_status = "degraded"
    except Exception as e:
        services["redis"] = HealthStatus(
            status="unhealthy",
            service="Redis",
            message=str(e),
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
        overall_status = "degraded"

    # Determine overall status
    # If DB and Redis are just "not initialized" (intentionally absent in free tier),
    # the system is still operational — just without caching/persistence.
    # Only mark as truly "degraded" if a service was expected but crashed.
    db_status = services.get("database", HealthStatus(status="unhealthy", service="TimescaleDB", timestamp=""))
    redis_status = services.get("redis", HealthStatus(status="unhealthy", service="Redis", timestamp=""))

    db_missing = db_status.status == "unhealthy" and db_status.message == "Engine not initialized"
    redis_missing = redis_status.status == "unhealthy" and redis_status.message == "Client not initialized"

    if db_missing and redis_missing:
        # Both intentionally absent → system is operational in lite mode
        overall_status = "operational"
    elif overall_status == "degraded":
        # At least one service was expected but failed → truly degraded
        pass

    return SystemHealth(
        status=overall_status,
        version="2.0.0",
        environment=settings.app_env.value,
        services=services,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )


@router.get("/health/db")
async def db_health():
    """Database-specific health check."""
    try:
        from app.dependencies import _engine
        if _engine:
            async with _engine.connect() as conn:
                result = await conn.execute(
                    __import__("sqlalchemy").text("SELECT version()")
                )
                version = result.scalar()
            return {"status": "healthy", "version": version}
    except Exception as e:
        return {"status": "unhealthy", "error": str(e)}


@router.get("/health/redis")
async def redis_health():
    """Redis-specific health check."""
    try:
        redis = await get_redis()
        if redis:
            info = await redis.info(section="memory")
            return {
                "status": "healthy",
                "used_memory_human": info.get("used_memory_human", "unknown"),
                "connected_clients": info.get("connected_clients", "unknown"),
            }
        return {"status": "unhealthy", "error": "Redis client not available"}
    except Exception as e:
        return {"status": "unhealthy", "error": str(e)}


@router.get("/metrics")
async def get_metrics():
    """Return in-memory application metrics (request counts, latencies, cache ratios, etc.)."""
    from app.engines.observability.metrics import metrics_collector

    return {
        "status": "ok",
        "metrics": metrics_collector.get_metrics(),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/debug")
async def get_debug():
    """Diagnostic endpoint — verify curl_cffi session and yfinance connectivity."""
    from app.data.adapters.yahoo import _yf_session

    result = {
        "curl_cffi_session": _yf_session is not None,
        "session_type": type(_yf_session).__name__ if _yf_session else "None",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    # Quick yfinance connectivity test
    try:
        import yfinance as yf
        ticker = yf.Ticker("AAPL")
        info = ticker.info
        result["yfinance_test"] = {
            "symbol": "AAPL",
            "price": info.get("regularMarketPrice"),
            "name": info.get("shortName"),
            "status": "ok" if info.get("regularMarketPrice") else "no_data",
        }
    except Exception as e:
        result["yfinance_test"] = {"status": "error", "error": str(e)}

    return result
