"""Memory selection for review batches."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import DateTime, cast, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.memory_unified import Memory

from ._review_agent_decisions import MIN_COMPACT_REVIEW_CONTENT_CHARS


def _effective_reviewed_at_expr() -> Any:
    source_validated_at = cast(
        func.nullif(Memory.metadata_["source_compact_validated_at"].astext, ""),
        DateTime(timezone=True),
    )
    return func.coalesce(Memory.last_reviewed_at, source_validated_at)


async def select_memories_due_for_review(
    db: AsyncSession,
    *,
    limit: int = 10,
    cadence_days: int = 45,
    force_all: bool = False,
    include_archived: bool = False,
    only_missing_compact: bool = False,
) -> list[Memory]:
    """Select active memories due for rolling review, oldest first."""
    cutoff = datetime.now(UTC) - timedelta(days=cadence_days)
    statuses = ["active", "archived"] if include_archived else ["active"]
    filters: list[Any] = [Memory.status.in_(statuses)]
    if only_missing_compact:
        filters.extend(
            [
                text("coalesce(memories.metadata->>'compact_content', '') = ''"),
                text("memories.metadata->>'compact_reviewed_at' is null"),
                func.length(Memory.content) > MIN_COMPACT_REVIEW_CONTENT_CHARS,
            ]
        )
    if not force_all:
        effective_reviewed_at = _effective_reviewed_at_expr()
        filters.append(or_(effective_reviewed_at.is_(None), effective_reviewed_at < cutoff))
    effective_reviewed_at = _effective_reviewed_at_expr()
    stmt = (
        select(Memory)
        .where(*filters)
        .order_by(effective_reviewed_at.asc().nulls_first(), Memory.created_at.asc())
        .limit(limit)
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


__all__ = ["select_memories_due_for_review"]
