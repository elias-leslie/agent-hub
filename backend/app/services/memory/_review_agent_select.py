"""Memory selection for review batches."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import DateTime, cast, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.memory_unified import Memory

from ._review_agent_decisions import MIN_COMPACT_REVIEW_CONTENT_CHARS
from ._review_agent_prompt import REVIEW_CHECK_KEYS


def _effective_reviewed_at_expr() -> Any:
    source_validated_at = cast(
        func.nullif(Memory.metadata_["source_compact_validated_at"].astext, ""),
        DateTime(timezone=True),
    )
    return func.coalesce(Memory.last_reviewed_at, source_validated_at)


def build_review_filters(
    *,
    cadence_days: int = 45,
    force_all: bool = False,
    include_archived: bool = False,
    only_missing_compact: bool = False,
    only_incomplete_audit: bool = False,
) -> list[Any]:
    """Build the canonical filter set for review status and execution."""
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
    if only_incomplete_audit:
        quoted_keys = ",".join(f"'{key}'" for key in REVIEW_CHECK_KEYS)
        filters.append(
            text(
                "not (coalesce(memories.metadata->'last_review'->'checks', "
                f"'{{}}'::jsonb) ?& array[{quoted_keys}]::text[])"
            )
        )
    if not force_all and not only_incomplete_audit:
        effective_reviewed_at = _effective_reviewed_at_expr()
        filters.append(or_(effective_reviewed_at.is_(None), effective_reviewed_at < cutoff))
    return filters


async def select_memories_due_for_review(
    db: AsyncSession,
    *,
    limit: int = 10,
    cadence_days: int = 45,
    force_all: bool = False,
    include_archived: bool = False,
    only_missing_compact: bool = False,
    only_incomplete_audit: bool = False,
) -> list[Memory]:
    """Select memories matching the canonical review filter, oldest first."""
    effective_reviewed_at = _effective_reviewed_at_expr()
    stmt = (
        select(Memory)
        .where(
            *build_review_filters(
                cadence_days=cadence_days,
                force_all=force_all,
                include_archived=include_archived,
                only_missing_compact=only_missing_compact,
                only_incomplete_audit=only_incomplete_audit,
            )
        )
        .order_by(effective_reviewed_at.asc().nulls_first(), Memory.created_at.asc())
        .limit(limit)
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


__all__ = ["build_review_filters", "select_memories_due_for_review"]
