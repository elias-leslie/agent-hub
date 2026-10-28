"""Recent workflow runs for the list page: state, goal, step counts, activity and attempt usage totals split by cost basis."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Session, WorkflowStep

from .usage import usage_totals

_FLAGGED_OUTCOMES = ("refused", "substituted", "usage_limit", "interrupted")


async def list_runs(db: AsyncSession, *, limit: int = 50, offset: int = 0) -> dict[str, Any]:
    """Newest runs first, with step counts by status and totals over the runs' attempts."""

    total = (
        await db.execute(select(func.count()).select_from(Session).where(Session.session_type == "workflow"))
    ).scalar_one()
    runs = (
        (
            await db.execute(
                select(Session)
                .where(Session.session_type == "workflow")
                .order_by(Session.created_at.desc(), Session.id)
                .limit(limit)
                .offset(offset)
            )
        )
        .scalars()
        .all()
    )
    ids = [run.id for run in runs]
    step_counts: dict[str, dict[str, int]] = defaultdict(dict)
    attempts: dict[str, list[dict[str, Any]]] = defaultdict(list)
    if ids:
        for run_id, status, count in await db.execute(
            select(WorkflowStep.run_session_id, WorkflowStep.status, func.count())
            .where(WorkflowStep.run_session_id.in_(ids))
            .group_by(WorkflowStep.run_session_id, WorkflowStep.status)
        ):
            step_counts[run_id][status] = count
        attempt = Session.provider_metadata["workflow_attempt"]
        for parent_id, usage, served, outcome in await db.execute(
            select(
                Session.parent_session_id,
                attempt["usage"],
                attempt["served_models"],
                attempt["outcome"],
            ).where(Session.parent_session_id.in_(ids), attempt.is_not(None))
        ):
            attempts[parent_id].append(
                {
                    "usage": usage if isinstance(usage, dict) else {},
                    "served": served if isinstance(served, list) else [],
                    "outcome": outcome if isinstance(outcome, dict) else {},
                }
            )
    items = []
    for run in runs:
        meta = (run.provider_metadata or {}).get("workflow") or {}
        counts = step_counts.get(run.id, {})
        history = attempts.get(run.id, [])
        items.append(
            {
                "id": run.id,
                "state": meta.get("state"),
                "goal": meta.get("goal"),
                "project_id": run.project_id,
                "launched_by": meta.get("launched_by"),
                "coordinator": meta.get("coordinator"),
                "plan_revision": meta.get("plan_revision", 0),
                "pause_reason": (meta.get("pause") or {}).get("reason"),
                "failure": meta.get("failure"),
                "created_at": run.created_at.isoformat() if run.created_at else None,
                "last_activity_at": run.last_activity_at.isoformat() if run.last_activity_at else None,
                "step_total": sum(counts.values()),
                "step_counts": counts,
                "attempt_count": len(history),
                "flagged_attempts": sum(1 for a in history if a["outcome"].get("kind") in _FLAGGED_OUTCOMES),
                "served_models": list(dict.fromkeys(m for a in history for m in a["served"])),
                **usage_totals(a["usage"] for a in history),
            }
        )
    return {"runs": items, "total": total, "limit": limit, "offset": offset}
