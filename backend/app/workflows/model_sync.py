"""Model enrichment sync — daily cron to fetch external benchmark data.

Runs once daily at 6 AM UTC, fetching external pricing/benchmark data
to enrich DB-backed model catalog rows.
"""

from __future__ import annotations

import logging
from typing import Any

from hatchet_sdk import ConcurrencyExpression, ConcurrencyLimitStrategy, Context
from pydantic import BaseModel

from app.hatchet_app import hatchet

logger = logging.getLogger(__name__)


class ModelSyncResult(BaseModel):
    status: str
    enriched: int = 0
    total: int = 0
    availability_changed: int = 0
    error: str | None = None


@hatchet.task(
    name="model-enrichment-sync",
    input_validator=BaseModel,
    on_crons=["0 6 * * *"],
    execution_timeout="120s",
    retries=1,
    concurrency=ConcurrencyExpression(
        expression="'model_sync'",
        max_runs=1,
        limit_strategy=ConcurrencyLimitStrategy.CANCEL_IN_PROGRESS,
    ),
)
async def model_enrichment_sync_task(input: BaseModel, ctx: Context) -> dict[str, Any]:
    """Daily model enrichment sync.

    Fetches external benchmark and pricing data, enriches catalog models,
    and stores results in model_enrichments table.
    """
    from app.services.workflow_schedule_registry import is_workflow_schedule_enabled

    if not await is_workflow_schedule_enabled("model_enrichment_sync"):
        ctx.log("Model enrichment sync skipped (schedule disabled)")
        return ModelSyncResult(status="disabled").model_dump()

    ctx.log("Starting model enrichment sync")

    try:
        from app.db import async_session
        from app.services.adaptive_model_router import refresh_catalog_model_availability
        from app.services.model_enrichment_service import sync_all

        async with async_session() as db:
            result = await sync_all(db)
            availability_changed = await refresh_catalog_model_availability(db)
            if availability_changed:
                await db.commit()

        out = ModelSyncResult(
            status=result.get("status", "success"),
            enriched=result.get("enriched", 0),
            total=result.get("total", 0),
            availability_changed=availability_changed,
        )
        ctx.log(
            "Model sync complete: "
            f"{out.enriched}/{out.total} enriched, "
            f"{out.availability_changed} availability rows changed"
        )
        return out.model_dump()

    except Exception as e:
        logger.exception("Model enrichment sync failed")
        return ModelSyncResult(
            status="error",
            error=str(e),
        ).model_dump()
