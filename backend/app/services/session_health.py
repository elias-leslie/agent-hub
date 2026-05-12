"""Lightweight session health snapshot helpers."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Session
from app.services.llm_errors import RateLimitError


def executing_tool_health_detail(tool_name: str | None) -> str:
    """Return the persisted health label for an active tool execution."""
    return f"executing_tool:{tool_name or 'unknown'}"


def progress_tag_health_detail(has_progress_tags: bool) -> str:
    """Return the persisted health label for live progress-tag compliance."""
    return "progress_tags_present" if has_progress_tags else "progress_tags_missing"


def health_detail_for_error(error: BaseException | str) -> str:
    """Map an execution error to a health detail label."""
    if isinstance(error, RateLimitError):
        return "rate_limited"

    message = str(error).lower()
    if "rate limit" in message or "429" in message:
        return "rate_limited"
    return "model_error"


async def update_session_health(
    db: AsyncSession,
    session_id: str,
    health_detail: str,
    *,
    commit: bool = False,
) -> None:
    """Persist the latest session health snapshot."""
    touched_at = datetime.now(UTC)
    await db.execute(
        update(Session)
        .where(Session.id == session_id)
        .values(health_detail=health_detail, last_activity_at=touched_at)
    )
    if commit:
        await db.commit()
