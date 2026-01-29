"""
Database connection and session management.
"""

from collections.abc import AsyncGenerator
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
    """Dependency for getting database sessions."""
    factory = _get_session_factory()
    async with factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
