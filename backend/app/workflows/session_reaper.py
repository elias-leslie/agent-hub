"""Session reaper — close sessions stuck in 'active' state.

Self-heals sessions that were never finalized due to crashes, timeouts, or bugs in
the completion pipeline. Its thresholds are owner settings
(app.services.session_close_settings, edited on the Sessions page).
"""

from __future__ import annotations

import logging
from typing import Any

from hatchet_sdk import Context
from pydantic import BaseModel

from app.hatchet_app import hatchet
from app.workflows.scheduled import EmptyInput

logger = logging.getLogger(__name__)



class ReaperResult(BaseModel):
    status: str
    reaped_completion: int = 0
    reaped_stale: int = 0


def _span(minutes: int) -> str:
    return f"{minutes // 60}h" if minutes % 60 == 0 else f"{minutes}m"


def _should_reap_dead_transcript_sync_session(session) -> bool:
    """Return whether a lane-free transcript-sync observer should be auto-closed early."""
    from app.services.session_close_settings import current
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
    return isinstance(quiet_for, int) and quiet_for >= current().transcript_sync_close_after_seconds


async def reap_stale_sessions(db, now, thresholds=None) -> tuple[int, int]:
    """Close sessions whose last observed activity is beyond the reaper thresholds."""
    from datetime import timedelta

    from sqlalchemy import select

    from app.models import Session
    from app.services import session_close_settings
    from app.services.session_activity import last_activity_expr
    from app.services.session_live_activity import mark_session_completed

    thresholds = thresholds or session_close_settings.current()
    last_activity = last_activity_expr()

    completion_minutes = thresholds.completion_close_after_minutes
    completion_cutoff = now - timedelta(minutes=completion_minutes)
    completion_sessions = (
        await db.execute(
            select(Session).where(
                Session.status == "active",
                Session.session_type == "completion",
                last_activity < completion_cutoff,
            )
        )
    ).scalars().all()
    for session in completion_sessions:
        mark_session_completed(
            session,
            summary=f"Auto-completed by session reaper after {_span(completion_minutes)} inactivity",
            termination_reason="session_reaper_completion_timeout",
        )
    reaped_completion = len(completion_sessions)

    excluded_ids = {session.id for session in completion_sessions}

    transcript_sync_cutoff = now - timedelta(seconds=thresholds.transcript_sync_close_after_seconds)
    transcript_sync_query = select(Session).where(
        Session.status == "active",
        last_activity < transcript_sync_cutoff,
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
            summary=f"Auto-completed by session reaper after {_span(thresholds.transcript_sync_close_after_minutes)} dead transcript-sync inactivity",
            termination_reason="session_reaper_dead_transcript_sync",
        )
    excluded_ids.update(session.id for session in transcript_sync_sessions)

    any_minutes = thresholds.any_session_close_after_minutes
    any_cutoff = now - timedelta(minutes=any_minutes)
    stale_query = select(Session).where(
        Session.status == "active",
        Session.session_type != "workflow",  # workflow runs may wait on the owner; the engine closes them
        last_activity < any_cutoff,
    )
    if excluded_ids:
        stale_query = stale_query.where(Session.id.notin_(excluded_ids))
    stale_sessions = (await db.execute(stale_query)).scalars().all()
    for session in stale_sessions:
        mark_session_completed(
            session,
            summary=f"Auto-completed by session reaper after {_span(any_minutes)} inactivity",
            termination_reason="session_reaper_global_timeout",
        )
    reaped_stale = len(transcript_sync_sessions) + len(stale_sessions)

    await db.commit()
    return reaped_completion, reaped_stale


@hatchet.task(
    name="session-reaper",
    input_validator=EmptyInput,
    execution_timeout="30s",
)
async def session_reaper_task(input: EmptyInput, ctx: Context) -> dict[str, Any]:
    """Close sessions stuck in 'active' state."""
    from datetime import UTC, datetime

    from app.db import async_session
    from app.services.workflow_schedule_registry import is_workflow_schedule_enabled

    if not await is_workflow_schedule_enabled("session_reaper", automation_run_id=input.automation_run_id):
        ctx.log("Session reaper skipped (schedule disabled)")
        return ReaperResult(status="disabled").model_dump()

    now = datetime.now(UTC)

    from app.services import session_close_settings

    thresholds = await session_close_settings.load()
    async with async_session() as db:
        reaped_completion, reaped_stale = await reap_stale_sessions(db, now, thresholds)

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
