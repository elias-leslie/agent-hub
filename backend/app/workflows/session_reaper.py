"""Session reaper — close sessions stuck in 'active' state.

Runs every 15 minutes to self-heal sessions that were never finalized
due to crashes, timeouts, or bugs in the completion pipeline.
"""

from __future__ import annotations

import logging
from typing import Any

from hatchet_sdk import Context
from pydantic import BaseModel

from app.hatchet_app import hatchet

logger = logging.getLogger(__name__)

_TRANSCRIPT_SYNC_REAP_AFTER_SECONDS = 60 * 60


class ReaperResult(BaseModel):
    status: str
    reaped_completion: int = 0
    reaped_stale: int = 0


def _should_reap_dead_transcript_sync_session(session) -> bool:
    """Return whether a lane-free transcript-sync observer should be auto-closed early."""
    from app.services.session_live_activity import build_live_activity_response

    request_source = str(getattr(session, "request_source", "") or "")
    if not request_source.endswith("transcript-sync"):
        return False
    activity = build_live_activity_response(session)
    if not activity:
        return False
    if activity.get("has_owner_lane") or activity.get("has_specialist_lane"):
        return False
    if activity.get("lifecycle_state") not in {"dead_candidate", "reapable"}:
        return False
    quiet_for = activity.get("quiet_for_seconds")
    return isinstance(quiet_for, int) and quiet_for >= _TRANSCRIPT_SYNC_REAP_AFTER_SECONDS


async def reap_stale_sessions(db, now) -> tuple[int, int]:
    """Close sessions whose last observed activity is beyond the reaper thresholds."""
    from datetime import timedelta

    from sqlalchemy import select

    from app.models import Session
    from app.services.session_activity import last_activity_expr
    from app.services.session_live_activity import mark_session_completed

    last_activity = last_activity_expr()

    cutoff_4h = now - timedelta(hours=4)
    completion_sessions = (
        await db.execute(
            select(Session).where(
                Session.status == "active",
                Session.session_type == "completion",
                last_activity < cutoff_4h,
            )
        )
    ).scalars().all()
    for session in completion_sessions:
        mark_session_completed(
            session,
            summary="Auto-completed by session reaper after 4h inactivity",
            termination_reason="session_reaper_completion_timeout",
        )
    reaped_completion = len(completion_sessions)

    excluded_ids = {session.id for session in completion_sessions}

    cutoff_1h = now - timedelta(seconds=_TRANSCRIPT_SYNC_REAP_AFTER_SECONDS)
    transcript_sync_query = select(Session).where(
        Session.status == "active",
        last_activity < cutoff_1h,
    )
    if excluded_ids:
        transcript_sync_query = transcript_sync_query.where(Session.id.notin_(excluded_ids))
    transcript_sync_candidates = (await db.execute(transcript_sync_query)).scalars().all()
    transcript_sync_sessions = [
        session
        for session in transcript_sync_candidates
        if _should_reap_dead_transcript_sync_session(session)
    ]
    for session in transcript_sync_sessions:
        mark_session_completed(
            session,
            summary="Auto-completed by session reaper after 1h dead transcript-sync inactivity",
            termination_reason="session_reaper_dead_transcript_sync",
        )
    excluded_ids.update(session.id for session in transcript_sync_sessions)

    cutoff_24h = now - timedelta(hours=24)
    stale_query = select(Session).where(
        Session.status == "active",
        last_activity < cutoff_24h,
    )
    if excluded_ids:
        stale_query = stale_query.where(Session.id.notin_(excluded_ids))
    stale_sessions = (await db.execute(stale_query)).scalars().all()
    for session in stale_sessions:
        mark_session_completed(
            session,
            summary="Auto-completed by session reaper after 24h inactivity",
            termination_reason="session_reaper_global_timeout",
        )
    reaped_stale = len(transcript_sync_sessions) + len(stale_sessions)

    await db.commit()
    return reaped_completion, reaped_stale


@hatchet.task(
    name="session-reaper",
    input_validator=BaseModel,
    on_crons=["*/30 * * * *"],
    execution_timeout="30s",
)
async def session_reaper_task(input: BaseModel, ctx: Context) -> dict[str, Any]:
    """Close sessions stuck in 'active' state."""
    from datetime import UTC, datetime

    from app.db import async_session

    now = datetime.now(UTC)

    async with async_session() as db:
        reaped_completion, reaped_stale = await reap_stale_sessions(db, now)

    total = reaped_completion + reaped_stale
    if total > 0:
        logger.info(
            "Session reaper: closed %d completion + %d stale sessions",
            reaped_completion,
            reaped_stale,
        )
    ctx.log(f"Reaper: {reaped_completion} completion, {reaped_stale} stale")
    return ReaperResult(
        status="reaped" if total > 0 else "idle",
        reaped_completion=reaped_completion,
        reaped_stale=reaped_stale,
    ).model_dump()
