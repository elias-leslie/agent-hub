"""Progressive context builder for memory-augmented completions.

Builds the 3-block progressive disclosure context:
- Block 1 (Mandates): Always-inject golden standards
- Block 2 (Guardrails): Type-filtered anti-patterns
- Block 3 (Reference): Auto-inject + triggered references

Extracted from context_injector.py for maintainability.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

from .budget import BudgetUsage, count_tokens
from .context_injector_blocks import (
    get_auto_inject_references_as_search_results,
    get_guardrails,
    get_mandates,
    get_phase_triggered_references_as_search_results,
    get_triggered_references_as_search_results,
)
from .service import MemoryScope, MemorySearchResult
from .settings import get_memory_settings

logger = logging.getLogger(__name__)


@dataclass
class ProgressiveContext:
    """Result of progressive disclosure context retrieval."""

    mandates: list[MemorySearchResult] = field(default_factory=list)
    guardrails: list[MemorySearchResult] = field(default_factory=list)
    reference: list[MemorySearchResult] = field(default_factory=list)
    total_tokens: int = 0
    debug_info: dict[str, Any] = field(default_factory=dict)
    budget_usage: BudgetUsage | None = None

    def get_loaded_uuids(self) -> list[str]:
        """Get all UUIDs that were loaded into context (for usage tracking)."""
        uuids: list[str] = []
        for m in self.mandates:
            if m.uuid:
                uuids.append(m.uuid)
        for g in self.guardrails:
            if g.uuid:
                uuids.append(g.uuid)
        for r in self.reference:
            if r.uuid:
                uuids.append(r.uuid)
        return uuids

    def get_mandate_uuids(self) -> list[str]:
        """Get mandate UUIDs (for citation tracking)."""
        return [m.uuid for m in self.mandates if m.uuid]

    def get_guardrail_uuids(self) -> list[str]:
        """Get guardrail UUIDs (for citation tracking)."""
        return [g.uuid for g in self.guardrails if g.uuid]


async def build_progressive_context(
    query: str,
    scope: MemoryScope = MemoryScope.GLOBAL,
    scope_id: str | None = None,
    include_mandates: bool = True,
    include_guardrails: bool = True,
    include_global: bool = True,
    task_type: str | None = None,
    phase: str | None = None,
) -> ProgressiveContext:
    """
    Build 2-block progressive context (mandates + guardrails).

    Deterministic injection: ALL mandates and guardrails for the scope are injected.
    No scoring, no thresholds - just demotion filtering for mandates.

    Reference items are included when:
    - auto_inject=true on the episode
    - task_type is provided and matches episode's trigger_task_types
    - phase is provided and matches episode's trigger_phases

    Args:
        query: Query for context (unused for mandates/guardrails, kept for API compat)
        scope: Memory scope to query
        scope_id: Project or task ID for scoping
        include_mandates: Whether to include mandates block
        include_guardrails: Whether to include guardrails block
        include_global: Whether to also include global scope when querying project scope
        task_type: Optional task type to trigger type-specific references
        phase: Optional subtask phase to trigger phase-specific references

    Returns:
        ProgressiveContext with mandates, guardrails, and triggered references
    """
    context = ProgressiveContext()

    scopes_to_query: list[tuple[MemoryScope, str | None]] = [(scope, scope_id)]
    if include_global and scope == MemoryScope.PROJECT and scope_id:
        scopes_to_query.append((MemoryScope.GLOBAL, None))

    tasks: list[asyncio.Task[list[MemorySearchResult]]] = []
    task_keys: list[str] = []

    for query_scope, query_scope_id in scopes_to_query:
        if include_mandates:
            tasks.append(
                asyncio.create_task(get_mandates(scope=query_scope, scope_id=query_scope_id))
            )
            task_keys.append(f"mandates_{query_scope.value}")
        if include_guardrails:
            tasks.append(
                asyncio.create_task(get_guardrails(scope=query_scope, scope_id=query_scope_id))
            )
            task_keys.append(f"guardrails_{query_scope.value}")
        tasks.append(
            asyncio.create_task(
                get_auto_inject_references_as_search_results(
                    scope=query_scope, scope_id=query_scope_id
                )
            )
        )
        task_keys.append(f"reference_{query_scope.value}")

    if task_type:
        tasks.append(
            asyncio.create_task(
                get_triggered_references_as_search_results(task_type=task_type, group_id="global")
            )
        )
        task_keys.append("reference_triggered")

    if phase:
        tasks.append(
            asyncio.create_task(
                get_phase_triggered_references_as_search_results(phase=phase, group_id="global")
            )
        )
        task_keys.append("reference_phase_triggered")

    if tasks:
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for key, result in zip(task_keys, results, strict=True):
            if isinstance(result, BaseException):
                logger.warning("Failed to get %s: %s", key, result)
                continue

            block_type = key.split("_")[0]
            existing = getattr(context, block_type, [])

            assert isinstance(result, list)
            result_list: list[MemorySearchResult] = result
            existing_uuids = {r.uuid for r in existing}
            for item in result_list:
                if item.uuid not in existing_uuids:
                    existing.append(item)
                    existing_uuids.add(item.uuid)

            setattr(context, block_type, existing)

    settings = await get_memory_settings()
    budget = BudgetUsage(total_budget=settings.total_budget)

    if not settings.enabled:
        logger.info("Memory injection disabled - returning empty context")
        context.mandates = []
        context.guardrails = []
        context.budget_usage = budget
        context.total_tokens = 0
        return context

    budget.mandates_total = len(context.mandates)
    budget.guardrails_total = len(context.guardrails)
    budget.reference_total = len(context.reference)

    if settings.max_mandates > 0 and len(context.mandates) > settings.max_mandates:
        logger.info(
            "Applying mandate count limit: %d -> %d",
            len(context.mandates),
            settings.max_mandates,
        )
        context.mandates = context.mandates[: settings.max_mandates]

    if settings.max_guardrails > 0 and len(context.guardrails) > settings.max_guardrails:
        logger.info(
            "Applying guardrail count limit: %d -> %d",
            len(context.guardrails),
            settings.max_guardrails,
        )
        context.guardrails = context.guardrails[: settings.max_guardrails]

    budget.mandates_tokens = sum(count_tokens(m.content) for m in context.mandates)
    budget.guardrails_tokens = sum(count_tokens(g.content) for g in context.guardrails)

    if settings.budget_enabled:
        total_budget = settings.total_budget
        mandates_cap = int(total_budget * 0.6)
        guardrails_cap = int(total_budget * 0.4)

        mandates_tokens = 0
        filtered_mandates = []
        for m in context.mandates:
            tokens = count_tokens(m.content)
            if mandates_tokens + tokens <= mandates_cap:
                filtered_mandates.append(m)
                mandates_tokens += tokens
            else:
                logger.debug("Mandates tier cap hit: %d/%d tokens", mandates_tokens, mandates_cap)
                break
        context.mandates = filtered_mandates
        budget.mandates_tokens = mandates_tokens

        guardrails_tokens = 0
        filtered_guardrails = []
        for g in context.guardrails:
            tokens = count_tokens(g.content)
            if guardrails_tokens + tokens <= guardrails_cap:
                filtered_guardrails.append(g)
                guardrails_tokens += tokens
            else:
                logger.debug(
                    "Guardrails tier cap hit: %d/%d tokens", guardrails_tokens, guardrails_cap
                )
                break
        context.guardrails = filtered_guardrails
        budget.guardrails_tokens = guardrails_tokens

        logger.info(
            "Budget allocation: M=%d/%d G=%d/%d",
            mandates_tokens,
            mandates_cap,
            guardrails_tokens,
            guardrails_cap,
        )
    else:
        logger.debug(
            "Budget enforcement disabled - injecting all %d memories (%d tokens)",
            len(context.mandates) + len(context.guardrails),
            budget.total_tokens,
        )

    context.budget_usage = budget
    context.total_tokens = budget.total_tokens

    context.debug_info = {
        "mandates_count": len(context.mandates),
        "guardrails_count": len(context.guardrails),
        "reference_count": len(context.reference),
        "total_tokens": context.total_tokens,
        "budget_limit": settings.total_budget,
        "budget_hit": budget.hit_limit,
        "query": query[:100] if query else "",
        "task_type": task_type,
        "phase": phase,
    }

    logger.info(
        "Progressive context: mandates=%d guardrails=%d refs=%d tokens=%d/%d%s%s%s",
        len(context.mandates),
        len(context.guardrails),
        len(context.reference),
        context.total_tokens,
        settings.total_budget,
        " (budget exceeded)" if budget.hit_limit else "",
        f" task_type={task_type}" if task_type else "",
        f" phase={phase}" if phase else "",
    )

    return context
