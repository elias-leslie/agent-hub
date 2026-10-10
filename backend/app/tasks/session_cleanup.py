"""Session cleanup background task."""

import logging
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Session
from app.services.ownership_inventory import (
    query_project_active_specialists,
    query_project_ownership,
)
from app.services.session_live_activity import build_live_activity_response, mark_session_completed

logger = logging.getLogger(__name__)

def _owner_lane_blocks_reap(owner: object) -> bool:
    """Return whether an ownership row represents real lane backing that should block reaping."""
    branch = getattr(owner, "branch", None)
    if isinstance(branch, str) and branch.strip():
        return True

    working_dir = getattr(owner, "working_dir", None)
    return isinstance(working_dir, str) and bool(working_dir) and Path(working_dir).exists()


def _blocking_owner_session_ids(owners: list[object]) -> set[str]:
    """Return owner session ids whose lane backing is still present."""
    blocking: set[str] = set()
    for owner in owners:
        session_id = getattr(owner, "session_id", None)
        if not session_id or not _owner_lane_blocks_reap(owner):
            continue
        blocking.add(str(session_id))
    return blocking


async def cleanup_stale_sessions(db: AsyncSession) -> int:
    """Mark only high-confidence reapable sessions as completed."""
    total_cleaned = 0
    active_sessions = (
        await db.execute(
            select(Session).where(Session.status == "active").order_by(Session.created_at.desc())
        )
    ).scalars().all()

    project_ids = sorted({session.project_id for session in active_sessions if session.project_id})
    owner_session_ids: set[str] = set()
    specialist_session_ids: set[str] = set()
    for project_id in project_ids:
        owner_session_ids.update(_blocking_owner_session_ids(await query_project_ownership(db, project_id)))
        specialist_session_ids.update(
            str(spec.session_id)
            for spec in await query_project_active_specialists(db, project_id)
            if getattr(spec, "session_id", None)
        )

    for session in active_sessions:
        live_activity = build_live_activity_response(
            session,
            has_owner_lane=session.id in owner_session_ids,
            has_specialist_lane=session.id in specialist_session_ids,
        )
        if not live_activity or not live_activity.get("reapable"):
            continue
        reason = str(live_activity.get("reapable_reason") or "session_reapable")
        mark_session_completed(
            session,
            summary="Auto-reaped stale session",
            termination_reason=reason,
        )
        total_cleaned += 1

    if total_cleaned > 0:
        await db.commit()
        logger.info(f"Session cleanup complete: {total_cleaned} sessions marked completed")
    else:
        logger.debug("Session cleanup: no stale sessions found")

    return total_cleaned


async def get_stale_session_stats(db: AsyncSession) -> dict[str, int]:
    """Return reapable-session counts by type."""
    sessions = (
        await db.execute(select(Session).where(Session.status == "active"))
    ).scalars().all()
    owner_session_ids: set[str] = set()
    specialist_session_ids: set[str] = set()
    for project_id in sorted({session.project_id for session in sessions if session.project_id}):
        owner_session_ids.update(_blocking_owner_session_ids(await query_project_ownership(db, project_id)))
        specialist_session_ids.update(
            str(spec.session_id)
            for spec in await query_project_active_specialists(db, project_id)
            if getattr(spec, "session_id", None)
        )

    stats: dict[str, int] = {}
    for session in sessions:
        live_activity = build_live_activity_response(
            session,
            has_owner_lane=session.id in owner_session_ids,
            has_specialist_lane=session.id in specialist_session_ids,
        )
        if live_activity and live_activity.get("reapable"):
            session_type = session.session_type or "unknown"
            stats[session_type] = stats.get(session_type, 0) + 1

    return stats
