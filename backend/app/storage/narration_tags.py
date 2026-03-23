"""Storage layer for narration tags — CRUD operations."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.narration_tag import NarrationTag

_NARRATION_TAG_UNIQUE_CONSTRAINT = "uq_narration_tags_task_session_type_content"


def _unique_tag_values(tags: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """Preserve order while collapsing duplicate narration tags."""
    return list(dict.fromkeys(tags))


async def insert_narration_tag(
    db: AsyncSession,
    *,
    task_id: str,
    session_id: str,
    tag_type: str,
    content: str,
) -> NarrationTag:
    """Insert a single narration tag."""
    tag = NarrationTag(
        task_id=task_id,
        session_id=session_id,
        tag_type=tag_type,
        content=content,
    )
    stmt = insert(NarrationTag).values(
        task_id=task_id,
        session_id=session_id,
        tag_type=tag_type,
        content=content,
    ).on_conflict_do_nothing(constraint=_NARRATION_TAG_UNIQUE_CONSTRAINT)
    await db.execute(stmt)
    return tag


async def insert_narration_tags_bulk(
    db: AsyncSession,
    *,
    task_id: str,
    session_id: str,
    tags: list[tuple[str, str]],
) -> list[NarrationTag]:
    """Insert multiple narration tags in one flush.

    tags is a list of (tag_type, content) tuples.
    """
    unique_tags = _unique_tag_values(tags)
    rows = [
        NarrationTag(
            task_id=task_id,
            session_id=session_id,
            tag_type=tag_type,
            content=content,
        )
        for tag_type, content in unique_tags
    ]
    if not rows:
        return []

    stmt = insert(NarrationTag).values(
        [
            {
                "task_id": task_id,
                "session_id": session_id,
                "tag_type": tag_type,
                "content": content,
            }
            for tag_type, content in unique_tags
        ]
    ).on_conflict_do_nothing(constraint=_NARRATION_TAG_UNIQUE_CONSTRAINT)
    await db.execute(stmt)
    return rows


async def get_narration_tags_for_task(
    db: AsyncSession,
    task_id: str,
    *,
    tag_type: str | None = None,
    limit: int = 500,
) -> list[NarrationTag]:
    """Get narration tags for a task, ordered by creation time."""
    stmt = (
        select(NarrationTag)
        .where(NarrationTag.task_id == task_id)
        .order_by(NarrationTag.created_at.asc())
        .limit(limit)
    )
    if tag_type:
        stmt = stmt.where(NarrationTag.tag_type == tag_type)
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def get_narration_tags_for_session(
    db: AsyncSession,
    session_id: str,
    *,
    limit: int = 500,
) -> list[NarrationTag]:
    """Get narration tags for a specific session."""
    stmt = (
        select(NarrationTag)
        .where(NarrationTag.session_id == session_id)
        .order_by(NarrationTag.created_at.asc())
        .limit(limit)
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())
