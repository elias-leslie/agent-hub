"""Progressive context builder: mandates, guardrails, and reference blocks."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from .budget import BudgetUsage
from .context_builder_budget import apply_budget_enforcement
from .context_builder_fetcher import fetch_all_episodes
from .context_builder_filters import filter_by_tags
from .context_builder_processors import apply_count_limits, compute_token_counts
from .context_builder_settings import apply_memory_config_overrides
from .context_injector_queries import get_query_relevant_references_as_search_results
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
        """Get all UUIDs loaded into context (for usage tracking)."""
        return [r.uuid for block in (self.mandates, self.guardrails, self.reference) for r in block if r.uuid]

    def get_mandate_uuids(self) -> list[str]:
        """Get mandate UUIDs (for citation tracking)."""
        return [m.uuid for m in self.mandates if m.uuid]

    def get_guardrail_uuids(self) -> list[str]:
        """Get guardrail UUIDs (for citation tracking)."""
        return [g.uuid for g in self.guardrails if g.uuid]

    def get_reference_uuids(self) -> list[str]:
        """Get directly selected reference UUIDs."""
        return [r.uuid for r in self.reference if r.uuid]


def _apply_tag_filters(context: ProgressiveContext, memory_config: dict[str, Any]) -> None:
    """Apply include/exclude tag filters to context blocks in-place.

    exclude_tags applies to all tiers (remove unwanted content everywhere).
    include_tags only applies to references (mandates/guardrails always injected).
    """
    exclude_tags = memory_config.get("exclude_tags", [])
    include_tags = memory_config.get("include_tags", [])
    if exclude_tags:
        context.mandates = filter_by_tags(context.mandates, [], exclude_tags)
        context.guardrails = filter_by_tags(context.guardrails, [], exclude_tags)
        context.reference = filter_by_tags(context.reference, [], exclude_tags)
    if include_tags:
        context.reference = filter_by_tags(context.reference, include_tags, [])


def _apply_limits_and_budget(context: ProgressiveContext, settings: Any) -> BudgetUsage:
    """Apply count limits and budget enforcement; return populated BudgetUsage."""
    budget = BudgetUsage(total_budget=settings.total_budget)
    budget.mandates_total = len(context.mandates)
    budget.guardrails_total = len(context.guardrails)
    budget.reference_total = len(context.reference)

    context.mandates, context.guardrails = apply_count_limits(context.mandates, context.guardrails, settings)
    budget.mandates_tokens, budget.guardrails_tokens, budget.reference_tokens = compute_token_counts(
        context.mandates,
        context.guardrails,
        context.reference,
    )

    if settings.budget_enabled:
        context.mandates, context.guardrails, context.reference = apply_budget_enforcement(
            context.mandates,
            context.guardrails,
            context.reference,
            budget,
        )
    else:
        logger.debug(
            "Budget enforcement disabled - injecting all %d memories (%d tokens)",
            len(context.mandates) + len(context.guardrails) + len(context.reference),
            budget.total_tokens,
        )
    return budget


def _finalize_context(
    context: ProgressiveContext, budget: BudgetUsage, settings: Any, query: str, task_type: str | None, phase: str | None
) -> None:
    """Set total_tokens, budget_usage, debug_info, and emit log line in-place."""
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
        len(context.mandates), len(context.guardrails), len(context.reference),
        context.total_tokens, settings.total_budget,
        " (budget exceeded)" if budget.hit_limit else "",
        f" task_type={task_type}" if task_type else "",
        f" phase={phase}" if phase else "",
    )


async def build_progressive_context(
    query: str,
    scope: MemoryScope = MemoryScope.GLOBAL,
    scope_id: str | None = None,
    include_mandates: bool = True,
    include_guardrails: bool = True,
    include_global: bool = True,
    task_type: str | None = None,
    phase: str | None = None,
    memory_config: dict[str, Any] | None = None,
) -> ProgressiveContext:
    """Build 2-block progressive context (mandates + guardrails).

    Deterministic injection: ALL mandates and guardrails for the scope are
    injected. No scoring, no thresholds - just demotion filtering for mandates.
    Reference items included when auto_inject=true or task_type/phase match.
    """
    context = ProgressiveContext()

    scopes_to_query: list[tuple[MemoryScope, str | None]] = [(scope, scope_id)]
    if include_global and scope == MemoryScope.PROJECT and scope_id:
        scopes_to_query.append((MemoryScope.GLOBAL, None))

    context.mandates, context.guardrails, context.reference = await fetch_all_episodes(
        scopes_to_query, include_mandates, include_guardrails, task_type, phase
    )
    selected_reference_payloads = await get_query_relevant_references_as_search_results(
        query,
        scopes_to_query,
    )
    if selected_reference_payloads:
        existing = {item.uuid for item in context.reference}
        for payload in selected_reference_payloads:
            result = MemorySearchResult.model_validate(payload)
            if result.uuid in existing:
                continue
            context.reference.append(result)
            existing.add(result.uuid)

    settings = await get_memory_settings()
    apply_memory_config_overrides(settings, memory_config)
    if memory_config:
        _apply_tag_filters(context, memory_config)

    budget = BudgetUsage(total_budget=settings.total_budget)
    if not settings.enabled:
        logger.info("Memory injection disabled - returning empty context")
        context.mandates = []
        context.guardrails = []
        context.budget_usage = budget
        context.total_tokens = 0
        return context

    budget = _apply_limits_and_budget(context, settings)
    _finalize_context(context, budget, settings, query, task_type, phase)
    return context
