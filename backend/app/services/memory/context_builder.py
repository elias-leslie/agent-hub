"""Tier-aware context builder for mandates, guardrails, and direct references."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from .budget import BudgetUsage
from .context_builder_fetcher import fetch_all_episodes
from .context_builder_filters import filter_by_tags
from .context_builder_processors import compute_token_counts
from .context_builder_settings import (
    apply_memory_config_overrides,
    normalize_memory_config,
    resolve_memory_tags,
)
from .context_builder_tiers import build_memory_plan_debug, plan_context_render_tiers
from .context_injector_queries import get_query_relevant_references_as_search_results
from .context_profiles import priority_tags_for_profile
from .scoring import MemoryScoreInput, score_memory
from .service import MemoryScope, MemorySearchResult
from .settings import get_memory_settings
from .variants import get_variant_config

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
    """Apply audience and exclude tag filters to context blocks in-place.

    Mandates and guardrails are universal instructions — all agents see all of
    them regardless of audience_tags.  Only exclude_tags can remove them (e.g.
    for deprecated episodes).  audience_tags filtering applies exclusively to
    references, where role/domain-specific selection is appropriate.
    """
    audience_tags, exclude_tags = resolve_memory_tags(memory_config)
    if exclude_tags:
        context.mandates = filter_by_tags(context.mandates, [], exclude_tags)
        context.guardrails = filter_by_tags(context.guardrails, [], exclude_tags)
        context.reference = filter_by_tags(context.reference, [], exclude_tags)
    if audience_tags:
        context.reference = filter_by_tags(context.reference, audience_tags, [])


def _prioritize_items_for_profile(
    items: list[MemorySearchResult],
    consumer_profile: str | None,
) -> list[MemorySearchResult]:
    """Move tagged startup-critical items to the front for profile-specific startup UX."""
    priority_tags = priority_tags_for_profile(consumer_profile)
    if not priority_tags:
        return items
    return sorted(
        items,
        key=lambda item: (0 if priority_tags.intersection(item.tags) else 1, -item.relevance_score),
    )


def _limit_references_for_variant(
    items: list[MemorySearchResult],
    limit: int,
    consumer_profile: str | None,
) -> list[MemorySearchResult]:
    """Keep only the highest-priority references when a variant sets a cap."""
    if limit <= 0:
        return []
    if len(items) <= limit:
        return items

    priority_tags = priority_tags_for_profile(consumer_profile)
    ranked = sorted(
        enumerate(items),
        key=lambda pair: (
            0 if priority_tags.intersection(pair[1].tags) else 1,
            0 if pair[1].pinned else 1,
            -pair[1].relevance_score,
            pair[0],
        ),
    )
    return [item for _, item in ranked[:limit]]


def _apply_reference_variant_scoring(
    items: list[MemorySearchResult],
    query: str,
    variant: str | None,
    consumer_profile: str | None,
) -> list[MemorySearchResult]:
    """Rescore references with the live variant config before limit/cap selection."""
    if not items:
        return items

    variant_config = get_variant_config(variant)
    priority_tags = priority_tags_for_profile(consumer_profile)
    scored: list[MemorySearchResult] = []
    now = datetime.now(UTC)

    for item in items:
        memory_score = score_memory(
            MemoryScoreInput(
                semantic_similarity=item.relevance_score,
                confidence=item.confidence if item.confidence is not None else 70.0,
                loaded_count=item.loaded_count,
                referenced_count=item.referenced_count,
                created_at=item.created_at,
                last_used_at=item.last_accessed_at,
                tier="reference",
                token_count=item.token_count,
            ),
            variant_config,
            now=now,
        )
        item.relevance_score = memory_score.final_score
        if item.pinned or priority_tags.intersection(item.tags) or memory_score.passes_threshold:
            scored.append(item)

    logger.info(
        "Reference scoring: kept=%d filtered=%d variant=%s query=%s",
        len(scored),
        len(items) - len(scored),
        variant_config.variant.value,
        query[:80],
    )
    return scored


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
    context: ProgressiveContext,
    budget: BudgetUsage,
    query: str,
    task_type: str | None,
    phase: str | None,
    consumer_profile: str | None,
    variant: str | None,
) -> None:
    """Set token totals, debug_info, and emit a compact observability line."""
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
        "consumer_profile": consumer_profile or "agent_runtime",
        "variant": get_variant_config(variant).variant.value,
        **plan_debug,
    }
    logger.info(
        "Progressive context: mandates=%d guardrails=%d refs=%d tokens=%d%s%s",
        len(context.mandates), len(context.guardrails), len(context.reference),
        context.total_tokens,
        f" task_type={task_type}" if task_type else "",
        f" phase={phase}" if phase else "",
    )


def _should_select_query_references(
    task_type: str | None,
    memory_config: dict[str, Any] | None,
) -> bool:
    """Return True when semantic/text-selected references should be added."""
    normalized_config = normalize_memory_config(memory_config)
    if normalized_config and "query_reference_selection_enabled" in normalized_config:
        return bool(normalized_config["query_reference_selection_enabled"])
    task_kind = (task_type or "").strip().lower()
    return task_kind != "heartbeat"


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
    consumer_profile: str | None = None,
    variant: str | None = None,
) -> ProgressiveContext:
    """Build tier-aware context for mandates, guardrails, and direct references.

    Deterministic injection: ALL mandates and guardrails for the scope are
    injected. No scoring, no thresholds - just tiered prompt rendering.
    References still include auto-inject and task/phase-triggered items. Query-
    selected references are enabled by default except for heartbeat, whose
    dynamic prompt is too noisy to use as a retrieval query.
    """
    context = ProgressiveContext()
    variant_config = get_variant_config(variant)

    scopes_to_query: list[tuple[MemoryScope, str | None]] = [(scope, scope_id)]
    if include_global and scope == MemoryScope.PROJECT and scope_id:
        scopes_to_query.append((MemoryScope.GLOBAL, None))

    context.mandates, context.guardrails, context.reference = await fetch_all_episodes(
        scopes_to_query, include_mandates, include_guardrails, include_references, task_type, phase
    )
    if not include_references:
        context.reference = []
    if include_references and _should_select_query_references(task_type, memory_config):
        selected_reference_payloads = await get_query_relevant_references_as_search_results(
            query,
            scopes_to_query,
        )
        if selected_reference_payloads:
            existing = {item.uuid for item in context.reference}
            selected_results: list[MemorySearchResult] = []
            for payload in selected_reference_payloads:
                result = MemorySearchResult.model_validate(payload)
                if result.uuid in existing:
                    continue
                existing.add(result.uuid)
                selected_results.append(result)
            context.reference.extend(
                _limit_references_for_variant(
                    selected_results,
                    variant_config.max_query_selected_references,
                    consumer_profile,
                )
            )

    settings = await get_memory_settings()
    apply_memory_config_overrides(settings, memory_config)
    if memory_config:
        _apply_tag_filters(context, memory_config)

    context.mandates = _prioritize_items_for_profile(context.mandates, consumer_profile)
    context.guardrails = _prioritize_items_for_profile(context.guardrails, consumer_profile)
    context.reference = _prioritize_items_for_profile(context.reference, consumer_profile)
    context.reference = _apply_reference_variant_scoring(
        context.reference,
        query,
        variant,
        consumer_profile,
    )
    context.reference = _limit_references_for_variant(
        context.reference,
        variant_config.max_reference_items,
        consumer_profile,
    )

    plan_context_render_tiers(
        context.mandates,
        context.guardrails,
        context.reference,
        query,
        consumer_profile=consumer_profile,
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
    _finalize_context(context, budget, query, task_type, phase, consumer_profile, variant)
    return context
