"""Session cleanup background task.

Automatically marks stale sessions as completed based on inactivity.
Each session type has its own timeout threshold.
"""

import logging
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import Session, SessionEvent
from app.services.session_activity import last_activity_expr
from app.services.session_live_activity import mark_session_completed

logger = logging.getLogger(__name__)

_HEARTBEAT_PREFIX = "Run your regular heartbeat check."


# Mapping of session types to their timeout settings (in minutes)
def get_session_timeouts() -> dict[str, int]:
    """Get session timeout configuration by type."""
    return {
        "completion": settings.session_timeout_completion,
        "chat": settings.session_timeout_chat,
        "roundtable": settings.session_timeout_roundtable,
        "image_generation": settings.session_timeout_image_generation,
        "agent": settings.session_timeout_agent,
        "claude_code": settings.session_timeout_claude_code,
    }


async def _query_active_persona_heartbeat_sessions(
    db: AsyncSession,
) -> list[SimpleNamespace]:
    rows = (
        await db.execute(
            select(Session.id, Session.created_at)
            .where(
                Session.status == "active",
                Session.agent_slug == "persona",
                Session.session_type == "completion",
                select(SessionEvent.id)
                .where(
                    SessionEvent.session_id == Session.id,
                    SessionEvent.event_type == "user_message",
                    SessionEvent.content.like(f"{_HEARTBEAT_PREFIX}%"),
                )
                .correlate(Session)
                .exists(),
            )
            .order_by(Session.created_at.desc())
        )
    ).all()
    return [SimpleNamespace(id=row.id, created_at=row.created_at) for row in rows]


async def _latest_completed_persona_heartbeat_at(db: AsyncSession) -> datetime | None:
    result = await db.execute(
        select(func.max(Session.created_at)).where(
            Session.status == "completed",
            Session.agent_slug == "persona",
            Session.session_type == "completion",
            select(SessionEvent.id)
            .where(
                SessionEvent.session_id == Session.id,
                SessionEvent.event_type == "user_message",
                SessionEvent.content.like(f"{_HEARTBEAT_PREFIX}%"),
            )
            .correlate(Session)
            .exists(),
        )
    )
    return result.scalar_one_or_none()


async def cleanup_superseded_persona_heartbeat_sessions(db: AsyncSession) -> int:
    """Mark interrupted heartbeat sessions completed when a newer heartbeat supersedes them."""
    latest_completed_at = await _latest_completed_persona_heartbeat_at(db)
    active_sessions = await _query_active_persona_heartbeat_sessions(db)
    if not active_sessions:
        return 0

    superseded_ids: list[str] = []
    if latest_completed_at is not None:
        superseded_ids.extend(
            str(row.id) for row in active_sessions if row.created_at < latest_completed_at
        )

    remaining_active = [row for row in active_sessions if str(row.id) not in set(superseded_ids)]
    if len(remaining_active) > 1:
        superseded_ids.extend(str(row.id) for row in remaining_active[1:])

    if not superseded_ids:
        return 0

    rows = (
        await db.execute(select(Session).where(Session.id.in_(sorted(set(superseded_ids)))))
    ).scalars().all()
    for session in rows:
        mark_session_completed(
            session,
            summary="Superseded by newer persona heartbeat",
            termination_reason="superseded_persona_heartbeat",
        )
    rows_updated = len(rows)
    if rows_updated > 0:
        logger.info(
            "Auto-completed %d superseded persona heartbeat session(s)",
            rows_updated,
        )
    return rows_updated


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
    total_cleaned = await cleanup_superseded_persona_heartbeat_sessions(db)

    for session_type, timeout_minutes in timeouts.items():
        cutoff = now - timedelta(minutes=timeout_minutes)
        last_activity = last_activity_expr()
        stale_ids = [
            str(session_id)
            for session_id in (
                await db.execute(
                    select(Session.id).where(
                        Session.session_type == session_type,
                        Session.status == "active",
                        last_activity < cutoff,
                    )
                )
            ).scalars().all()
        ]
        if not stale_ids:
            continue

        rows = (
            await db.execute(
                select(Session).where(
                    Session.id.in_(stale_ids),
                )
            )
        ).scalars().all()
        for session in rows:
            mark_session_completed(
                session,
                summary=f"Auto-completed after {timeout_minutes}m inactivity",
                termination_reason=f"session_cleanup_idle_gt_{timeout_minutes}m",
            )
        rows_updated = len(rows)
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
        last_activity = last_activity_expr()

        # Use COUNT instead of loading all sessions
        result = await db.execute(
            select(func.count(Session.id)).where(
                Session.session_type == session_type,
                Session.status == "active",
                last_activity < cutoff,
            )
        )
        stats[session_type] = result.scalar() or 0

    return stats
