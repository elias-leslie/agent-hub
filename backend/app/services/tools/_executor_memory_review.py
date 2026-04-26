"""Memory review tool implementation for Agent Hub agents."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, or_, select, text

from app.models.memory_unified import Memory, MemoryReviewRun

logger = logging.getLogger(__name__)


_MAX_TOOL_BATCH_LIMIT = 10
_MIN_COMPACT_REVIEW_CONTENT_CHARS = 240


def _bounded_int(value: int | None, *, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value if value is not None else default)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(maximum, parsed))


def _json(data: dict[str, Any]) -> str:
    return json.dumps(data, separators=(",", ":"), sort_keys=True, default=str)


def _review_filters(
    *,
    cadence_days: int,
    force_all: bool,
    include_archived: bool,
    only_missing_compact: bool,
) -> list[Any]:
    cutoff = datetime.now(UTC) - timedelta(days=cadence_days)
    statuses = ["active", "archived"] if include_archived else ["active"]
    filters: list[Any] = [Memory.status.in_(statuses)]
    if only_missing_compact:
        filters.extend(
            [
                text("coalesce(memories.metadata->>'compact_content', '') = ''"),
                text("memories.metadata->>'compact_reviewed_at' is null"),
                func.length(Memory.content) > _MIN_COMPACT_REVIEW_CONTENT_CHARS,
            ]
        )
    if not force_all:
        filters.append(or_(Memory.last_reviewed_at.is_(None), Memory.last_reviewed_at < cutoff))
    return filters


async def _review_status(
    *,
    cadence_days: int,
    force_all: bool = False,
    include_archived: bool = False,
    only_missing_compact: bool = False,
    latest_runs: int = 3,
) -> str:
    from app.db import async_session

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
                *_review_filters(
                    cadence_days=cadence_days,
                    force_all=force_all,
                    include_archived=include_archived,
                    only_missing_compact=only_missing_compact,
                )
            )
        )
        compact_counts_result = await db.execute(
            select(
                func.count().filter(
                    text("coalesce(memories.metadata->>'compact_content', '') <> ''")
                ),
                func.count().filter(
                    text(
                        "coalesce(memories.metadata->>'compact_content', '') = '' "
                        f"and length(memories.content) > {_MIN_COMPACT_REVIEW_CONTENT_CHARS}"
                    )
                ),
                func.count().filter(
                    text("coalesce(memories.metadata->>'compact_reviewed_at', '') <> ''")
                ),
            )
            .select_from(Memory)
            .where(Memory.status.in_(statuses))
        )
        compact_ready, compact_missing_long, compact_reviewed = compact_counts_result.one()
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
            "force_all": force_all,
            "include_archived": include_archived,
            "only_missing_compact": only_missing_compact,
            "due": int(due_count or 0),
            "compact": {
                "ready": int(compact_ready or 0),
                "missing_long": int(compact_missing_long or 0),
                "reviewed": int(compact_reviewed or 0),
            },
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
    force_all: bool,
    include_archived: bool,
    only_missing_compact: bool,
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
                force_all=force_all,
                include_archived=include_archived,
                only_missing_compact=only_missing_compact,
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
            "force_all": force_all,
            "include_archived": include_archived,
            "only_missing_compact": only_missing_compact,
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
    force_all: bool,
    only_missing_compact: bool,
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
        "force_all": force_all,
        "only_missing_compact": only_missing_compact,
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
    batch_limit: int = 10,
    max_batches: int = 1,
    cadence_days: int = 45,
    reviewer_agent_slug: str = "memory-curator",
    dry_run: bool = False,
    force_all: bool = False,
    include_archived: bool = False,
    only_missing_compact: bool = False,
    schedule_type: str | None = None,
    schedule_value: str | None = None,
    timezone: str = "UTC",
) -> str:
    """Inspect, run, or schedule dedicated memory-curator review batches."""
    batch_limit = _bounded_int(batch_limit, default=10, minimum=1, maximum=_MAX_TOOL_BATCH_LIMIT)
    max_batches = _bounded_int(max_batches, default=1, minimum=1, maximum=20)
    force_all = bool(force_all)
    only_missing_compact = bool(only_missing_compact)
    cadence_days = _bounded_int(
        cadence_days,
        default=45,
        minimum=0 if force_all else 1,
        maximum=365,
    )
    if force_all:
        cadence_days = 0
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
                force_all=force_all,
                include_archived=include_archived,
                only_missing_compact=only_missing_compact,
            )
        if action == "run_due":
            return await _run_due_reviews(
                batch_limit=batch_limit,
                max_batches=max_batches,
                cadence_days=cadence_days,
                reviewer_agent_slug=reviewer_agent_slug,
                dry_run=dry_run,
                force_all=force_all,
                include_archived=include_archived,
                only_missing_compact=only_missing_compact,
            )
        if action == "schedule":
            return await _schedule_reviews(
                batch_limit=batch_limit,
                cadence_days=cadence_days,
                reviewer_agent_slug=reviewer_agent_slug,
                dry_run=dry_run,
                include_archived=include_archived,
                force_all=force_all,
                only_missing_compact=only_missing_compact,
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
