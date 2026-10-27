"""Hatchet tasks that advance durable workflow runs and recover stale steps."""

from __future__ import annotations

import logging
from typing import Any

from hatchet_sdk import Context
from pydantic import BaseModel

from app.hatchet_app import hatchet

logger = logging.getLogger(__name__)

ADVANCE_TASK_NAME = "workflow-run-advance"
RECOVERY_TASK_NAME = "workflow-run-recovery"


class AdvanceInput(BaseModel):
    run_id: str


@hatchet.task(name=ADVANCE_TASK_NAME, retries=0, input_validator=AdvanceInput)
async def workflow_run_advance_task(input: AdvanceInput, ctx: Context) -> dict[str, Any]:
    """Execute the next eligible step of one run, commit, and enqueue the next advance."""
    from app.services.workflow_runs.engine import advance_run

    result = await advance_run(input.run_id)
    ctx.log(f"workflow run {input.run_id}: {result}")
    if result.get("next") == "continue":
        await enqueue_advance(input.run_id)
    return result


@hatchet.task(name=RECOVERY_TASK_NAME, input_validator=BaseModel, on_crons=["*/2 * * * *"])
async def workflow_run_recovery_task(input: BaseModel, ctx: Context) -> dict[str, Any]:
    """Charge stale running steps, resume runs whose usage limit reset, and re-enqueue orphaned runs."""
    from app.services.workflow_runs.engine import recover_stale_steps

    run_ids = await recover_stale_steps()
    for run_id in run_ids:
        await enqueue_advance(run_id)
    ctx.log(f"workflow recovery re-enqueued {len(run_ids)} run(s)")
    return {"enqueued": run_ids}


async def enqueue_advance(run_id: str) -> bool:
    """Queue an advance; a failure is logged because the recovery sweep re-enqueues orphaned runs."""
    try:
        await workflow_run_advance_task.aio_run_no_wait(AdvanceInput(run_id=run_id))
        return True
    except Exception:
        logger.warning(
            "could not enqueue workflow run %s; recovery will retry", run_id, exc_info=True
        )
        return False
