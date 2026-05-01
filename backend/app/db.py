"""
Database connection and session management.
"""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from functools import lru_cache
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings


def _get_async_url(url: str) -> str:
    """Convert sync URL to async URL."""
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    return url


@lru_cache
def _get_engine() -> Any:
    """Lazily create async engine (cached)."""
    return create_async_engine(
        _get_async_url(settings.agent_hub_db_url),
        echo=settings.debug,
        pool_pre_ping=True,
        pool_size=settings.agent_hub_db_pool_size,
        max_overflow=settings.agent_hub_db_max_overflow,
        pool_timeout=settings.agent_hub_db_pool_timeout,
        pool_recycle=settings.agent_hub_db_pool_recycle,
    )


@lru_cache
def _get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Lazily create session factory (cached)."""
    return async_sessionmaker(
        _get_engine(),
        class_=AsyncSession,
        expire_on_commit=False,
    )


async def get_db() -> AsyncGenerator[AsyncSession]:
    """Dependency for getting database sessions.

    WARNING: Only use this with FastAPI's Depends() mechanism.
    For manual usage outside of route handlers, use async_session() instead.
    Using `async for db in get_db()` with early return/break causes connection leaks.
    """
    factory = _get_session_factory()
    async with factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


@asynccontextmanager
async def async_session() -> AsyncGenerator[AsyncSession]:
    """Context manager for getting database sessions outside of FastAPI dependencies.

    Use this instead of `async for db in get_db()` to avoid connection leaks.

    Example:
        async with async_session() as db:
            result = await db.execute(query)
    """
    factory = _get_session_factory()
    async with factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
