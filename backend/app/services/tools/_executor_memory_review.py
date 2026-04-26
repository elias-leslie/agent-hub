"""Memory review tool implementation for Agent Hub agents."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select

from app.models.memory_unified import Memory, MemoryReviewRun

logger = logging.getLogger(__name__)


def _bounded_int(value: int | None, *, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value if value is not None else default)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(maximum, parsed))


def _json(data: dict[str, Any]) -> str:
    return json.dumps(data, separators=(",", ":"), sort_keys=True, default=str)


async def _review_status(
    *,
    cadence_days: int,
    include_archived: bool = False,
    latest_runs: int = 3,
) -> str:
    from app.db import async_session

    cutoff = datetime.now(UTC) - timedelta(days=cadence_days)
    statuses = ["active", "archived"] if include_archived else ["active"]
    async with async_session() as db:
        status_rows = await db.execute(
            select(Memory.review_status, func.count())
            .where(Memory.status.in_(statuses))
            .group_by(Memory.review_status)
            .order_by(Memory.review_status)
        )
        due_count = await db.scalar(
            select(func.count())
            .select_from(Memory)
            .where(
                Memory.status.in_(statuses),
                (Memory.last_reviewed_at.is_(None)) | (Memory.last_reviewed_at < cutoff),
            )
        )
        runs_result = await db.execute(
            select(MemoryReviewRun)
            .order_by(MemoryReviewRun.started_at.desc())
            .limit(latest_runs)
        )
        runs = list(runs_result.scalars().all())

    return _json(
        {
            "status": "ok",
            "cadence_days": cadence_days,
            "include_archived": include_archived,
            "due": int(due_count or 0),
            "review_status": {
                str(status or "pending"): int(count)
                for status, count in status_rows.all()
            },
            "latest_runs": [
                {
                    "id": str(run.id),
                    "status": run.status,
                    "dry_run": run.dry_run,
                    "reviewer_agent_slug": run.reviewer_agent_slug,
                    "reviewer_model_id": run.reviewer_model_id,
                    "reviewed": run.reviewed_count,
                    "needs_action": run.needs_action_count,
                    "failed": run.failed_count,
                    "started_at": run.started_at.isoformat() if run.started_at else None,
                }
                for run in runs
            ],
        }
    )


async def _run_due_reviews(
    *,
    batch_limit: int,
    max_batches: int,
    cadence_days: int,
    reviewer_agent_slug: str,
    dry_run: bool,
    include_archived: bool,
) -> str:
    from app.db import async_session
    from app.services.memory.review_agent import run_memory_review_batch

    runs: list[dict[str, Any]] = []
    totals = {"reviewed": 0, "needs_action": 0, "failed": 0}
    final_status = "idle"
    session_ids: list[str] = []

    for _ in range(max_batches):
        async with async_session() as db:
            result = await run_memory_review_batch(
                db=db,
                batch_limit=batch_limit,
                cadence_days=cadence_days,
                reviewer_agent_slug=reviewer_agent_slug,
                reviewer_model_id=None,
                dry_run=dry_run,
                include_archived=include_archived,
            )
            await db.commit()

        runs.append(
            {
                "run_id": result.run_id,
                "status": result.status,
                "reviewed": result.reviewed_count,
                "needs_action": result.needs_action_count,
                "failed": result.failed_count,
                "model": result.reviewer_model_id,
                "session_id": result.session_id,
            }
        )
        totals["reviewed"] += result.reviewed_count
        totals["needs_action"] += result.needs_action_count
        totals["failed"] += result.failed_count
        final_status = result.status
        if result.session_id:
            session_ids.append(result.session_id)
        if result.status in {"idle", "failed"}:
            break

    return _json(
        {
            "status": final_status,
            "reviewer_agent_slug": reviewer_agent_slug,
            "batch_limit": batch_limit,
            "max_batches": max_batches,
            "dry_run": dry_run,
            "include_archived": include_archived,
            "totals": totals,
            "runs": runs,
            "session_ids": session_ids,
        }
    )


async def _schedule_reviews(
    *,
    batch_limit: int,
    cadence_days: int,
    reviewer_agent_slug: str,
    dry_run: bool,
    include_archived: bool,
    schedule_type: str | None,
    schedule_value: str | None,
    timezone: str,
) -> str:
    if not schedule_type or not schedule_value:
        return _json(
            {
                "status": "error",
                "error": "schedule_type and schedule_value required for schedule",
            }
        )

    from app.services.tools._executor_scheduling import schedule_job

    payload = {
        "batch_limit": batch_limit,
        "cadence_days": cadence_days,
        "reviewer_agent_slug": reviewer_agent_slug,
        "dry_run": dry_run,
        "include_archived": include_archived,
    }
    result = await schedule_job(
        name="Memory quality review",
        schedule_type=schedule_type,
        schedule_value=schedule_value,
        payload_message=_json(payload),
        payload_type="memory_review",
        delivery="none",
        timezone=timezone,
    )
    return _json({"status": "scheduled" if not result.startswith("Error") else "error", "result": result})


async def review_memory_system(
    action: str = "status",
    batch_limit: int = 20,
    max_batches: int = 1,
    cadence_days: int = 45,
    reviewer_agent_slug: str = "memory-curator",
    dry_run: bool = False,
    include_archived: bool = False,
    schedule_type: str | None = None,
    schedule_value: str | None = None,
    timezone: str = "UTC",
) -> str:
    """Inspect, run, or schedule dedicated memory-curator review batches."""
    batch_limit = _bounded_int(batch_limit, default=20, minimum=1, maximum=25)
    max_batches = _bounded_int(max_batches, default=1, minimum=1, maximum=20)
    cadence_days = _bounded_int(cadence_days, default=45, minimum=1, maximum=365)
    reviewer_agent_slug = (reviewer_agent_slug or "memory-curator").strip()
    if reviewer_agent_slug != "memory-curator":
        return _json(
            {
                "status": "error",
                "error": "memory review must use reviewer_agent_slug=memory-curator",
            }
        )

    try:
        if action == "status":
            return await _review_status(
                cadence_days=cadence_days,
                include_archived=include_archived,
            )
        if action == "run_due":
            return await _run_due_reviews(
                batch_limit=batch_limit,
                max_batches=max_batches,
                cadence_days=cadence_days,
                reviewer_agent_slug=reviewer_agent_slug,
                dry_run=dry_run,
                include_archived=include_archived,
            )
        if action == "schedule":
            return await _schedule_reviews(
                batch_limit=batch_limit,
                cadence_days=cadence_days,
                reviewer_agent_slug=reviewer_agent_slug,
                dry_run=dry_run,
                include_archived=include_archived,
                schedule_type=schedule_type,
                schedule_value=schedule_value,
                timezone=timezone,
            )
    except Exception as exc:
        logger.exception("review_memory_system failed")
        return _json({"status": "error", "error": str(exc)})

    return _json(
        {
            "status": "error",
            "error": "unknown action; use status/run_due/schedule",
        }
    )
