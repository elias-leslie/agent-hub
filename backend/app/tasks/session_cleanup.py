"""Session cleanup background task."""

import logging
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Session, SessionEvent
from app.services.ownership_inventory import (
    query_project_active_specialists,
    query_project_ownership,
)
from app.services.session_live_activity import build_live_activity_response, mark_session_completed

logger = logging.getLogger(__name__)

_HEARTBEAT_PREFIX = "Run your regular heartbeat check."


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
    """Mark only high-confidence reapable sessions as completed."""
    total_cleaned = await cleanup_superseded_persona_heartbeat_sessions(db)
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
