"""Memory settings endpoints."""

import logging

from fastapi import APIRouter

from app.services.memory.service import MemoryCategory
from app.services.memory.settings import (
    get_memory_settings,
    update_memory_settings,
)

from .memory_schemas import BudgetUsageResponse, SettingsResponse, SettingsUpdateRequest

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/settings", response_model=SettingsResponse)
async def get_settings() -> SettingsResponse:
    """Get current memory settings.

    Returns the global memory configuration including enable/disable state
    and per-tier count limits.
    """
    from app.db import async_session

    async with async_session() as db:
        settings = await get_memory_settings(db)
        return SettingsResponse(
            enabled=settings.enabled,
            continuity_enabled=settings.continuity_enabled,
            continuity_max_sessions=settings.continuity_max_sessions,
            active_variant=settings.active_variant,
        )


@router.put("/settings", response_model=SettingsResponse)
async def update_settings(request: SettingsUpdateRequest) -> SettingsResponse:
    """Update memory settings.

    Allows enabling/disabling memory injection and adjusting per-tier count limits.
    """
    from app.db import async_session

    async with async_session() as db:
        update_kwargs: dict[str, object] = {
            "enabled": request.enabled,
            "continuity_enabled": request.continuity_enabled,
            "continuity_max_sessions": request.continuity_max_sessions,
        }
        if "active_variant" in request.model_fields_set:
            update_kwargs["active_variant"] = request.active_variant

        settings = await update_memory_settings(db, **update_kwargs)
        return SettingsResponse(
            enabled=settings.enabled,
            continuity_enabled=settings.continuity_enabled,
            continuity_max_sessions=settings.continuity_max_sessions,
            active_variant=settings.active_variant,
        )


@router.get("/llm-config")
async def get_llm_config() -> dict[str, str]:
    """Get current LLM configuration for memory system."""
    from app.services.memory.embedder import EMBEDDING_MODEL

    return {
        "entity_extraction_model": "none (pgvector — no entity extraction)",
        "reranker_model": "none (pgvector cosine similarity)",
        "embedding_model": EMBEDDING_MODEL,
    }


@router.get("/budget-usage", response_model=BudgetUsageResponse)
async def get_budget_usage() -> BudgetUsageResponse:
    """Get current rendered memory usage statistics."""
    from app.services.memory.budget import count_tokens
    from app.services.memory.context_injector import build_progressive_context
    from app.services.memory.continuity_injector import build_continuity_context
    from app.services.memory.service import MemoryScope, get_memory_service

    # Get progressive context for token usage
    context = await build_progressive_context(
        query="budget check",
        scope=MemoryScope.GLOBAL,
    )

    # Get continuity context token estimate
    settings = await get_memory_settings()
    continuity_tokens = 0
    if settings.continuity_enabled:
        try:
            continuity_ctx = await build_continuity_context(
                max_sessions=settings.continuity_max_sessions,
                include_cross_project=False,
                include_live_sessions=True,
                allow_unscoped=True,
            )
            if continuity_ctx.markdown:
                continuity_tokens = count_tokens(continuity_ctx.markdown)
        except Exception:
            logger.debug("Failed to estimate continuity tokens", exc_info=True)

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
            continuity_tokens=continuity_tokens,
            total_tokens=context.budget_usage.total_tokens + continuity_tokens,
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
        continuity_tokens=continuity_tokens,
        total_tokens=continuity_tokens,
        mandates_injected=0,
        mandates_total=mandates_total,
        guardrails_injected=0,
        guardrails_total=guardrails_total,
        reference_injected=0,
        reference_total=reference_total,
    )
