"""Session cleanup background task.

Automatically marks stale sessions as completed based on inactivity.
Each session type has its own timeout threshold.
"""

import logging
from datetime import datetime, timedelta

from sqlalchemy import select, update
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

    Queries sessions where now() - updated_at > timeout for the session type.
    Sets status='completed' for matching sessions.

    Args:
        db: Database session

    Returns:
        Number of sessions marked as completed
    """
    timeouts = get_session_timeouts()
    now = datetime.utcnow()
    total_cleaned = 0

    for session_type, timeout_minutes in timeouts.items():
        cutoff = now - timedelta(minutes=timeout_minutes)

        # Find stale sessions of this type
        result = await db.execute(
            select(Session).where(
                Session.session_type == session_type,
                Session.status == "active",
                Session.updated_at < cutoff,
            )
        )
        stale_sessions = result.scalars().all()

        if stale_sessions:
            session_ids = [s.id for s in stale_sessions]

            # Mark as completed
            await db.execute(
                update(Session).where(Session.id.in_(session_ids)).values(status="completed")
            )

            logger.info(
                f"Auto-completed {len(session_ids)} stale {session_type} sessions "
                f"(idle > {timeout_minutes}min): {session_ids[:5]}..."
            )
            total_cleaned += len(session_ids)

    if total_cleaned > 0:
        await db.commit()
        logger.info(f"Session cleanup complete: {total_cleaned} sessions marked completed")
    else:
        logger.debug("Session cleanup: no stale sessions found")

    return total_cleaned


async def get_stale_session_stats(db: AsyncSession) -> dict[str, int]:
    """Get statistics on stale sessions by type.

    Returns:
        Dict mapping session_type to count of stale sessions
    """
    timeouts = get_session_timeouts()
    now = datetime.utcnow()
    stats: dict[str, int] = {}

    for session_type, timeout_minutes in timeouts.items():
        cutoff = now - timedelta(minutes=timeout_minutes)

        result = await db.execute(
            select(Session).where(
                Session.session_type == session_type,
                Session.status == "active",
                Session.updated_at < cutoff,
            )
        )
        stale_sessions = result.scalars().all()
        stats[session_type] = len(stale_sessions)

    return stats
