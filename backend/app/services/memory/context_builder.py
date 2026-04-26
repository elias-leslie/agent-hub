"""Tier-aware context builder for mandates, guardrails, and direct references."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from .applicability import (
    applicability_has_exclusions,
    applicability_has_targets,
    applicability_matches,
    normalize_trigger_phases,
    normalize_trigger_task_types,
)
from .budget import BudgetUsage, count_tokens
from .context_builder_fetcher import fetch_all_episodes
from .context_builder_filters import filter_by_tags
from .context_builder_processors import compute_token_counts
from .context_builder_settings import (
    apply_memory_config_overrides,
    normalize_memory_config,
    resolve_excluded_memory_uuids,
    resolve_memory_tags,
    resolve_reference_index_enabled,
)
from .context_builder_tiers import (
    build_memory_plan_debug,
    get_rendered_content,
    plan_context_render_tiers,
)
from .context_injector_queries import get_query_relevant_references_as_search_results
from .context_profiles import (
    policy_limits_for_profile,
    priority_tags_for_profile,
    query_reference_selection_default_for_profile,
)
from .memory_models import MemoryContextKind
from .scoring import MemoryScoreInput, score_memory
from .service import MemoryScope, MemorySearchResult
from .settings import get_memory_settings
from .variants import get_variant_config

logger = logging.getLogger(__name__)
_TARGET_TOKENS_PER_LIMITED_ITEM = 100


@dataclass
class ProgressiveContext:
    """Result of progressive disclosure context retrieval."""

    mandates: list[MemorySearchResult] = field(default_factory=list)
    guardrails: list[MemorySearchResult] = field(default_factory=list)
    reference: list[MemorySearchResult] = field(default_factory=list)
    reference_index: list[MemorySearchResult] = field(default_factory=list)
    total_tokens: int = 0
    debug_info: dict[str, Any] = field(default_factory=dict)
    budget_usage: BudgetUsage | None = None

    def get_loaded_uuids(self) -> list[str]:
        """Get all UUIDs loaded into context (for usage tracking)."""
        return [
            r.uuid
            for block in (self.mandates, self.guardrails, self.reference_index, self.reference)
            for r in block
            if r.uuid
        ]

    def get_mandate_uuids(self) -> list[str]:
        """Get mandate UUIDs (for citation tracking)."""
        return [m.uuid for m in self.mandates if m.uuid]

    def get_guardrail_uuids(self) -> list[str]:
        """Get guardrail UUIDs (for citation tracking)."""
        return [g.uuid for g in self.guardrails if g.uuid]

    def get_reference_uuids(self) -> list[str]:
        """Get directly selected reference UUIDs."""
        return [r.uuid for r in self.reference if r.uuid]

    def get_reference_index_uuids(self) -> list[str]:
        """Get passive reference-index UUIDs."""
        return [r.uuid for r in self.reference_index if r.uuid]


def _apply_tag_filters(context: ProgressiveContext, memory_config: dict[str, Any]) -> None:
    """Apply exclude tags universally and audience tags only for legacy references.

    Mandates and guardrails are universal instructions — all agents see all of
    them regardless of audience_tags.  Only exclude_tags can remove them (e.g.
    for deprecated episodes). Explicit applicability targeting is authoritative;
    audience_tags remain only as a backward-compatible fallback for legacy
    references that still rely on ordinary memory tags for routing.
    """
    audience_tags, exclude_tags = resolve_memory_tags(memory_config)
    if exclude_tags:
        context.mandates = filter_by_tags(context.mandates, [], exclude_tags)
        context.guardrails = filter_by_tags(context.guardrails, [], exclude_tags)
        context.reference = filter_by_tags(context.reference, [], exclude_tags)
        context.reference_index = filter_by_tags(context.reference_index, [], exclude_tags)
    if audience_tags:
        context.reference = _filter_legacy_reference_audience_tags(
            context.reference,
            audience_tags,
        )
        context.reference_index = _filter_legacy_reference_audience_tags(
            context.reference_index,
            audience_tags,
        )


def _filter_legacy_reference_audience_tags(
    items: list[MemorySearchResult],
    audience_tags: list[str],
) -> list[MemorySearchResult]:
    """Apply tag-based audience routing only to references without applicability."""
    retained: list[MemorySearchResult] = []
    for item in items:
        applicability = item.applicability
        if applicability_has_targets(applicability) or applicability_has_exclusions(applicability):
            retained.append(item)
            continue
        if filter_by_tags([item], audience_tags, []):
            retained.append(item)
    return retained


def _apply_applicability_filters(
    context: ProgressiveContext,
    *,
    consumer_profile: str | None,
    consumer_agent_slug: str | None,
    consumer_tags: list[str],
) -> None:
    """Filter all context blocks against explicit applicability targeting."""
    for field_name in ("mandates", "guardrails", "reference", "reference_index"):
        items = getattr(context, field_name)
        filtered = [
            item
            for item in items
            if applicability_matches(
                item.applicability,
                consumer_profile=consumer_profile,
                consumer_agent_slug=consumer_agent_slug,
                consumer_tags=consumer_tags,
            )
        ]
        setattr(context, field_name, filtered)


def _apply_uuid_exclusions(context: ProgressiveContext, excluded_uuids: set[str]) -> None:
    """Remove explicitly excluded memory UUIDs from all context blocks."""
    if not excluded_uuids:
        return
    for field_name in ("mandates", "guardrails", "reference", "reference_index"):
        items = getattr(context, field_name)
        setattr(context, field_name, [item for item in items if item.uuid not in excluded_uuids])


def _prioritize_items_for_profile(
    items: list[MemorySearchResult],
    consumer_profile: str | None,
) -> list[MemorySearchResult]:
    """Move tagged startup-critical items to the front for profile-specific startup UX."""
    priority_tags = priority_tags_for_profile(consumer_profile)
    if not priority_tags and all(item.review_status == "pending" for item in items):
        return items
    return sorted(
        items,
        key=lambda item: (
            0 if priority_tags.intersection(item.tags) else 1,
            _review_status_rank(item),
            -item.relevance_score,
        ),
    )


def _review_status_rank(item: MemorySearchResult) -> int:
    """Prefer clean reviewed memories, then unreviewed, then queued review debt."""
    if item.review_status == "clean":
        return 0
    if item.review_status == "needs_action":
        return 2
    return 1


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
            _review_status_rank(pair[1]),
            -pair[1].relevance_score,
            pair[0],
        ),
    )
    return [item for _, item in ranked[:limit]]


def _limit_by_rendered_token_budget(
    items: list[MemorySearchResult],
    limit: int,
) -> list[MemorySearchResult]:
    """Limit only after reviewed compaction/rendering has reduced each item."""
    if limit <= 0 or len(items) <= limit:
        return items
    budget = limit * _TARGET_TOKENS_PER_LIMITED_ITEM
    kept: list[MemorySearchResult] = []
    used_tokens = 0
    for item in items:
        item_tokens = count_tokens(get_rendered_content(item))
        if len(kept) < limit or used_tokens + item_tokens <= budget:
            kept.append(item)
            used_tokens += item_tokens
    return kept


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
    budget.reference_total = len(context.reference) + len(context.reference_index)
    budget.mandates_tokens, budget.guardrails_tokens, budget.reference_tokens = compute_token_counts(
        context.mandates,
        context.guardrails,
        [*context.reference_index, *context.reference],
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
        context.reference_index,
        context.reference,
    )
    context.budget_usage = budget
    context.total_tokens = budget.total_tokens
    context.debug_info = {
        **context.debug_info,
        "mandates_count": len(context.mandates),
        "guardrails_count": len(context.guardrails),
        "reference_count": len(context.reference) + len(context.reference_index),
        "reference_index_count": len(context.reference_index),
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
        len(context.mandates), len(context.guardrails), len(context.reference) + len(context.reference_index),
        context.total_tokens,
        f" task_type={task_type}" if task_type else "",
        f" phase={phase}" if phase else "",
    )


def _should_select_query_references(
    task_type: str | None,
    memory_config: dict[str, Any] | None,
    consumer_profile: str | None,
) -> bool:
    """Return True when semantic/text-selected references should be added."""
    normalized_config = normalize_memory_config(memory_config)
    if normalized_config and "query_reference_selection_enabled" in normalized_config:
        return bool(normalized_config["query_reference_selection_enabled"])
    profile_default = query_reference_selection_default_for_profile(consumer_profile)
    if profile_default is not None:
        return profile_default
    task_kind = (task_type or "").strip().lower()
    return task_kind != "heartbeat"


def _split_reference_index(
    context: ProgressiveContext,
    settings: Any,
    memory_config: dict[str, Any] | None,
) -> None:
    """Partition fetched references into capability (index) vs regular buckets."""
    if settings.reference_index_enabled and resolve_reference_index_enabled(memory_config):
        context.reference_index = [
            item for item in context.reference if item.context_kind == MemoryContextKind.CAPABILITY
        ]
        context.reference = [
            item for item in context.reference if item.context_kind != MemoryContextKind.CAPABILITY
        ]


def _deduplicate_query_selected(
    payloads: list[Any],
    existing_uuids: set[str],
) -> list[MemorySearchResult]:
    """Validate payloads and drop any UUIDs already present in context."""
    results: list[MemorySearchResult] = []
    for payload in payloads:
        result = MemorySearchResult.model_validate(payload)
        if result.uuid in existing_uuids:
            continue
        existing_uuids.add(result.uuid)
        results.append(result)
    return results


async def _merge_query_selected_references(
    context: ProgressiveContext,
    query: str,
    scopes_to_query: list[tuple[MemoryScope, str | None]],
    variant_config: Any,
    consumer_profile: str | None,
    task_type: str | None,
    phase: str | None,
) -> None:
    """Fetch query-relevant references and merge them into the context."""
    payloads = await get_query_relevant_references_as_search_results(query, scopes_to_query)
    if not payloads:
        return
    filtered_payloads = [
        payload for payload in payloads if _query_selected_matches_triggers(payload, task_type, phase)
    ]
    if not filtered_payloads:
        return
    existing = {item.uuid for item in [*context.reference_index, *context.reference]}
    selected = _deduplicate_query_selected(filtered_payloads, existing)
    if selected:
        selected_uuids = {r.uuid for r in selected}
        context.reference_index = [
            item for item in context.reference_index if item.uuid not in selected_uuids
        ]
    context.reference.extend(
        _limit_references_for_variant(selected, variant_config.max_query_selected_references, consumer_profile)
    )


def _query_selected_matches_triggers(
    payload: dict[str, Any],
    task_type: str | None,
    phase: str | None,
) -> bool:
    """Respect explicit trigger hints when semantic/text query selection adds references."""
    trigger_task_types = normalize_trigger_task_types(payload.get("trigger_task_types"))
    if trigger_task_types:
        resolved_task_type = (task_type or "").strip().lower()
        if not resolved_task_type or resolved_task_type not in trigger_task_types:
            return False

    trigger_phases = normalize_trigger_phases(payload.get("trigger_phases"))
    if trigger_phases:
        resolved_phase = (phase or "").strip().lower()
        if not resolved_phase or resolved_phase not in trigger_phases:
            return False

    return True


def _apply_all_filters(
    context: ProgressiveContext,
    memory_config: dict[str, Any] | None,
    consumer_profile: str | None,
    consumer_agent_slug: str | None,
    consumer_tags: list[str] | None,
) -> None:
    """Apply applicability, tag, and UUID exclusion filters to all context blocks."""
    resolved_tags = list(consumer_tags or [])
    if not resolved_tags:
        resolved_tags, _ = resolve_memory_tags(memory_config)
    _apply_applicability_filters(
        context,
        consumer_profile=consumer_profile,
        consumer_agent_slug=consumer_agent_slug,
        consumer_tags=resolved_tags,
    )
    if memory_config:
        _apply_tag_filters(context, memory_config)
        _apply_uuid_exclusions(context, set(resolve_excluded_memory_uuids(memory_config)))


def _build_scopes_to_query(
    scope: MemoryScope,
    scope_id: str | None,
    include_global: bool,
) -> list[tuple[MemoryScope, str | None]]:
    """Return the ordered list of scopes to query, appending GLOBAL when appropriate."""
    scopes: list[tuple[MemoryScope, str | None]] = [(scope, scope_id)]
    if include_global and scope == MemoryScope.PROJECT and scope_id:
        scopes.append((MemoryScope.GLOBAL, None))
    return scopes


def _apply_priority_and_limits(
    context: ProgressiveContext,
    query: str,
    variant: str | None,
    variant_config: Any,
    consumer_profile: str | None,
) -> None:
    """Prioritize, score, and cap all context blocks according to variant config."""
    context.mandates = _prioritize_items_for_profile(context.mandates, consumer_profile)
    context.guardrails = _prioritize_items_for_profile(context.guardrails, consumer_profile)
    context.reference_index = _prioritize_items_for_profile(context.reference_index, consumer_profile)
    context.reference_index = _limit_references_for_variant(
        context.reference_index, variant_config.max_reference_items, consumer_profile
    )
    context.reference = _prioritize_items_for_profile(context.reference, consumer_profile)
    context.reference = _apply_reference_variant_scoring(context.reference, query, variant, consumer_profile)
    context.reference = _limit_references_for_variant(
        context.reference, variant_config.max_reference_items, consumer_profile
    )
    plan_context_render_tiers(
        context.mandates, context.guardrails, context.reference_index, context.reference,
        query, consumer_profile=consumer_profile,
    )
    policy_mandate_limit, policy_guardrail_limit = policy_limits_for_profile(consumer_profile)
    context.mandates = _limit_by_rendered_token_budget(context.mandates, policy_mandate_limit)
    context.guardrails = _limit_by_rendered_token_budget(context.guardrails, policy_guardrail_limit)


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
    consumer_agent_slug: str | None = None,
    consumer_tags: list[str] | None = None,
    variant: str | None = None,
) -> ProgressiveContext:
    """Build tier-aware context: all mandates/guardrails injected deterministically;
    references include auto-inject, task/phase triggers, and query-selected items
    (disabled only for heartbeat tasks).
    """
    context = ProgressiveContext()
    variant_config = get_variant_config(variant)
    settings = await get_memory_settings()
    apply_memory_config_overrides(settings, memory_config)
    if not settings.enabled:
        logger.info("Memory injection disabled - returning empty context")
        context.budget_usage, context.total_tokens = BudgetUsage(), 0
        return context
    scopes_to_query = _build_scopes_to_query(scope, scope_id, include_global)
    context.mandates, context.guardrails, context.reference = await fetch_all_episodes(
        scopes_to_query, include_mandates, include_guardrails, include_references, task_type, phase
    )
    _split_reference_index(context, settings, memory_config)
    if not include_references:
        context.reference = []
        context.reference_index = []
    elif _should_select_query_references(task_type, memory_config, consumer_profile):
        await _merge_query_selected_references(
            context, query, scopes_to_query, variant_config, consumer_profile, task_type, phase
        )
    _apply_all_filters(context, memory_config, consumer_profile, consumer_agent_slug, consumer_tags)
    _apply_priority_and_limits(context, query, variant, variant_config, consumer_profile)
    budget = _build_usage_snapshot(context)
    _finalize_context(context, budget, query, task_type, phase, consumer_profile, variant)
    return context
