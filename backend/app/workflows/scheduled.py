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
    pass


class CleanupResult(BaseModel):
    status: str
    sessions_cleaned: int = 0


class TierOptimizerResult(BaseModel):
    status: str
    demotions: int = 0
    promotions: int = 0


class MemoryCleanupResult(BaseModel):
    status: str
    edges_deleted: int = 0
    entities_deleted: int = 0
    duplicates_merged: int = 0


@hatchet.task(
    name="session-cleanup",
    input_validator=EmptyInput,
    on_crons=["*/5 * * * *"],
    execution_timeout="120s",
    concurrency=ConcurrencyExpression(
        expression="'session_cleanup'",
        max_runs=1,
        limit_strategy=ConcurrencyLimitStrategy.CANCEL_IN_PROGRESS,
    ),
)
async def session_cleanup_task(input: EmptyInput, ctx: Context) -> dict[str, Any]:
    from app.db import async_session
    from app.tasks.session_cleanup import cleanup_stale_sessions

    async with async_session() as db:
        cleaned = await cleanup_stale_sessions(db)

    result = CleanupResult(status="success", sessions_cleaned=cleaned)
    ctx.log(f"Session cleanup: {cleaned} sessions marked completed")
    return result.model_dump()


@hatchet.task(
    name="tier-optimizer",
    input_validator=EmptyInput,
    on_crons=["0 2 * * *"],
    execution_timeout="600s",
    concurrency=ConcurrencyExpression(
        expression="'tier_optimizer'",
        max_runs=1,
        limit_strategy=ConcurrencyLimitStrategy.CANCEL_IN_PROGRESS,
    ),
)
async def tier_optimizer_task(input: EmptyInput, ctx: Context) -> dict[str, Any]:
    from app.services.memory.tier_optimizer import optimize_tiers

    result_data = await optimize_tiers()
    result = TierOptimizerResult(
        status="success",
        demotions=result_data.get("demotions", 0),
        promotions=result_data.get("promotions", 0),
    )
    ctx.log(
        f"Tier optimization: {result.demotions} demotions, {result.promotions} promotions"
    )
    return result.model_dump()


@hatchet.task(
    name="memory-cleanup",
    input_validator=EmptyInput,
    on_crons=["0 3 * * 0"],
    execution_timeout="300s",
    concurrency=ConcurrencyExpression(
        expression="'memory_cleanup'",
        max_runs=1,
        limit_strategy=ConcurrencyLimitStrategy.CANCEL_IN_PROGRESS,
    ),
)
async def memory_cleanup_task(input: EmptyInput, ctx: Context) -> dict[str, Any]:
    from app.services.memory.service_cleanup import cleanup_orphaned

    result_data = await cleanup_orphaned("global")
    result = MemoryCleanupResult(
        status="success",
        edges_deleted=result_data.get("edges_deleted", 0),
        entities_deleted=result_data.get("entities_deleted", 0),
        duplicates_merged=result_data.get("duplicates_merged", 0),
    )
    ctx.log(
        f"Memory cleanup: edges={result.edges_deleted} entities={result.entities_deleted} "
        f"dupes={result.duplicates_merged}"
    )
    return result.model_dump()
