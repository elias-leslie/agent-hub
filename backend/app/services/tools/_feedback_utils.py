"""Shared utilities for feedback tool actions."""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


@asynccontextmanager
async def db_session() -> AsyncGenerator[AsyncSession]:
    """Yield a database session."""
    from app.db import async_session

    async with async_session() as session:
        yield session


async def resolve_id(db: AsyncSession, item_id: str) -> str | None:
    """Resolve a short or full feedback ID to the full UUID."""
    from app.services.feedback_storage import resolve_feedback_id

    return await resolve_feedback_id(db, item_id)


def resolve_verb(status: str) -> str:
    """Return a past-tense label for an update operation."""
    return {"archived": "Archived", "resolved": "Resolved"}.get(status, "Updated")
