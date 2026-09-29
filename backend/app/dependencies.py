"""
Dependency injection for database and Redis connections.

Uses FastAPI's dependency injection system to provide:
- Async SQLAlchemy sessions (per-request)
- Redis client (singleton)
- Settings (cached singleton)
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncGenerator

import redis.asyncio as aioredis
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import Settings, get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)

# ── Module-level singletons (initialized in lifespan) ──
_engine = None
_session_factory = None
_redis_client: aioredis.Redis | None = None


async def init_db(settings: Settings) -> None:
    """Initialize the async database engine and session factory."""
    global _engine, _session_factory

    db_url = settings.database_url
    if not db_url:
        logger.warning("database_skipped", reason="DATABASE_URL not set")
        return

    # Normalize driver scheme for create_async_engine
    if db_url.startswith("postgres://"):
        db_url = "postgresql+asyncpg://" + db_url[len("postgres://"):]
    elif db_url.startswith("postgresql://"):
        db_url = "postgresql+asyncpg://" + db_url[len("postgresql://"):]
    elif not db_url.startswith("postgresql+asyncpg://"):
        import re
        db_url = re.sub(r"^postgresql\+\w+://", "postgresql+asyncpg://", db_url)

    # Supabase / cloud SSL options: SQLAlchemy + asyncpg expects ssl in connect_args
    connect_args = {}
    if "sslmode=" in db_url:
        import urllib.parse
        parsed = urllib.parse.urlsplit(db_url)
        q_params = urllib.parse.parse_qs(parsed.query)
        sslmode = q_params.pop("sslmode", ["require"])[0]
        new_query = urllib.parse.urlencode(q_params, doseq=True)
        db_url = urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, parsed.path, new_query, parsed.fragment))
        if sslmode in ("require", "verify-ca", "verify-full"):
            connect_args["ssl"] = "require"
    elif "supabase.co" in db_url:
        connect_args["ssl"] = "require"

    _engine = create_async_engine(
        db_url,
        pool_size=settings.database_pool_size,
        max_overflow=settings.database_max_overflow,
        echo=settings.debug,
        pool_pre_ping=True,  # Verify connections before use
        connect_args=connect_args,
    )
    _session_factory = async_sessionmaker(
        _engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    logger.info("database_initialized", url=db_url.split("@")[-1] if "@" in db_url else "localhost")


async def close_db() -> None:
    """Close the database engine."""
    global _engine
    if _engine:
        await _engine.dispose()
        logger.info("database_closed")


async def init_redis(settings: Settings) -> None:
    """
    Initialize the Redis client.
    Supports Upstash Redis (Phase 3 persistent store) with fallback to standard Redis URL.
    """
    global _redis_client
    target_url = settings.upstash_redis_url or settings.redis_url
    if not target_url:
        logger.info("redis_disabled", reason="No redis URL configured")
        return

    _redis_client = aioredis.from_url(
        target_url,
        encoding="utf-8",
        decode_responses=True,
    )
    # Verify connection
    try:
        await _redis_client.ping()
        logger.info("redis_initialized", url=target_url.split("@")[-1])
        
        # Connect outcome_tracker singleton to Redis
        try:
            from app.engines.prediction.outcome_tracker import outcome_tracker
            outcome_tracker.set_redis(_redis_client)
        except Exception as e:
            logger.warning("outcome_tracker_redis_init_failed", error=str(e))
    except Exception as e:
        logger.warning("redis_connection_failed", error=str(e))
        _redis_client = None


async def close_redis() -> None:
    """Close the Redis client."""
    global _redis_client
    if _redis_client:
        await _redis_client.close()
        logger.info("redis_closed")


# ── FastAPI Dependencies ──

async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Provide an async database session per request."""
    if _session_factory is None:
        raise RuntimeError("Database not initialized. Call init_db() first.")
    async with _session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def get_redis() -> aioredis.Redis | None:
    """Provide the Redis client. Returns None if Redis is unavailable."""
    return _redis_client


def get_config() -> Settings:
    """Provide the application settings."""
    return get_settings()
