"""Model enrichment sync: fetch external pricing and benchmark data.

The central automation clock dispatches this daily (profile
``static:model_enrichment_sync``); there is no Hatchet cron trigger, so a stray
tick can never cancel the dispatched run. A run that saves nothing fails, so
the automation run records the failure instead of a silent success.
"""

from __future__ import annotations

from typing import Any

from hatchet_sdk import ConcurrencyExpression, ConcurrencyLimitStrategy, Context
from pydantic import BaseModel

from app.hatchet_app import hatchet
from app.workflows.scheduled import EmptyInput


class ModelSyncResult(BaseModel):
    status: str
    enriched: int = 0
    total: int = 0


@hatchet.task(
    name="model-enrichment-sync",
    input_validator=EmptyInput,
    execution_timeout="120s",
    retries=1,
    concurrency=ConcurrencyExpression(
        expression="'model_sync'",
        max_runs=1,
        limit_strategy=ConcurrencyLimitStrategy.CANCEL_NEWEST,
    ),
)
async def model_enrichment_sync_task(input: EmptyInput, ctx: Context) -> dict[str, Any]:
    """Daily model enrichment sync.

    Fetches external benchmark and pricing data, enriches catalog models,
    and stores results in model_enrichments table.
    """
    from app.services.workflow_schedule_registry import is_workflow_schedule_enabled

    if not await is_workflow_schedule_enabled("model_enrichment_sync", automation_run_id=input.automation_run_id):
        ctx.log("Model enrichment sync skipped (schedule disabled)")
        return ModelSyncResult(status="disabled").model_dump()

    ctx.log("Starting model enrichment sync")

    from app.db import async_session
    from app.services.model_enrichment_service import sync_all

    async with async_session() as db:
        result = await sync_all(db)

    out = ModelSyncResult(
        status=result.get("status", "error"),
        enriched=result.get("enriched", 0),
        total=result.get("total", 0),
    )
    if out.status != "success":
        raise RuntimeError(f"Model enrichment sync saved nothing (status={out.status})")
    ctx.log(f"Model sync complete: {out.enriched}/{out.total} enriched")
    return out.model_dump()
