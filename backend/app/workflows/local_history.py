"""Scheduled pruning of local agent-harness history (app/services/local_history.py)."""

from __future__ import annotations

from typing import Any

from hatchet_sdk import ConcurrencyExpression, ConcurrencyLimitStrategy, Context

from app.hatchet_app import hatchet
from app.workflows.scheduled import EmptyInput, _disabled_schedule_result


@hatchet.task(
    name="local-history",
    input_validator=EmptyInput,
    # The first runs import every pending Claude Code subagent and delete a backlog thread by thread.
    execution_timeout="3h",
    concurrency=ConcurrencyExpression(
        expression="'local_history'",
        max_runs=1,
        limit_strategy=ConcurrencyLimitStrategy.CANCEL_NEWEST,
    ),
)
async def local_history_task(input: EmptyInput, ctx: Context) -> dict[str, Any]:
    from app.db import async_session
    from app.services.local_history import run_local_history
    from app.services.workflow_schedule_registry import is_workflow_schedule_enabled

    if not await is_workflow_schedule_enabled("local_history", automation_run_id=input.automation_run_id):
        ctx.log("Local history skipped (schedule disabled)")
        return _disabled_schedule_result("local_history")

    async with async_session() as db:
        result = await run_local_history(db)
    ctx.log(f"Local history: {result}")
    return {"status": "success", **result}
