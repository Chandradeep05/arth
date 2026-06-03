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

    _engine = create_async_engine(
        settings.database_url,
        pool_size=settings.database_pool_size,
        max_overflow=settings.database_max_overflow,
        echo=settings.debug,
        pool_pre_ping=True,  # Verify connections before use
    )
    _session_factory = async_sessionmaker(
        _engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    logger.info("database_initialized", url=settings.database_url.split("@")[-1])


async def close_db() -> None:
    """Close the database engine."""
    global _engine
    if _engine:
        await _engine.dispose()
        logger.info("database_closed")


async def init_redis(settings: Settings) -> None:
    """Initialize the Redis client."""
    global _redis_client
    _redis_client = aioredis.from_url(
        settings.redis_url,
        encoding="utf-8",
        decode_responses=True,
    )
    # Verify connection
    try:
        await _redis_client.ping()
        logger.info("redis_initialized", url=settings.redis_url)
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
