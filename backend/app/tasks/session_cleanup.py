"""Session cleanup background task.

Automatically marks stale sessions as completed based on inactivity.
Each session type has its own timeout threshold.
"""

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import Session

logger = logging.getLogger(__name__)


# Mapping of session types to their timeout settings (in minutes)
def get_session_timeouts() -> dict[str, int]:
    """Get session timeout configuration by type."""
    return {
        "completion": settings.session_timeout_completion,
        "chat": settings.session_timeout_chat,
        "roundtable": settings.session_timeout_roundtable,
        "image_generation": settings.session_timeout_image_generation,
        "agent": settings.session_timeout_agent,
    }


async def cleanup_stale_sessions(db: AsyncSession) -> int:
    """Mark stale sessions as completed.

    Uses batch UPDATE statements to avoid N+1 queries.
    Each session type is updated in a single query.

    Args:
        db: Database session

    Returns:
        Number of sessions marked as completed
    """
    timeouts = get_session_timeouts()
    now = datetime.now(UTC)
    total_cleaned = 0

    for session_type, timeout_minutes in timeouts.items():
        cutoff = now - timedelta(minutes=timeout_minutes)

        # Single UPDATE query per session type - avoids SELECT + UPDATE N+1 pattern
        result = await db.execute(
            update(Session)
            .where(
                Session.session_type == session_type,
                Session.status == "active",
                Session.updated_at < cutoff,
            )
            .values(status="completed")
        )

        rows_updated = result.rowcount
        if rows_updated > 0:
            logger.info(
                f"Auto-completed {rows_updated} stale {session_type} sessions "
                f"(idle > {timeout_minutes}min)"
            )
            total_cleaned += rows_updated

    if total_cleaned > 0:
        await db.commit()
        logger.info(f"Session cleanup complete: {total_cleaned} sessions marked completed")
    else:
        logger.debug("Session cleanup: no stale sessions found")

    return total_cleaned


async def get_stale_session_stats(db: AsyncSession) -> dict[str, int]:
    """Get statistics on stale sessions by type.

    Uses COUNT queries instead of loading all sessions to avoid N+1.

    Returns:
        Dict mapping session_type to count of stale sessions
    """
    timeouts = get_session_timeouts()
    now = datetime.now(UTC)
    stats: dict[str, int] = {}

    for session_type, timeout_minutes in timeouts.items():
        cutoff = now - timedelta(minutes=timeout_minutes)

        # Use COUNT instead of loading all sessions
        result = await db.execute(
            select(func.count(Session.id)).where(
                Session.session_type == session_type,
                Session.status == "active",
                Session.updated_at < cutoff,
            )
        )
        stats[session_type] = result.scalar() or 0

    return stats
