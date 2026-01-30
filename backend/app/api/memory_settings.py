"""Memory settings endpoints."""


from fastapi import APIRouter, HTTPException

from app.services.memory.service import MemoryCategory
from app.services.memory.settings import (
    get_memory_settings,
    update_memory_settings,
)

from .memory_schemas import BudgetUsageResponse, SettingsResponse, SettingsUpdateRequest

router = APIRouter()


@router.get("/settings", response_model=SettingsResponse)
async def get_settings() -> SettingsResponse:
    """Get current memory settings.

    Returns the global memory configuration including enable/disable state
    and per-tier count limits.
    """
    from app.db import get_db

    async for db in get_db():
        settings = await get_memory_settings(db)
        return SettingsResponse(
            enabled=settings.enabled,
            budget_enabled=settings.budget_enabled,
            total_budget=settings.total_budget,
            max_mandates=settings.max_mandates,
            max_guardrails=settings.max_guardrails,
            reference_index_enabled=settings.reference_index_enabled,
        )

    # Fallback if no db available
    return SettingsResponse(
        enabled=True,
        budget_enabled=True,
        total_budget=2000,
        max_mandates=0,
        max_guardrails=0,
        reference_index_enabled=True,
    )


@router.put("/settings", response_model=SettingsResponse)
async def update_settings(request: SettingsUpdateRequest) -> SettingsResponse:
    """Update memory settings.

    Allows enabling/disabling memory injection and adjusting per-tier count limits.
    """
    from app.db import get_db

    async for db in get_db():
        settings = await update_memory_settings(
            db,
            enabled=request.enabled,
            budget_enabled=request.budget_enabled,
            total_budget=request.total_budget,
            max_mandates=request.max_mandates,
            max_guardrails=request.max_guardrails,
            reference_index_enabled=request.reference_index_enabled,
        )
        return SettingsResponse(
            enabled=settings.enabled,
            budget_enabled=settings.budget_enabled,
            total_budget=settings.total_budget,
            max_mandates=settings.max_mandates,
            max_guardrails=settings.max_guardrails,
            reference_index_enabled=settings.reference_index_enabled,
        )

    raise HTTPException(status_code=500, detail="Database unavailable")


@router.get("/budget-usage", response_model=BudgetUsageResponse)
async def get_budget_usage() -> BudgetUsageResponse:
    """Get current budget usage statistics.

    Returns token usage breakdown by category and remaining budget.
    Computes actual usage by calling get_progressive_context internally.
    Also returns counts for coverage tracking.
    """
    from app.services.memory.context_injector import build_progressive_context
    from app.services.memory.service import MemoryScope, get_memory_service

    # Get progressive context for token usage
    context = await build_progressive_context(
        query="budget check",
        scope=MemoryScope.GLOBAL,
    )

    # Get total counts from stats
    memory_svc = get_memory_service(MemoryScope.GLOBAL, None)
    stats = await memory_svc.get_stats()

    # Build category count lookup
    category_counts = {c.category: c.count for c in stats.by_category}
    mandates_total = category_counts.get(MemoryCategory.MANDATE, 0)
    guardrails_total = category_counts.get(MemoryCategory.GUARDRAIL, 0)
    reference_total = category_counts.get(MemoryCategory.REFERENCE, 0)

    if context.budget_usage:
        return BudgetUsageResponse(
            mandates_tokens=context.budget_usage.mandates_tokens,
            guardrails_tokens=context.budget_usage.guardrails_tokens,
            reference_tokens=context.budget_usage.reference_tokens,
            total_tokens=context.budget_usage.total_tokens,
            total_budget=context.budget_usage.total_budget,
            remaining=context.budget_usage.remaining,
            hit_limit=context.budget_usage.hit_limit,
            mandates_injected=len(context.mandates),
            mandates_total=mandates_total,
            guardrails_injected=len(context.guardrails),
            guardrails_total=guardrails_total,
            reference_injected=len(context.reference),
            reference_total=reference_total,
        )

    return BudgetUsageResponse(
        mandates_tokens=0,
        guardrails_tokens=0,
        reference_tokens=0,
        total_tokens=0,
        total_budget=3500,
        remaining=3500,
        hit_limit=False,
        mandates_injected=0,
        mandates_total=mandates_total,
        guardrails_injected=0,
        guardrails_total=guardrails_total,
        reference_injected=0,
        reference_total=reference_total,
    )
