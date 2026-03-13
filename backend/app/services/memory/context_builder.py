"""Progressive context builder: mandates, guardrails, and reference blocks."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from .budget import BudgetUsage
from .context_builder_fetcher import fetch_all_episodes
from .context_builder_filters import filter_by_tags
from .context_builder_processors import compute_token_counts
from .context_builder_settings import apply_memory_config_overrides
from .context_builder_tiers import build_memory_plan_debug, plan_context_render_tiers
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
    """Apply audience and exclude tag filters to context blocks in-place."""
    exclude_tags = memory_config.get("exclude_tags", [])
    audience_tags = memory_config.get("audience_tags", [])
    if exclude_tags:
        context.mandates = filter_by_tags(context.mandates, [], exclude_tags)
        context.guardrails = filter_by_tags(context.guardrails, [], exclude_tags)
        context.reference = filter_by_tags(context.reference, [], exclude_tags)
    if audience_tags:
        context.mandates = filter_by_tags(context.mandates, audience_tags, [])
        context.guardrails = filter_by_tags(context.guardrails, audience_tags, [])
        context.reference = filter_by_tags(context.reference, audience_tags, [])


def _build_usage_snapshot(context: ProgressiveContext) -> BudgetUsage:
    """Capture rendered token totals and coverage counts for the current context."""
    budget = BudgetUsage()
    budget.mandates_total = len(context.mandates)
    budget.guardrails_total = len(context.guardrails)
    budget.reference_total = len(context.reference)
    budget.mandates_tokens, budget.guardrails_tokens, budget.reference_tokens = compute_token_counts(
        context.mandates,
        context.guardrails,
        context.reference,
    )
    return budget


def _finalize_context(
    context: ProgressiveContext, budget: BudgetUsage, query: str, task_type: str | None, phase: str | None
) -> None:
    """Set total_tokens, budget_usage, debug_info, and emit log line in-place."""
    plan_debug = build_memory_plan_debug(
        context.mandates,
        context.guardrails,
        context.reference,
    )
    context.budget_usage = budget
    context.total_tokens = budget.total_tokens
    context.debug_info = {
        **context.debug_info,
        "mandates_count": len(context.mandates),
        "guardrails_count": len(context.guardrails),
        "reference_count": len(context.reference),
        "total_tokens": context.total_tokens,
        "query": query[:100] if query else "",
        "task_type": task_type,
        "phase": phase,
        **plan_debug,
    }
    logger.info(
        "Progressive context: mandates=%d guardrails=%d refs=%d tokens=%d%s%s",
        len(context.mandates), len(context.guardrails), len(context.reference),
        context.total_tokens,
        f" task_type={task_type}" if task_type else "",
        f" phase={phase}" if phase else "",
    )


async def build_progressive_context(
    query: str,
    scope: MemoryScope = MemoryScope.GLOBAL,
    scope_id: str | None = None,
    include_mandates: bool = True,
    include_guardrails: bool = True,
    include_references: bool = True,
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
        scopes_to_query, include_mandates, include_guardrails, include_references, task_type, phase
    )
    if not include_references:
        context.reference = []
    if include_references:
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

    plan_context_render_tiers(
        context.mandates,
        context.guardrails,
        context.reference,
        query,
    )

    budget = BudgetUsage()
    if not settings.enabled:
        logger.info("Memory injection disabled - returning empty context")
        context.mandates = []
        context.guardrails = []
        context.reference = []
        context.budget_usage = budget
        context.total_tokens = 0
        return context

    budget = _build_usage_snapshot(context)
    _finalize_context(context, budget, query, task_type, phase)
    return context
