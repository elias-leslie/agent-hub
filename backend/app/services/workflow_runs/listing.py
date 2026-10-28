"""Recent workflow runs for the list page: state, goal, step counts, activity and summed attempt usage."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Session, WorkflowStep

_FLAGGED_OUTCOMES = ("refused", "substituted", "usage_limit", "interrupted")


def _cost_of(usage: dict[str, Any]) -> float | None:
    """The attempt's reported cost (agent_hub: cost_usd, claude_code: total_cost_usd); None when unreported."""

    for key in ("cost_usd", "total_cost_usd"):
        value = usage.get(key)
        if isinstance(value, int | float):
            return float(value)
    return None


_TOKEN_PARTS = ("input_tokens", "cache_read_tokens", "cache_write_tokens", "output_tokens")


def _tokens_of(usage: dict[str, Any]) -> int | None:
    """total_tokens when the executor reported it, else the sum of the token parts it did report."""

    if isinstance(usage.get("total_tokens"), int):
        return usage["total_tokens"]
    parts = [usage[k] for k in _TOKEN_PARTS if isinstance(usage.get(k), int)]
    return sum(parts) if parts else None


def _usage_totals(attempts: list[dict[str, Any]]) -> dict[str, Any]:
    # Unknown is not zero: tokens/cost stay null when no attempt reported them.
    tokens = [t for t in (_tokens_of(a["usage"]) for a in attempts) if t is not None]
    costs = [c for c in (_cost_of(a["usage"]) for a in attempts) if c is not None]
    return {
        "total_tokens": sum(tokens) if tokens else None,
        "cost_usd": sum(costs) if costs else None,
        "cost_reported_attempts": len(costs),
    }


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
                "pause_reason": (meta.get("pause") or {}).get("reason"),
                "failure": meta.get("failure"),
                "created_at": run.created_at.isoformat() if run.created_at else None,
                "last_activity_at": run.last_activity_at.isoformat() if run.last_activity_at else None,
                "step_total": sum(counts.values()),
                "step_counts": counts,
                "attempt_count": len(history),
                "flagged_attempts": sum(1 for a in history if a["outcome"].get("kind") in _FLAGGED_OUTCOMES),
                "served_models": list(dict.fromkeys(m for a in history for m in a["served"])),
                **_usage_totals(history),
            }
        )
    return {"runs": items, "total": total, "limit": limit, "offset": offset}
