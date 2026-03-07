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


@hatchet.task(
    name="session-reaper",
    input_validator=BaseModel,
    on_crons=["*/15 * * * *"],
    execution_timeout="30s",
)
async def session_reaper_task(input: BaseModel, ctx: Context) -> dict[str, Any]:
    """Close sessions stuck in 'active' state."""
    from datetime import UTC, datetime, timedelta

    from sqlalchemy import update

    from app.db import async_session
    from app.models import Session
    from app.services.session_activity import last_activity_expr

    now = datetime.now(UTC)
    reaped_completion = 0
    reaped_stale = 0

    async with async_session() as db:
        last_activity = last_activity_expr()

        # 1. Completion-type sessions active for > 4 hours
        cutoff_4h = now - timedelta(hours=4)
        result = await db.execute(
            update(Session)
            .where(
                Session.status == "active",
                Session.session_type == "completion",
                last_activity < cutoff_4h,
            )
            .values(status="completed")
            .execution_options(synchronize_session="fetch")
        )
        reaped_completion = result.rowcount  # type: ignore[assignment]

        # 2. Any session active for > 24 hours (safety net)
        cutoff_24h = now - timedelta(hours=24)
        result = await db.execute(
            update(Session)
            .where(
                Session.status == "active",
                last_activity < cutoff_24h,
            )
            .values(status="completed")
            .execution_options(synchronize_session="fetch")
        )
        reaped_stale = result.rowcount  # type: ignore[assignment]

        await db.commit()

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
