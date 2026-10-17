"""One central automation clock; legacy profiles are not eligible."""

from typing import Any

from hatchet_sdk import ConcurrencyExpression, ConcurrencyLimitStrategy, Context
from pydantic import BaseModel

from app.hatchet_app import hatchet
from app.services.automation_dispatch import dispatch_due, reconcile_runs, sync_owner_policies


@hatchet.task(
    name="automation-clock",
    input_validator=BaseModel,
    on_crons=["* * * * *"],
    concurrency=ConcurrencyExpression(
        expression="'automation_clock'",
        max_runs=1,
        limit_strategy=ConcurrencyLimitStrategy.CANCEL_NEWEST,
    ),
)
async def automation_clock_task(input: BaseModel, ctx: Context) -> dict[str, Any]:
    policy_synced = await sync_owner_policies()
    admitted = await dispatch_due()
    reconciled = await reconcile_runs()
    ctx.log(f"Automation clock admitted={admitted} reconciled={reconciled} policy_synced={policy_synced}")
    return {"admitted": admitted, "reconciled": reconciled, "policy_synced": policy_synced}
