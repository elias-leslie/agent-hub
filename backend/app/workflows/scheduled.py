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


def _disabled_schedule_result(schedule_id: str) -> dict[str, Any]:
    return {"status": "disabled", "schedule_id": schedule_id}


class CleanupResult(BaseModel):
    status: str
    sessions_cleaned: int = 0


class TierOptimizerResult(BaseModel):
    status: str
    demotions: int = 0
    promotions: int = 0
    self_heals: int = 0
    lifecycle_updated: int = 0


class MemoryCleanupResult(BaseModel):
    status: str
    deleted: int = 0
    retired: int = 0
    consolidated: int = 0
    redundancy_suggestions: int = 0
    skipped: bool = False
    reason: str = ""


class FeedbackCleanupResult(BaseModel):
    status: str
    archived: int = 0
    purged: int = 0


class DataRetentionResult(BaseModel):
    status: str
    request_logs_deleted: int = 0
    usage_stats_deleted: int = 0
    session_events_deleted: int = 0
    memory_injection_metrics_deleted: int = 0


class MemoryGovernanceResult(BaseModel):
    status: str
    active_count: int = 0
    active_agent_count: int = 0
    health_status: str = "healthy"
    issue_count: int = 0
    untargeted_reference_count: int = 0
    missing_reference_summary_count: int = 0
    oversized_policy_count: int = 0
    invalid_trigger_task_type_count: int = 0
    custom_memory_config_agent_count: int = 0
    tool_capabilities_disabled_agent_count: int = 0
    project_index_disabled_agent_count: int = 0
    reference_index_disabled_agent_count: int = 0
    memory_exclusion_agent_count: int = 0


@hatchet.task(
    name="session-cleanup",
    input_validator=EmptyInput,
    on_crons=["*/15 * * * *"],
    execution_timeout="120s",
    concurrency=ConcurrencyExpression(
        expression="'session_cleanup'",
        max_runs=1,
        limit_strategy=ConcurrencyLimitStrategy.CANCEL_IN_PROGRESS,
    ),
)
async def session_cleanup_task(input: EmptyInput, ctx: Context) -> dict[str, Any]:
    from app.db import async_session
    from app.services.workflow_schedule_registry import is_workflow_schedule_enabled
    from app.tasks.session_cleanup import cleanup_stale_sessions

    if not await is_workflow_schedule_enabled("session_cleanup"):
        ctx.log("Session cleanup skipped (schedule disabled)")
        return _disabled_schedule_result("session_cleanup")

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
    from app.services.workflow_schedule_registry import is_workflow_schedule_enabled

    if not await is_workflow_schedule_enabled("tier_optimizer"):
        ctx.log("Tier optimizer skipped (schedule disabled)")
        return _disabled_schedule_result("tier_optimizer")

    result_data = await optimize_tiers()

    lifecycle_update = result_data.get("lifecycle_update", {})
    result = TierOptimizerResult(
        status="success",
        demotions=result_data.get("demotions", 0),
        promotions=result_data.get("promotions", 0),
        self_heals=result_data.get("self_heals", 0),
        lifecycle_updated=lifecycle_update.get("updated", 0),
    )
    ctx.log(
        f"Tier optimization: {result.demotions} demotions, {result.promotions} promotions, "
        f"{result.self_heals} self-heals, {result.lifecycle_updated} scores updated"
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
    from app.services.memory.cleanup_ttl import cleanup_stale_memories
    from app.services.memory.redundancy import find_and_consolidate_redundant
    from app.services.workflow_schedule_registry import is_workflow_schedule_enabled

    if not await is_workflow_schedule_enabled("memory_cleanup"):
        ctx.log("Memory cleanup skipped (schedule disabled)")
        return _disabled_schedule_result("memory_cleanup")

    # Step 1: Graduated retirement (replaces hard delete)
    cleanup_data = await cleanup_stale_memories(ttl_days=90)

    # Step 2: Redundancy detection and consolidation
    redundancy_data: dict[str, Any] = {"consolidated": 0, "suggestions": 0}
    try:
        redundancy_data = await find_and_consolidate_redundant()
    except Exception as e:
        logger.error("Redundancy detection failed: %s", e)

    result = MemoryCleanupResult(
        status="success",
        deleted=cleanup_data.get("deleted", 0),
        retired=cleanup_data.get("retired", 0),
        consolidated=redundancy_data.get("consolidated", 0),
        redundancy_suggestions=redundancy_data.get("suggestions", 0),
        skipped=cleanup_data.get("skipped", False),
        reason=cleanup_data.get("reason", ""),
    )
    ctx.log(
        f"Memory cleanup: retired={result.retired}, consolidated={result.consolidated}, "
        f"suggestions={result.redundancy_suggestions}, skipped={result.skipped}"
    )
    return result.model_dump()


@hatchet.task(
    name="feedback-cleanup",
    input_validator=EmptyInput,
    on_crons=["30 3 * * *"],
    execution_timeout="180s",
    concurrency=ConcurrencyExpression(
        expression="'feedback_cleanup'",
        max_runs=1,
        limit_strategy=ConcurrencyLimitStrategy.CANCEL_IN_PROGRESS,
    ),
)
async def feedback_cleanup_task(input: EmptyInput, ctx: Context) -> dict[str, Any]:
    from app.services.workflow_schedule_registry import is_workflow_schedule_enabled
    from app.tasks.feedback_cleanup import cleanup_feedback_lifecycle

    if not await is_workflow_schedule_enabled("feedback_cleanup"):
        ctx.log("Feedback cleanup skipped (schedule disabled)")
        return _disabled_schedule_result("feedback_cleanup")

    result_data = await cleanup_feedback_lifecycle()
    result = FeedbackCleanupResult(
        status="success",
        archived=int(result_data.get("archived", 0)),
        purged=int(result_data.get("purged", 0)),
    )
    ctx.log(
        f"Feedback cleanup: archived={result.archived}, purged={result.purged}"
    )
    return result.model_dump()


@hatchet.task(
    name="data-retention",
    input_validator=EmptyInput,
    on_crons=["0 4 * * *"],
    execution_timeout="600s",
    concurrency=ConcurrencyExpression(
        expression="'data_retention'",
        max_runs=1,
        limit_strategy=ConcurrencyLimitStrategy.CANCEL_IN_PROGRESS,
    ),
)
async def data_retention_task(input: EmptyInput, ctx: Context) -> dict[str, Any]:
    from app.db import async_session
    from app.services.workflow_schedule_registry import is_workflow_schedule_enabled
    from app.tasks.data_retention import run_data_retention

    if not await is_workflow_schedule_enabled("data_retention"):
        ctx.log("Data retention skipped (schedule disabled)")
        return _disabled_schedule_result("data_retention")

    async with async_session() as db:
        result_data = await run_data_retention(db)

    result = DataRetentionResult(status="success", **result_data)
    ctx.log(
        f"Data retention: request_logs={result.request_logs_deleted}, "
        f"usage_stats={result.usage_stats_deleted}, "
        f"session_events={result.session_events_deleted}, "
        f"memory_injection_metrics={result.memory_injection_metrics_deleted}"
    )
    return result.model_dump()


@hatchet.task(
    name="memory-governance",
    input_validator=EmptyInput,
    on_crons=["15 3 * * *"],
    execution_timeout="180s",
    concurrency=ConcurrencyExpression(
        expression="'memory_governance'",
        max_runs=1,
        limit_strategy=ConcurrencyLimitStrategy.CANCEL_IN_PROGRESS,
    ),
)
async def memory_governance_task(input: EmptyInput, ctx: Context) -> dict[str, Any]:
    from app.db import async_session
    from app.services.memory.governance import collect_memory_governance_snapshot
    from app.services.workflow_schedule_registry import is_workflow_schedule_enabled

    if not await is_workflow_schedule_enabled("memory_governance"):
        ctx.log("Memory governance skipped (schedule disabled)")
        return _disabled_schedule_result("memory_governance")

    async with async_session() as db:
        snapshot = await collect_memory_governance_snapshot(db)

    result = MemoryGovernanceResult(
        status="success",
        active_count=int(snapshot.get("active_count", 0)),
        active_agent_count=int(snapshot.get("active_agent_count", 0)),
        health_status=str(snapshot.get("health_status", "healthy")),
        issue_count=int(snapshot.get("issue_count", 0)),
        untargeted_reference_count=int(snapshot.get("untargeted_reference_count", 0)),
        missing_reference_summary_count=int(snapshot.get("missing_reference_summary_count", 0)),
        oversized_policy_count=int(snapshot.get("oversized_policy_count", 0)),
        invalid_trigger_task_type_count=int(snapshot.get("invalid_trigger_task_type_count", 0)),
        custom_memory_config_agent_count=int(snapshot.get("custom_memory_config_agent_count", 0)),
        tool_capabilities_disabled_agent_count=int(
            snapshot.get("tool_capabilities_disabled_agent_count", 0)
        ),
        project_index_disabled_agent_count=int(
            snapshot.get("project_index_disabled_agent_count", 0)
        ),
        reference_index_disabled_agent_count=int(
            snapshot.get("reference_index_disabled_agent_count", 0)
        ),
        memory_exclusion_agent_count=int(snapshot.get("memory_exclusion_agent_count", 0)),
    )
    ctx.log(
        "Memory governance: "
        f"active={result.active_count} "
        f"agents={result.active_agent_count} "
        f"health={result.health_status} "
        f"issues={result.issue_count} "
        f"untargeted_refs={result.untargeted_reference_count} "
        f"missing_summary={result.missing_reference_summary_count} "
        f"oversized_policy={result.oversized_policy_count} "
        f"invalid_triggers={result.invalid_trigger_task_type_count} "
        f"custom_configs={result.custom_memory_config_agent_count} "
        f"tool_ctx_off={result.tool_capabilities_disabled_agent_count} "
        f"project_index_off={result.project_index_disabled_agent_count} "
        f"reference_index_off={result.reference_index_disabled_agent_count} "
        f"memory_exclusions={result.memory_exclusion_agent_count}"
    )
    return result.model_dump()
