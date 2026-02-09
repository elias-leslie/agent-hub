"""Progressive context builder for memory-augmented completions.

Builds the 3-block progressive disclosure context:
- Block 1 (Mandates): Always-inject golden standards
- Block 2 (Guardrails): Type-filtered anti-patterns
- Block 3 (Reference): Auto-inject + triggered references

Extracted from context_injector.py for maintainability.
"""

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
    memory_config: dict[str, Any] | None = None,
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

    # Fetch all episodes in parallel
    context.mandates, context.guardrails, context.reference = await fetch_all_episodes(
        scopes_to_query, include_mandates, include_guardrails, task_type, phase
    )

    settings = await get_memory_settings()

    # Apply memory_config overrides to settings
    apply_memory_config_overrides(settings, memory_config)

    # Apply tag filtering if configured
    if memory_config:
        exclude_tags = memory_config.get("exclude_tags", [])
        include_tags = memory_config.get("include_tags", [])
        if exclude_tags or include_tags:
            context.mandates = filter_by_tags(context.mandates, include_tags, exclude_tags)
            context.guardrails = filter_by_tags(context.guardrails, include_tags, exclude_tags)
            context.reference = filter_by_tags(context.reference, include_tags, exclude_tags)

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

    # Apply count limits
    context.mandates, context.guardrails = apply_count_limits(
        context.mandates, context.guardrails, settings
    )

    # Compute token counts
    budget.mandates_tokens, budget.guardrails_tokens = compute_token_counts(
        context.mandates, context.guardrails
    )

    # Apply budget enforcement if enabled
    if settings.budget_enabled:
        context.mandates, context.guardrails = apply_budget_enforcement(
            context.mandates, context.guardrails, budget
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
