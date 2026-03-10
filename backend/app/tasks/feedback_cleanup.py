"""Scheduled lifecycle cleanup for agent feedback items."""

from __future__ import annotations

from app.db import async_session
from app.services.feedback_storage import (
    archive_stale_feedback_items,
    purge_old_archived_feedback_items,
)


async def cleanup_feedback_lifecycle(
    *,
    archive_after_days: int = 14,
    purge_after_days: int = 90,
    purge_max_vote_count: int = 2,
) -> dict[str, int | str]:
    """Archive stale resolved items and purge old low-signal archived rows."""
    async with async_session() as db:
        archived = await archive_stale_feedback_items(
            db, older_than_days=archive_after_days
        )
        purged = await purge_old_archived_feedback_items(
            db,
            older_than_days=purge_after_days,
            max_vote_count=purge_max_vote_count,
        )
        await db.commit()

    return {"status": "success", "archived": archived, "purged": purged}
