"""Session reaper — close only sessions with hard dead-lane evidence."""

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
    """Close only dead transcript-sync observers with no owner/specialist lane."""
    from datetime import timedelta

    from sqlalchemy import select

    from app.models import Session
    from app.services.session_activity import last_activity_expr
    from app.services.session_live_activity import mark_session_completed

    last_activity = last_activity_expr()

    reaped_completion = 0

    cutoff_1h = now - timedelta(seconds=_TRANSCRIPT_SYNC_REAP_AFTER_SECONDS)
    transcript_sync_query = select(Session).where(
        Session.status == "active",
        last_activity < cutoff_1h,
    )
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
    reaped_stale = len(transcript_sync_sessions)

    await db.commit()
    return reaped_completion, reaped_stale


@hatchet.task(
    name="session-reaper",
    input_validator=BaseModel,
    on_crons=["*/30 * * * *"],
    execution_timeout="30s",
)
async def session_reaper_task(input: BaseModel, ctx: Context) -> dict[str, Any]:
    """Close sessions only when live-lane evidence says they are dead/reapable."""
    from datetime import UTC, datetime

    from app.db import async_session
    from app.services.workflow_schedule_registry import is_workflow_schedule_enabled

    if not await is_workflow_schedule_enabled("session_reaper"):
        ctx.log("Session reaper skipped (schedule disabled)")
        return ReaperResult(status="disabled").model_dump()

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
