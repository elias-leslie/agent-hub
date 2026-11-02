"""Scheduled (cron) workflows."""

from __future__ import annotations

import logging
from typing import Any

from hatchet_sdk import (
    ConcurrencyExpression,
    ConcurrencyLimitStrategy,
    Context,
)
from pydantic import BaseModel

from app.hatchet_app import hatchet

logger = logging.getLogger(__name__)


class EmptyInput(BaseModel):
    automation_run_id: str | None = None


def _disabled_schedule_result(schedule_id: str) -> dict[str, Any]:
    return {"status": "disabled", "schedule_id": schedule_id}


class CleanupResult(BaseModel):
    status: str
    sessions_cleaned: int = 0


class DataRetentionResult(BaseModel):
    status: str
    request_logs_deleted: int = 0
    usage_stats_deleted: int = 0
    sessions_archived: int = 0
    session_events_archived: int = 0
    session_events_archive_raw_bytes: int = 0
    session_events_archive_stored_bytes: int = 0
    session_archive_skipped: list[str] = []
    session_archive_failed: list[str] = []
    memory_injection_metrics_deleted: int = 0


@hatchet.task(
    name="session-cleanup",
    input_validator=EmptyInput,
    execution_timeout="120s",
    concurrency=ConcurrencyExpression(
        expression="'session_cleanup'",
        max_runs=1,
        limit_strategy=ConcurrencyLimitStrategy.CANCEL_NEWEST,
    ),
)
async def session_cleanup_task(input: EmptyInput, ctx: Context) -> dict[str, Any]:
    from app.db import async_session
    from app.services.workflow_schedule_registry import is_workflow_schedule_enabled
    from app.tasks.session_cleanup import cleanup_stale_sessions

    if not await is_workflow_schedule_enabled("session_cleanup", automation_run_id=input.automation_run_id):
        ctx.log("Session cleanup skipped (schedule disabled)")
        return _disabled_schedule_result("session_cleanup")

    from app.services import session_close_settings

    await session_close_settings.load()  # the classifier reads this process's copy
    async with async_session() as db:
        cleaned = await cleanup_stale_sessions(db)

    result = CleanupResult(status="success", sessions_cleaned=cleaned)
    ctx.log(f"Session cleanup: {cleaned} sessions marked completed")
    return result.model_dump()


@hatchet.task(
    name="data-retention",
    input_validator=EmptyInput,
    execution_timeout="600s",
    concurrency=ConcurrencyExpression(
        expression="'data_retention'",
        max_runs=1,
        limit_strategy=ConcurrencyLimitStrategy.CANCEL_NEWEST,
    ),
)
async def data_retention_task(input: EmptyInput, ctx: Context) -> dict[str, Any]:
    from app.db import async_session
    from app.services.workflow_schedule_registry import is_workflow_schedule_enabled
    from app.tasks.data_retention import run_data_retention

    if not await is_workflow_schedule_enabled("data_retention", automation_run_id=input.automation_run_id):
        ctx.log("Data retention skipped (schedule disabled)")
        return _disabled_schedule_result("data_retention")

    async with async_session() as db:
        result_data = await run_data_retention(db)

    result = DataRetentionResult(status="success", **result_data)
    from app.services.owner_notice import notify_retention_result

    await notify_retention_result(result.session_archive_failed)
    ctx.log(
        f"Data retention: request_logs={result.request_logs_deleted}, "
        f"usage_stats={result.usage_stats_deleted}, "
        f"sessions_archived={result.sessions_archived} ({result.session_events_archived} events, "
        f"{result.session_events_archive_raw_bytes} -> {result.session_events_archive_stored_bytes} bytes, "
        f"skipped={len(result.session_archive_skipped)}, failed={len(result.session_archive_failed)}), "
        f"memory_injection_metrics={result.memory_injection_metrics_deleted}"
    )
    return result.model_dump()
