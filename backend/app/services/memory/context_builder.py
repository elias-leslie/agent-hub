"""Tier-aware context builder for mandates, guardrails, and direct references."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.db import async_session

from .applicability import (
    applicability_has_exclusions,
    applicability_has_targets,
    applicability_matches,
    normalize_trigger_phases,
    normalize_trigger_task_types,
)
from .budget import BudgetUsage, count_tokens
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
from .context_injector_blocks import (
    get_auto_inject_references_as_search_results,
    get_guardrails,
    get_mandates,
    get_phase_triggered_references_as_search_results,
    get_pinned_episodes_as_search_results,
    get_triggered_references_as_search_results,
)
from .context_injector_queries import get_query_relevant_references_as_search_results
from .context_profiles import (
    priority_tags_for_profile,
    query_reference_selection_default_for_profile,
    resolve_policy_limits,
)
from .memory_models import MemoryContextKind
from .memory_utils import build_group_id
from .scoring import MemoryScoreInput, score_memory
from .service import MemoryScope, MemorySearchResult
from .settings import get_memory_settings
from .variants import get_variant_config

logger = logging.getLogger(__name__)


def _has_excluded_tag(ep_tags: list[str], exclude_tags: list[str]) -> bool:
    return any(tag in ep_tags for tag in exclude_tags)


def _has_required_tag(ep_tags: list[str], include_tags: list[str]) -> bool:
    return any(tag in ep_tags for tag in include_tags)


def _episode_passes_filters(
    ep_tags: list[str],
    include_tags: list[str],
    exclude_tags: list[str],
) -> bool:
    if exclude_tags and _has_excluded_tag(ep_tags, exclude_tags):
        return False
    return not (include_tags and not _has_required_tag(ep_tags, include_tags))


def filter_by_tags(
    episodes: list[MemorySearchResult],
    include_tags: list[str],
    exclude_tags: list[str],
) -> list[MemorySearchResult]:
    """Filter episodes by include/exclude tags using the episode's tags field."""
    if not include_tags and not exclude_tags:
        return episodes

    filtered = [
        ep
        for ep in episodes
        if _episode_passes_filters(ep.tags or [], include_tags, exclude_tags)
    ]

    if len(filtered) < len(episodes):
        logger.info(
            "Tag filter: %d -> %d episodes (include=%s, exclude=%s)",
            len(episodes),
            len(filtered),
            include_tags,
            exclude_tags,
        )

    return filtered


def compute_token_counts(
    mandates: list[MemorySearchResult],
    guardrails: list[MemorySearchResult],
    references: list[MemorySearchResult],
) -> tuple[int, int, int]:
    """Compute total tokens for mandates, guardrails, and references."""
    mandates_tokens = sum(count_tokens(get_rendered_content(m)) for m in mandates)
    guardrails_tokens = sum(count_tokens(get_rendered_content(g)) for g in guardrails)
    reference_tokens = sum(count_tokens(get_rendered_content(r)) for r in references)
    return mandates_tokens, guardrails_tokens, reference_tokens


def _add_unique(
    items: list[MemorySearchResult],
    target: list[MemorySearchResult],
    seen: set[str],
) -> None:
    for item in items:
        if item.uuid not in seen:
            target.append(item)
            seen.add(item.uuid)


FetchOperation = tuple[str, Callable[[], Awaitable[list[MemorySearchResult]]]]


def _build_scope_operations(
    scopes_to_query: list[tuple[MemoryScope, str | None]],
    include_mandates: bool,
    include_guardrails: bool,
    include_references: bool,
    db: AsyncSession | None,
) -> list[FetchOperation]:
    operations: list[FetchOperation] = []

    for query_scope, query_scope_id in scopes_to_query:
        if include_mandates:
            operations.append(
                (
                    f"mandates_{query_scope.value}",
                    lambda scope=query_scope, scope_id=query_scope_id: get_mandates(
                        scope=scope, scope_id=scope_id, db=db
                    ),
                )
            )
            operations.append(
                (
                    f"mandates_pinned_{query_scope.value}",
                    lambda scope=query_scope, scope_id=query_scope_id: (
                        get_pinned_episodes_as_search_results(
                            "mandate",
                            scope=scope,
                            scope_id=scope_id,
                            db=db,
                        )
                    )
                )
            )
        if include_guardrails:
            operations.append(
                (
                    f"guardrails_{query_scope.value}",
                    lambda scope=query_scope, scope_id=query_scope_id: get_guardrails(
                        scope=scope, scope_id=scope_id, db=db
                    ),
                )
            )
            operations.append(
                (
                    f"guardrails_pinned_{query_scope.value}",
                    lambda scope=query_scope, scope_id=query_scope_id: (
                        get_pinned_episodes_as_search_results(
                            "guardrail",
                            scope=scope,
                            scope_id=scope_id,
                            db=db,
                        )
                    )
                )
            )
        if include_references:
            operations.append(
                (
                    f"reference_{query_scope.value}",
                    lambda scope=query_scope, scope_id=query_scope_id: (
                        get_auto_inject_references_as_search_results(
                            scope=scope, scope_id=scope_id, db=db
                        )
                    ),
                )
            )
            operations.append(
                (
                    f"reference_pinned_{query_scope.value}",
                    lambda scope=query_scope, scope_id=query_scope_id: (
                        get_pinned_episodes_as_search_results(
                            "reference",
                            scope=scope,
                            scope_id=scope_id,
                            db=db,
                        )
                    )
                )
            )

    return operations


async def _run_fetch_operations(
    operations: list[FetchOperation],
) -> tuple[list[str], list[list[MemorySearchResult] | BaseException]]:
    task_keys: list[str] = []
    results: list[list[MemorySearchResult] | BaseException] = []
    for task_key, operation in operations:
        task_keys.append(task_key)
        try:
            results.append(await operation())
        except BaseException as exc:
            results.append(exc)
    return task_keys, results


def _process_gathered_results(
    task_keys: list[str],
    results: list[list[MemorySearchResult] | BaseException],
) -> tuple[list[MemorySearchResult], list[MemorySearchResult], list[MemorySearchResult]]:
    mandates: list[MemorySearchResult] = []
    guardrails: list[MemorySearchResult] = []
    reference: list[MemorySearchResult] = []

    mandates_seen: set[str] = set()
    guardrails_seen: set[str] = set()
    reference_seen: set[str] = set()

    buckets = {
        "mandates": (mandates, mandates_seen),
        "guardrails": (guardrails, guardrails_seen),
    }

    for key, result in zip(task_keys, results, strict=True):
        if isinstance(result, BaseException):
            logger.warning("Failed to get %s: %s", key, result)
            continue

        assert isinstance(result, list)
        block_type = key.split("_")[0]
        target, seen = buckets.get(block_type, (reference, reference_seen))
        _add_unique(result, target, seen)

    return mandates, guardrails, reference


async def fetch_all_episodes(
    scopes_to_query: list[tuple[MemoryScope, str | None]],
    include_mandates: bool,
    include_guardrails: bool,
    include_references: bool,
    task_type: str | None,
    phase: str | None,
    db: AsyncSession | None = None,
) -> tuple[list[MemorySearchResult], list[MemorySearchResult], list[MemorySearchResult]]:
    """Fetch all episodes with one caller-owned session and deduplicate by UUID."""
    operations = _build_scope_operations(
        scopes_to_query, include_mandates, include_guardrails, include_references, db
    )

    if include_references and task_type:
        for query_scope, query_scope_id in scopes_to_query:
            operations.append(
                (
                    f"reference_triggered_{query_scope.value}",
                    lambda scope=query_scope, scope_id=query_scope_id: (
                        get_triggered_references_as_search_results(
                            task_type=task_type,
                            group_id=build_group_id(scope, scope_id),
                            db=db,
                        )
                    ),
                )
            )

    if include_references and phase:
        for query_scope, query_scope_id in scopes_to_query:
            operations.append(
                (
                    f"reference_phase_triggered_{query_scope.value}",
                    lambda scope=query_scope, scope_id=query_scope_id: (
                        get_phase_triggered_references_as_search_results(
                            phase=phase,
                            group_id=build_group_id(scope, scope_id),
                            db=db,
                        )
                    ),
                )
            )

    if not operations:
        return [], [], []

    task_keys, results = await _run_fetch_operations(operations)
    return _process_gathered_results(task_keys, results)


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


def _get_context_blocks(context: ProgressiveContext) -> dict[str, list[MemorySearchResult]]:
    """Return mutable access to each context block."""
    return {
        "mandates": context.mandates,
        "guardrails": context.guardrails,
        "reference": context.reference,
        "reference_index": context.reference_index,
    }


def _set_context_block(
    context: ProgressiveContext,
    field_name: str,
    items: list[MemorySearchResult],
) -> None:
    """Replace one context block in-place."""
    setattr(context, field_name, items)


def _map_context_blocks(
    context: ProgressiveContext,
    transform: Callable[[str, list[MemorySearchResult]], list[MemorySearchResult]],
) -> None:
    """Apply same transform to each context block."""
    for field_name, items in _get_context_blocks(context).items():
        _set_context_block(context, field_name, transform(field_name, items))


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
        _map_context_blocks(
            context,
            lambda _field_name, items: filter_by_tags(items, [], exclude_tags),
        )
    if audience_tags:
        for field_name in ("reference", "reference_index"):
            _set_context_block(
                context,
                field_name,
                _filter_legacy_reference_audience_tags(
                    _get_context_blocks(context)[field_name],
                    audience_tags,
                ),
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
    _map_context_blocks(
        context,
        lambda _field_name, items: [
            item
            for item in items
            if applicability_matches(
                item.applicability,
                consumer_profile=consumer_profile,
                consumer_agent_slug=consumer_agent_slug,
                consumer_tags=consumer_tags,
            )
        ],
    )


def _apply_uuid_exclusions(context: ProgressiveContext, excluded_uuids: set[str]) -> None:
    """Remove explicitly excluded memory UUIDs from all context blocks."""
    if not excluded_uuids:
        return
    _map_context_blocks(
        context,
        lambda _field_name, items: [item for item in items if item.uuid not in excluded_uuids],
    )


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


def _limit_policy_item_count(
    items: list[MemorySearchResult],
    limit: int,
) -> list[MemorySearchResult]:
    """Cap policy items by count (0 = uncapped); items arrive pre-ranked."""
    if limit <= 0 or len(items) <= limit:
        return items
    return items[:limit]


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


def _partition_reference_index(
    items: list[MemorySearchResult],
) -> tuple[list[MemorySearchResult], list[MemorySearchResult]]:
    """Split references into capability-index and normal references."""
    reference_index = [item for item in items if item.context_kind == MemoryContextKind.CAPABILITY]
    reference = [item for item in items if item.context_kind != MemoryContextKind.CAPABILITY]
    return reference_index, reference


def _split_reference_index(
    context: ProgressiveContext,
    settings: Any,
    memory_config: dict[str, Any] | None,
) -> None:
    """Partition fetched references into capability (index) vs regular buckets."""
    if settings.reference_index_enabled and resolve_reference_index_enabled(memory_config):
        context.reference_index, context.reference = _partition_reference_index(context.reference)


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
    db: AsyncSession | None,
) -> None:
    """Fetch query-relevant references and merge them into the context."""
    payloads = await get_query_relevant_references_as_search_results(
        query, scopes_to_query, db=db
    )
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


async def _apply_priority_and_limits(
    context: ProgressiveContext,
    query: str,
    variant: str | None,
    variant_config: Any,
    consumer_profile: str | None,
    memory_config: dict[str, Any] | None,
    db: AsyncSession | None,
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
    policy_mandate_limit, policy_guardrail_limit, policy_reference_limit = (
        await resolve_policy_limits(consumer_profile, memory_config, db)
    )
    context.mandates = _limit_policy_item_count(context.mandates, policy_mandate_limit)
    context.guardrails = _limit_policy_item_count(context.guardrails, policy_guardrail_limit)
    if policy_reference_limit > 0:
        context.reference = _limit_policy_item_count(
            context.reference, policy_reference_limit
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
    consumer_profile: str | None = None,
    consumer_agent_slug: str | None = None,
    consumer_tags: list[str] | None = None,
    variant: str | None = None,
    db: AsyncSession | None = None,
) -> ProgressiveContext:
    """Build tier-aware context: all mandates/guardrails injected deterministically;
    references include auto-inject, task/phase triggers, and query-selected items
    (disabled only for heartbeat tasks).
    """
    if db is None:
        async with async_session() as session:
            return await build_progressive_context(
                query=query,
                scope=scope,
                scope_id=scope_id,
                include_mandates=include_mandates,
                include_guardrails=include_guardrails,
                include_references=include_references,
                include_global=include_global,
                task_type=task_type,
                phase=phase,
                memory_config=memory_config,
                consumer_profile=consumer_profile,
                consumer_agent_slug=consumer_agent_slug,
                consumer_tags=consumer_tags,
                variant=variant,
                db=session,
            )

    context = ProgressiveContext()
    variant_config = get_variant_config(variant)
    settings = await get_memory_settings(db)
    apply_memory_config_overrides(settings, memory_config)
    if not settings.enabled:
        logger.info("Memory injection disabled - returning empty context")
        context.budget_usage, context.total_tokens = BudgetUsage(), 0
        return context
    scopes_to_query = _build_scopes_to_query(scope, scope_id, include_global)
    context.mandates, context.guardrails, context.reference = await fetch_all_episodes(
        scopes_to_query,
        include_mandates,
        include_guardrails,
        include_references,
        task_type,
        phase,
        db=db,
    )
    _split_reference_index(context, settings, memory_config)
    if not include_references:
        context.reference = []
        context.reference_index = []
    elif _should_select_query_references(task_type, memory_config, consumer_profile):
        await _merge_query_selected_references(
            context, query, scopes_to_query, variant_config, consumer_profile, task_type, phase, db
        )
    _apply_all_filters(context, memory_config, consumer_profile, consumer_agent_slug, consumer_tags)
    await _apply_priority_and_limits(
        context, query, variant, variant_config, consumer_profile, memory_config, db
    )
    budget = _build_usage_snapshot(context)
    _finalize_context(context, budget, query, task_type, phase, consumer_profile, variant)
    return context
