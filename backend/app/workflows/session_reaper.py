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


class ReaperResult(BaseModel):
    status: str
    reaped_completion: int = 0
    reaped_stale: int = 0


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

    cutoff_24h = now - timedelta(hours=24)
    stale_query = select(Session).where(
        Session.status == "active",
        last_activity < cutoff_24h,
    )
    if completion_sessions:
        stale_query = stale_query.where(
            Session.id.notin_([session.id for session in completion_sessions])
        )
    stale_sessions = (await db.execute(stale_query)).scalars().all()
    for session in stale_sessions:
        mark_session_completed(
            session,
            summary="Auto-completed by session reaper after 24h inactivity",
            termination_reason="session_reaper_global_timeout",
        )
    reaped_stale = len(stale_sessions)

    await db.commit()
    return reaped_completion, reaped_stale


@hatchet.task(
    name="session-reaper",
    input_validator=BaseModel,
    on_crons=["*/15 * * * *"],
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
