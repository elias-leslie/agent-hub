"""
Context injection service for memory-augmented completions.

Implements 3-block progressive disclosure context injection:
- Block 1 (Mandates): Always-inject golden standards (confidence=100), critical constraints
- Block 2 (Guardrails): Type-filtered anti-patterns and gotchas (TROUBLESHOOTING_GUIDE)
- Block 3 (Reference): Semantic search for patterns and workflows (CODING_STANDARD, OPERATIONAL_CONTEXT)

This ensures relevant context surfaces when needed without overwhelming
the context window.

Also supports legacy two-tier injection for backwards compatibility:
- Tier 1 (Global): System design + domain knowledge at task start
- Tier 2 (JIT): Patterns + gotchas at subtask execution time
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from .budget import BudgetUsage, count_tokens
from .citation_parser import format_guardrail_citation, format_mandate_citation
from .graphiti_client import get_graphiti
from .metrics_collector import InjectionMetrics, record_injection_metrics
from .service import (
    MemoryCategory,
    MemoryScope,
    MemorySearchResult,
    MemorySource,
    build_group_id,
    get_memory_service,
)
from .settings import get_memory_settings

logger = logging.getLogger(__name__)

# Context injection markers
MEMORY_CONTEXT_START = "<memory>"
MEMORY_CONTEXT_END = "</memory>"


async def get_episodes_by_tier(
    tier: str,
    scope: MemoryScope = MemoryScope.GLOBAL,
    scope_id: str | None = None,
) -> list[dict[str, Any]]:
    """
    Get episodes by injection_tier field.

    This is the new tier-first query method that replaces keyword matching.

    Args:
        tier: The injection tier (mandate/guardrail/reference)
        scope: Memory scope to query
        scope_id: Project or task ID for scoping

    Returns:
        List of episode dicts with uuid, content, created_at, etc.
    """
    graphiti = get_graphiti()
    driver = graphiti.driver
    group_id = build_group_id(scope, scope_id)

    query = """
    MATCH (e:Episodic {group_id: $group_id})
    WHERE e.injection_tier = $tier
    RETURN e.uuid AS uuid,
           e.content AS content,
           e.name AS name,
           e.source_description AS source_description,
           e.created_at AS created_at,
           COALESCE(e.loaded_count, 0) AS loaded_count,
           COALESCE(e.referenced_count, 0) AS referenced_count,
           COALESCE(e.utility_score, 0.5) AS utility_score
    ORDER BY e.created_at DESC
    """

    try:
        records, _, _ = await driver.execute_query(
            query,
            group_id=group_id,
            tier=tier,
        )
        return [dict(r) for r in records]
    except Exception as e:
        logger.warning("Failed to get episodes by tier %s: %s", tier, e)
        return []


# Token estimation constants (used for logging/debugging only, NOT for limiting)
CHARS_PER_TOKEN = 4


@dataclass
class ProgressiveContext:
    """Result of progressive disclosure context retrieval."""

    mandates: list[MemorySearchResult] = field(default_factory=list)
    guardrails: list[MemorySearchResult] = field(default_factory=list)
    reference: list[MemorySearchResult] = field(default_factory=list)
    total_tokens: int = 0
    debug_info: dict[str, Any] = field(default_factory=dict)
    budget_usage: BudgetUsage | None = None  # Token budget tracking

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


class ContextTier(str, Enum):
    """Context injection tier."""

    GLOBAL = "global"  # Task-start: system_design, domain_knowledge
    JIT = "jit"  # Subtask-time: patterns, gotchas (troubleshooting_guide, coding_standard)
    BOTH = "both"  # Combined for single-shot requests


# Directive language for global context
GLOBAL_CONTEXT_DIRECTIVE = """
## Project Context (from memory)

The following context has been retrieved from your knowledge base about this project.
Use this information to inform your decisions and recommendations.
"""

# Directive language for JIT context
JIT_CONTEXT_DIRECTIVE = """
## Relevant Patterns & Known Issues

The following patterns and gotchas have been retrieved based on the current task.
Pay special attention to the gotchas to avoid repeating past mistakes.
"""

# Progressive disclosure directive blocks (compact for token efficiency)
MANDATE_DIRECTIVE = "## Mandates"
GUARDRAIL_DIRECTIVE = "## Guardrails"
REFERENCE_DIRECTIVE = "## Reference"

# Citation instruction for LLM (compact)
CITATION_INSTRUCTION = """When applying a rule, cite it: Applied: [M:uuid8] or [G:uuid8]"""


# ============================================================================
# 3-Block Progressive Disclosure Functions
# ============================================================================


async def get_mandates(
    scope: MemoryScope = MemoryScope.GLOBAL,
    scope_id: str | None = None,
    query: str | None = None,
    variant: str = "BASELINE",
) -> list[MemorySearchResult]:
    """
    Get mandates via tier-based lookup with score-based selection.

    Uses injection_tier='mandate' field for filtering (tier-first approach).
    Implements adaptive index for demotion logic and scoring.

    Mandates are critical system knowledge:
    - Core coding principles (simplicity, async patterns, etc.)
    - Critical constraints from system design
    - Authentication and security patterns

    Args:
        scope: Memory scope to query
        scope_id: Project or task ID for scoping
        query: Query for semantic relevance scoring (optional)
        variant: A/B variant for configuration

    Returns:
        List of mandate search results filtered by relevance threshold and demotion
    """
    from .adaptive_index import get_adaptive_index
    from .scoring import MemoryScoreInput, score_memory
    from .variants import get_variant_config

    config = get_variant_config(variant)

    # Get adaptive index for demotion logic and usage stats
    adaptive_index = await get_adaptive_index()
    demoted_uuids = {e.uuid for e in adaptive_index.entries if e.is_demoted}

    # Get mandates by injection_tier field (tier-first approach)
    episodes = await get_episodes_by_tier("mandate", scope, scope_id)
    logger.debug("Retrieved %d mandate episodes", len(episodes))

    # Build uuid->entry map for usage stats from adaptive index
    entry_by_uuid = {e.uuid: e for e in adaptive_index.entries}

    # Convert and score each mandate
    results: list[MemorySearchResult] = []
    for ep in episodes:
        content = ep.get("content") or ""
        uuid = ep.get("uuid", "")
        if not content:
            logger.debug("Skipping mandate without content: %s", uuid[:8] if uuid else "?")
            continue

        # Check if demoted by adaptive index
        if uuid in demoted_uuids:
            logger.debug("Excluding demoted mandate: uuid=%s", uuid[:8])
            continue

        # Convert neo4j.time.DateTime to Python datetime if needed
        created_at = ep.get("created_at")
        if created_at is not None and hasattr(created_at, "to_native"):
            created_at = created_at.to_native()

        # Get usage stats from adaptive index entry or fallback to episode data
        entry = entry_by_uuid.get(uuid)
        if entry:
            loaded_count = entry.loaded_count
            referenced_count = entry.referenced_count
            relevance_ratio = entry.relevance_ratio
        else:
            loaded_count = ep.get("loaded_count", 0)
            referenced_count = ep.get("referenced_count", 0)
            relevance_ratio = ep.get("utility_score", 0.5)

        # Build score input
        score_input = MemoryScoreInput(
            semantic_similarity=relevance_ratio,
            confidence=100.0,  # Mandates have confidence=100
            loaded_count=loaded_count,
            referenced_count=referenced_count,
            created_at=created_at,
            tier="mandate",
        )

        # Score the memory
        score_result = score_memory(score_input, config)

        # Apply minimum relevance threshold
        if not score_result.passes_threshold:
            logger.debug(
                "Excluding mandate below threshold: uuid=%s score=%.3f threshold=%.3f",
                uuid[:8],
                score_result.final_score,
                config.min_relevance_threshold,
            )
            continue

        try:
            results.append(
                MemorySearchResult(
                    uuid=uuid,
                    content=content,
                    source=MemorySource.SYSTEM,
                    relevance_score=score_result.final_score,
                    created_at=created_at,
                    facts=[content],
                )
            )
        except Exception as e:
            logger.warning(
                "Failed to create MemorySearchResult: %s (content=%s...)", e, content[:50]
            )

    # Sort by score descending (highest relevance first)
    results.sort(key=lambda r: r.relevance_score, reverse=True)

    logger.info(
        "Mandate selection: %d/%d passed (variant=%s, threshold=%.3f, demoted=%d)",
        len(results),
        len(episodes),
        variant,
        config.min_relevance_threshold,
        len(demoted_uuids),
    )
    return results


async def get_guardrails(
    query: str,
    scope: MemoryScope = MemoryScope.GLOBAL,
    scope_id: str | None = None,
    variant: str = "BASELINE",
) -> list[MemorySearchResult]:
    """
    Get guardrails via tier-based lookup with score-based selection.

    Uses injection_tier='guardrail' field for filtering (tier-first approach).
    Guardrails are anti-patterns, gotchas, and things to avoid.

    Args:
        query: Query to find relevant guardrails for
        scope: Memory scope to query
        scope_id: Project or task ID for scoping
        variant: A/B variant for configuration

    Returns:
        List of guardrail search results filtered by relevance threshold
    """
    from .scoring import MemoryScoreInput, score_memory
    from .variants import get_variant_config

    config = get_variant_config(variant)

    # Get guardrails by injection_tier field (tier-first approach)
    episodes = await get_episodes_by_tier("guardrail", scope, scope_id)
    logger.debug("Retrieved %d guardrail episodes", len(episodes))

    results: list[MemorySearchResult] = []

    for ep in episodes:
        content = ep.get("content") or ""
        uuid = ep.get("uuid", "")

        if not content:
            continue

        # Convert neo4j.time.DateTime to Python datetime if needed
        created_at = ep.get("created_at")
        if created_at is not None and hasattr(created_at, "to_native"):
            created_at = created_at.to_native()

        # Score the guardrail using multi-factor scoring
        score_input = MemoryScoreInput(
            semantic_similarity=ep.get("utility_score", 0.5),
            confidence=80.0,  # Guardrails typically have lower confidence than mandates
            loaded_count=ep.get("loaded_count", 0),
            referenced_count=ep.get("referenced_count", 0),
            created_at=created_at,
            tier="guardrail",
        )

        score_result = score_memory(score_input, config)

        # Apply minimum relevance threshold
        if not score_result.passes_threshold:
            continue

        results.append(
            MemorySearchResult(
                uuid=uuid,
                content=content,
                source=MemorySource.SYSTEM,
                relevance_score=score_result.final_score,
                created_at=created_at,
                facts=[content],
            )
        )

    # Sort by score descending
    results.sort(key=lambda r: r.relevance_score, reverse=True)

    logger.info(
        "Guardrail selection: %d passed threshold (variant=%s, threshold=%.3f)",
        len(results),
        variant,
        config.min_relevance_threshold,
    )
    return results


async def get_reference(
    query: str,
    scope: MemoryScope = MemoryScope.GLOBAL,
    scope_id: str | None = None,
    variant: str = "BASELINE",
) -> list[MemorySearchResult]:
    """
    Get reference via tier-based lookup with score-based selection.

    Uses injection_tier='reference' field for filtering (tier-first approach).
    Reference items provide positive guidance - patterns, standards, workflows.

    Args:
        query: Query to find relevant reference for
        scope: Memory scope to query
        scope_id: Project or task ID for scoping
        variant: A/B variant for configuration

    Returns:
        List of reference search results filtered by relevance threshold
    """
    from .scoring import MemoryScoreInput, score_memory
    from .variants import get_variant_config

    config = get_variant_config(variant)

    # Get reference by injection_tier field (tier-first approach)
    episodes = await get_episodes_by_tier("reference", scope, scope_id)
    logger.debug("Retrieved %d reference episodes", len(episodes))

    results: list[MemorySearchResult] = []

    for ep in episodes:
        content = ep.get("content") or ""
        uuid = ep.get("uuid", "")

        if not content:
            continue

        # Convert neo4j.time.DateTime to Python datetime if needed
        created_at = ep.get("created_at")
        if created_at is not None and hasattr(created_at, "to_native"):
            created_at = created_at.to_native()

        # Score the reference using multi-factor scoring
        score_input = MemoryScoreInput(
            semantic_similarity=ep.get("utility_score", 0.5),
            confidence=70.0,  # Reference items typically have moderate confidence
            loaded_count=ep.get("loaded_count", 0),
            referenced_count=ep.get("referenced_count", 0),
            created_at=created_at,
            tier="reference",
        )

        score_result = score_memory(score_input, config)

        # Apply minimum relevance threshold
        if not score_result.passes_threshold:
            continue

        results.append(
            MemorySearchResult(
                uuid=uuid,
                content=content,
                source=MemorySource.SYSTEM,
                relevance_score=score_result.final_score,
                created_at=created_at,
                facts=[content],
            )
        )

    # Sort by score descending
    results.sort(key=lambda r: r.relevance_score, reverse=True)

    logger.info(
        "Reference selection: %d passed threshold (variant=%s, threshold=%.3f)",
        len(results),
        variant,
        config.min_relevance_threshold,
    )
    return results


async def build_progressive_context(
    query: str,
    scope: MemoryScope = MemoryScope.GLOBAL,
    scope_id: str | None = None,
    include_mandates: bool = True,
    include_guardrails: bool = True,
    include_reference: bool = True,
    include_global: bool = True,
    variant: str = "BASELINE",
) -> ProgressiveContext:
    """
    Build 3-block progressive disclosure context for a query.

    Implements Decision d6: Score-based selection with minimum relevance threshold.
    All memories compete on final_score (semantic + usage + recency + tier multiplier).
    Items above MIN_RELEVANCE_THRESHOLD are included - NO arbitrary token/char caps.

    Combines:
    - Mandates: Golden standards with score-based selection
    - Guardrails: Type-filtered anti-patterns with scoring
    - Reference: Semantic search patterns with scoring

    Args:
        query: Query to retrieve context for
        scope: Memory scope to query
        scope_id: Project or task ID for scoping
        include_mandates: Whether to include mandates block
        include_guardrails: Whether to include guardrails block
        include_reference: Whether to include reference block
        include_global: Whether to also include global scope when querying project scope
        variant: A/B variant for configuration (BASELINE, ENHANCED, MINIMAL, AGGRESSIVE)

    Returns:
        ProgressiveContext with all three blocks and token count
    """
    context = ProgressiveContext()

    # Determine which scopes to query
    # When scope is PROJECT and include_global=True, query both project AND global
    scopes_to_query: list[tuple[MemoryScope, str | None]] = [(scope, scope_id)]
    if include_global and scope == MemoryScope.PROJECT and scope_id:
        scopes_to_query.append((MemoryScope.GLOBAL, None))

    # Retrieve each block in parallel for efficiency
    tasks: list[asyncio.Task[list[MemorySearchResult]]] = []
    task_keys: list[str] = []

    for query_scope, query_scope_id in scopes_to_query:
        if include_mandates:
            tasks.append(
                asyncio.create_task(
                    get_mandates(
                        scope=query_scope,
                        scope_id=query_scope_id,
                        query=query,
                        variant=variant,
                    )
                )
            )
            task_keys.append(f"mandates_{query_scope.value}")
        if include_guardrails:
            tasks.append(
                asyncio.create_task(
                    get_guardrails(
                        query,
                        scope=query_scope,
                        scope_id=query_scope_id,
                        variant=variant,
                    )
                )
            )
            task_keys.append(f"guardrails_{query_scope.value}")
        if include_reference:
            tasks.append(
                asyncio.create_task(
                    get_reference(
                        query,
                        scope=query_scope,
                        scope_id=query_scope_id,
                        variant=variant,
                    )
                )
            )
            task_keys.append(f"reference_{query_scope.value}")

    if tasks:
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Aggregate results from multiple scopes (project + global)
        for key, result in zip(task_keys, results, strict=True):
            if isinstance(result, Exception):
                logger.warning("Failed to get %s: %s", key, result)
                continue

            # Extract the block type (mandates, guardrails, reference) from key
            block_type = key.split("_")[0]  # e.g., "mandates_project" -> "mandates"
            existing = getattr(context, block_type, [])

            # Merge results, avoiding duplicates by UUID
            # Type narrow: result is list[MemorySearchResult] after Exception check
            result_list: list[MemorySearchResult] = result  # type: ignore[assignment]
            existing_uuids = {r.uuid for r in existing}
            for item in result_list:
                if item.uuid not in existing_uuids:
                    existing.append(item)
                    existing_uuids.add(item.uuid)

            setattr(context, block_type, existing)

    # Get memory settings
    settings = await get_memory_settings()
    budget = BudgetUsage(total_budget=settings.total_budget)

    # Kill switch: if memory injection is disabled, return empty context
    if not settings.enabled:
        logger.info("Memory injection disabled - returning empty context")
        context.mandates = []
        context.guardrails = []
        context.reference = []
        context.budget_usage = budget
        context.total_tokens = 0
        return context

    # Count tokens for all items (always needed for tracking)
    budget.mandates_tokens = sum(count_tokens(m.content) for m in context.mandates)
    budget.guardrails_tokens = sum(count_tokens(g.content) for g in context.guardrails)
    budget.reference_tokens = sum(count_tokens(r.content) for r in context.reference)

    # Apply budget enforcement only when budget_enabled is True
    # When budget_enabled is False, inject all memories without limits
    if settings.budget_enabled:
        # Proportional allocation: each tier gets a guaranteed percentage
        # This ensures all tiers get represented, not just mandates
        from .settings import (
            TIER_ALLOCATION_GUARDRAILS,
            TIER_ALLOCATION_MANDATES,
            TIER_ALLOCATION_REFERENCE,
        )

        total_budget = settings.total_budget
        mandates_cap = int(total_budget * TIER_ALLOCATION_MANDATES)
        guardrails_cap = int(total_budget * TIER_ALLOCATION_GUARDRAILS)
        reference_cap = int(total_budget * TIER_ALLOCATION_REFERENCE)

        # Phase 1: Filter mandates (50% cap)
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

        # Phase 2: Filter guardrails (30% cap)
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

        # Phase 3: Filter reference (20% cap)
        reference_tokens = 0
        filtered_reference = []
        for r in context.reference:
            tokens = count_tokens(r.content)
            if reference_tokens + tokens <= reference_cap:
                filtered_reference.append(r)
                reference_tokens += tokens
            else:
                logger.debug(
                    "Reference tier cap hit: %d/%d tokens", reference_tokens, reference_cap
                )
                break
        context.reference = filtered_reference
        budget.reference_tokens = reference_tokens

        # Log allocation summary
        logger.info(
            "Proportional allocation: M=%d/%d G=%d/%d R=%d/%d",
            mandates_tokens,
            mandates_cap,
            guardrails_tokens,
            guardrails_cap,
            reference_tokens,
            reference_cap,
        )
    else:
        logger.debug(
            "Budget enforcement disabled (budget_enabled=False) - injecting all %d memories (%d tokens)",
            len(context.mandates) + len(context.guardrails) + len(context.reference),
            budget.total_tokens,
        )

    context.budget_usage = budget
    context.total_tokens = budget.total_tokens

    # Build debug info for relevance debugger
    context.debug_info = {
        "mandates_count": len(context.mandates),
        "guardrails_count": len(context.guardrails),
        "reference_count": len(context.reference),
        "total_tokens": context.total_tokens,
        "budget_limit": settings.total_budget,
        "budget_hit": budget.hit_limit,
        "query": query[:100],  # Truncate for logging
    }

    logger.info(
        "Progressive context: mandates=%d guardrails=%d reference=%d tokens=%d/%d%s",
        len(context.mandates),
        len(context.guardrails),
        len(context.reference),
        context.total_tokens,
        settings.total_budget,
        " (budget exceeded)" if budget.hit_limit else "",
    )

    return context


def format_progressive_context(
    context: ProgressiveContext,
    include_citations: bool = True,
) -> str:
    """
    Format progressive context into a string for injection.

    Uses compact format to minimize token usage:
    - Mandates: bullet list with [M:uuid8] prefix (always injected)
    - Guardrails: bullet list with [G:uuid8] prefix
    - Reference: bullet list

    Args:
        context: ProgressiveContext to format
        include_citations: Whether to include citation IDs and instruction

    Returns:
        Formatted string ready for injection
    """
    parts: list[str] = []

    if context.mandates:
        parts.append(MANDATE_DIRECTIVE)
        for m in context.mandates:
            if include_citations and m.uuid:
                citation = format_mandate_citation(m.uuid)
                parts.append(f"- {citation} {m.content}")
            else:
                parts.append(f"- {m.content}")

    if context.guardrails:
        if parts:
            parts.append("")
        parts.append(GUARDRAIL_DIRECTIVE)
        for g in context.guardrails:
            if include_citations and g.uuid:
                citation = format_guardrail_citation(g.uuid)
                parts.append(f"- {citation} {g.content}")
            else:
                parts.append(f"- {g.content}")

    if context.reference:
        if parts:
            parts.append("")
        parts.append(REFERENCE_DIRECTIVE)
        for r in context.reference:
            parts.append(f"- {r.content}")

    # Add citation instruction if citations are included
    if include_citations and (context.mandates or context.guardrails):
        if parts:
            parts.append("")
        parts.append(CITATION_INSTRUCTION)

    return "\n".join(parts)


def estimate_tokens(text: str) -> int:
    """
    Estimate token count for a string.

    Uses simple character-based estimation (4 chars = 1 token).
    For more accurate counts, use tiktoken or model-specific tokenizers.

    Args:
        text: Text to estimate tokens for

    Returns:
        Estimated token count
    """
    return len(text) // CHARS_PER_TOKEN


def get_context_token_stats(context: ProgressiveContext) -> dict[str, Any]:
    """
    Get detailed token statistics for a progressive context.

    Useful for monitoring and debugging token usage per block.

    Args:
        context: ProgressiveContext to analyze

    Returns:
        Dict with token counts per block and total
    """
    mandate_chars = sum(len(r.content) for r in context.mandates)
    guardrail_chars = sum(len(r.content) for r in context.guardrails)
    reference_chars = sum(len(r.content) for r in context.reference)

    # Add overhead for formatting (headers, bullets, newlines)
    format_overhead = (
        (len(MANDATE_DIRECTIVE) + len(context.mandates) * 3 if context.mandates else 0)
        + (len(GUARDRAIL_DIRECTIVE) + len(context.guardrails) * 3 if context.guardrails else 0)
        + (len(REFERENCE_DIRECTIVE) + len(context.reference) * 3 if context.reference else 0)
    )

    return {
        "mandates_tokens": mandate_chars // CHARS_PER_TOKEN,
        "guardrails_tokens": guardrail_chars // CHARS_PER_TOKEN,
        "reference_tokens": reference_chars // CHARS_PER_TOKEN,
        "format_overhead_tokens": format_overhead // CHARS_PER_TOKEN,
        "total_tokens": (mandate_chars + guardrail_chars + reference_chars + format_overhead)
        // CHARS_PER_TOKEN,
        "mandates_count": len(context.mandates),
        "guardrails_count": len(context.guardrails),
        "reference_count": len(context.reference),
    }


def get_relevance_debug_info(context: ProgressiveContext) -> dict[str, Any]:
    """
    Get detailed relevance debug info for troubleshooting context injection.

    Includes memory IDs, categories, relevance scores, and content snippets.
    This is used by the relevance debugger to show why certain memories were
    or were not included.

    Args:
        context: ProgressiveContext to analyze

    Returns:
        Dict with detailed debug info for each memory item
    """

    def _format_item(r: MemorySearchResult) -> dict[str, Any]:
        return {
            "id": r.uuid[:8],  # Short ID for readability
            "score": round(r.relevance_score, 3),
            "snippet": r.content[:80] + "..." if len(r.content) > 80 else r.content,
            "created": r.created_at.isoformat()[:10],  # Just date
        }

    return {
        "mandates": [_format_item(r) for r in context.mandates],
        "guardrails": [_format_item(r) for r in context.guardrails],
        "reference": [_format_item(r) for r in context.reference],
        "stats": get_context_token_stats(context),
        "query": context.debug_info.get("query", ""),
    }


def format_relevance_debug_block(context: ProgressiveContext) -> str:
    """
    Format relevance debug info as an XML block for session context.

    Returns debug info in <memory-debug> format for human review.
    Only call this when DEBUG=true.

    Args:
        context: ProgressiveContext to format

    Returns:
        Formatted debug string
    """
    debug = get_relevance_debug_info(context)
    lines = ["<memory-debug>"]

    stats = debug["stats"]
    lines.append(f"Query: {debug['query']}")
    lines.append(
        f"Tokens: {stats['total_tokens']} (M:{stats['mandates_tokens']} G:{stats['guardrails_tokens']} R:{stats['reference_tokens']})"
    )
    lines.append("")

    if debug["mandates"]:
        lines.append("MANDATES:")
        for m in debug["mandates"]:
            lines.append(f"  [{m['id']}] score={m['score']}: {m['snippet']}")

    if debug["guardrails"]:
        lines.append("GUARDRAILS:")
        for g in debug["guardrails"]:
            lines.append(f"  [{g['id']}] score={g['score']}: {g['snippet']}")

    if debug["reference"]:
        lines.append("REFERENCE:")
        for r in debug["reference"]:
            lines.append(f"  [{r['id']}] score={r['score']}: {r['snippet']}")

    if not (debug["mandates"] or debug["guardrails"] or debug["reference"]):
        lines.append("No memories matched query")

    lines.append("</memory-debug>")
    return "\n".join(lines)


async def inject_progressive_context(
    messages: list[dict[str, Any]],
    scope: MemoryScope = MemoryScope.GLOBAL,
    scope_id: str | None = None,
    query: str | None = None,
    variant: str = "BASELINE",
    session_id: str | None = None,
    external_id: str | None = None,
    project_id: str | None = None,
    collect_metrics: bool = True,
) -> tuple[list[dict[str, Any]], ProgressiveContext]:
    """
    Inject 3-block progressive disclosure context into messages.

    This is the main entry point for progressive disclosure injection.

    Args:
        messages: List of message dicts with role and content
        scope: Memory scope for context retrieval
        scope_id: Project or task ID for scoping
        query: Optional explicit query; if None, extracts from last user message
        variant: A/B test variant (BASELINE, ENHANCED, MINIMAL, AGGRESSIVE)
        session_id: Session ID for metrics tracking
        external_id: External ID (e.g., task ID) for metrics tracking
        project_id: Project ID for metrics tracking
        collect_metrics: Whether to collect injection metrics (default: True)

    Returns:
        Tuple of (modified messages, ProgressiveContext with debug info)
    """
    start_time = time.monotonic()

    if not messages:
        return messages, ProgressiveContext()

    # Extract query from last user message if not provided
    if not query:
        for msg in reversed(messages):
            if msg.get("role") == "user":
                content = msg.get("content", "")
                if isinstance(content, str):
                    query = content[:500]
                elif isinstance(content, list):
                    text_parts = [
                        block.get("text", "")
                        for block in content
                        if isinstance(block, dict) and block.get("type") == "text"
                    ]
                    query = " ".join(text_parts)[:500]
                break

    if not query:
        return messages, ProgressiveContext()

    # Build progressive context
    context = await build_progressive_context(
        query=query,
        scope=scope,
        scope_id=scope_id,
    )

    # Format context for injection
    formatted = format_progressive_context(context)

    if not formatted:
        return messages, context

    # Wrap in memory context tags
    memory_block = f"{MEMORY_CONTEXT_START}\n{formatted}\n{MEMORY_CONTEXT_END}"

    # Inject into system message
    modified_messages = list(messages)
    first_msg = modified_messages[0] if modified_messages else None

    if first_msg and first_msg.get("role") == "system":
        existing_content = first_msg.get("content", "")
        modified_messages[0] = {
            "role": "system",
            "content": f"{existing_content}\n\n{memory_block}",
        }
    else:
        modified_messages.insert(0, {"role": "system", "content": memory_block})

    # Calculate injection latency
    latency_ms = int((time.monotonic() - start_time) * 1000)

    # Store variant in debug info for downstream use
    context.debug_info["variant"] = variant
    context.debug_info["injection_latency_ms"] = latency_ms

    logger.info(
        "Injected progressive context: variant=%s latency=%dms tokens=%d mandates=%d guardrails=%d reference=%d",
        variant,
        latency_ms,
        context.total_tokens,
        len(context.mandates),
        len(context.guardrails),
        len(context.reference),
    )

    # Collect metrics asynchronously (non-blocking)
    if collect_metrics:
        metrics = InjectionMetrics(
            injection_latency_ms=latency_ms,
            mandates_count=len(context.mandates),
            guardrails_count=len(context.guardrails),
            reference_count=len(context.reference),
            total_tokens=context.total_tokens,
            query=query,
            variant=variant,
            session_id=session_id,
            external_id=external_id,
            project_id=project_id,
            memories_loaded=context.get_loaded_uuids(),
        )
        record_injection_metrics(metrics)

    return modified_messages, context


# ============================================================================
# 2-Tier Context Functions (score-based selection)
# ============================================================================


async def build_global_context(
    scope: MemoryScope = MemoryScope.PROJECT,
    scope_id: str | None = None,
    task_description: str | None = None,
    variant: str = "BASELINE",
) -> str:
    """
    Build global context for task-start injection.

    Uses score-based selection with minimum relevance threshold.
    Retrieves system design and domain knowledge relevant to the task.

    Args:
        scope: Memory scope to query
        scope_id: Project or task ID
        task_description: Optional task description to improve search relevance
        variant: A/B variant for configuration

    Returns:
        Formatted context string for system prompt injection
    """
    from .scoring import MemoryScoreInput, score_memory
    from .variants import get_variant_config

    config = get_variant_config(variant)
    service = get_memory_service(scope=scope, scope_id=scope_id)

    query = task_description or "project architecture system design domain knowledge"

    # Search for system design content - fetch more, let scoring filter
    try:
        edges = await service._graphiti.search(
            query=f"system design architecture: {query}",
            group_ids=[service._group_id],
            num_results=50,
        )
    except Exception as e:
        logger.warning("Failed to search for global context: %s", e)
        return ""

    # Filter for relevant categories and score results
    relevant_categories = {MemoryCategory.REFERENCE}
    results: list[MemorySearchResult] = []

    for edge in edges:
        source_desc = getattr(edge, "source_description", "") or ""
        name = getattr(edge, "name", "") or ""
        category = service._infer_category(source_desc, name)

        if category not in relevant_categories:
            continue

        fact = edge.fact or ""
        if not fact:
            continue

        # Score using multi-factor scoring
        semantic_score = getattr(edge, "score", 0.5)
        score_input = MemoryScoreInput(
            semantic_similarity=semantic_score,
            confidence=75.0,
            tier="reference",
            created_at=edge.created_at,
        )
        score_result = score_memory(score_input, config)

        if not score_result.passes_threshold:
            continue

        results.append(
            MemorySearchResult(
                uuid=edge.uuid,
                content=fact,
                source=service._map_episode_type(getattr(edge, "source", None)),
                relevance_score=score_result.final_score,
                created_at=edge.created_at,
                facts=[fact],
            )
        )

    if not results:
        return ""

    # Sort by score descending
    results.sort(key=lambda r: r.relevance_score, reverse=True)

    # Format context
    parts = [GLOBAL_CONTEXT_DIRECTIVE.strip(), "", MEMORY_CONTEXT_START]
    parts.append("### System & Domain Knowledge")
    for r in results:
        parts.append(f"- {r.content}")

    parts.append(MEMORY_CONTEXT_END)
    return "\n".join(parts)


async def build_subtask_context(
    subtask_description: str,
    scope: MemoryScope = MemoryScope.PROJECT,
    scope_id: str | None = None,
    variant: str = "BASELINE",
) -> str:
    """
    Build JIT context for subtask execution.

    Uses score-based selection with minimum relevance threshold.
    Retrieves patterns and gotchas relevant to the specific subtask.

    Args:
        subtask_description: Description of the subtask being executed
        scope: Memory scope to query
        scope_id: Project or task ID
        variant: A/B variant for configuration

    Returns:
        Formatted context string for injection
    """
    from .variants import get_variant_config

    config = get_variant_config(variant)
    service = get_memory_service(scope=scope, scope_id=scope_id)

    # Get patterns and gotchas - use config threshold instead of hardcoded
    try:
        patterns, gotchas = await service.get_patterns_and_gotchas(
            query=subtask_description,
            num_results=50,  # Fetch more, scoring handles filtering
            min_score=config.min_relevance_threshold,
        )
    except Exception as e:
        logger.warning("Failed to get patterns/gotchas: %s", e)
        return ""

    if not patterns and not gotchas:
        return ""

    # Sort by score (patterns and gotchas already have relevance_score)
    patterns.sort(key=lambda r: r.relevance_score, reverse=True)
    gotchas.sort(key=lambda r: r.relevance_score, reverse=True)

    # Format context
    parts = [JIT_CONTEXT_DIRECTIVE.strip(), "", MEMORY_CONTEXT_START]

    if patterns:
        parts.append("### Relevant Patterns")
        for p in patterns:
            parts.append(f"- {p.content}")

    if gotchas:
        parts.append("")
        parts.append("### Known Gotchas (IMPORTANT)")
        for g in gotchas:
            parts.append(f"- {g.content}")

    parts.append(MEMORY_CONTEXT_END)
    return "\n".join(parts)


def parse_memory_group_id(memory_group_id: str | None) -> tuple[MemoryScope, str | None]:
    """
    Parse a memory_group_id string into explicit scope and scope_id.

    Format:
    - None, "global", "default" → (GLOBAL, None)
    - "project:<id>" → (PROJECT, <id>)

    Args:
        memory_group_id: String identifier for memory group

    Returns:
        Tuple of (MemoryScope, scope_id)
    """
    if not memory_group_id or memory_group_id in ("global", "default"):
        return MemoryScope.GLOBAL, None
    if memory_group_id.startswith("project:"):
        return MemoryScope.PROJECT, memory_group_id.split(":", 1)[1]
    # Explicit project scope requires "project:" prefix
    # Bare strings default to GLOBAL for cross-session knowledge transfer
    return MemoryScope.GLOBAL, None


async def inject_memory_context(
    messages: list[dict[str, Any]],
    scope: MemoryScope = MemoryScope.GLOBAL,
    scope_id: str | None = None,
    tier: ContextTier = ContextTier.BOTH,
    task_description: str | None = None,
    subtask_description: str | None = None,
    variant: str = "BASELINE",
) -> tuple[list[dict[str, Any]], int]:
    """
    Inject relevant memory context into messages.

    Uses score-based selection with minimum relevance threshold.
    Supports hybrid two-tier injection:
    - GLOBAL tier: System design and domain knowledge at task start
    - JIT tier: Patterns and gotchas for specific subtasks
    - BOTH tier: Combined context for single-shot requests

    Args:
        messages: List of message dicts with role and content
        scope: Memory scope for context retrieval (default: GLOBAL)
        scope_id: Project or task ID for scoping (only needed for PROJECT/TASK scope)
        tier: Which context tier to inject
        task_description: Task description for global context search
        subtask_description: Subtask description for JIT context search
        variant: A/B variant for configuration

    Returns:
        Tuple of (modified messages, number of items injected)
    """
    if not messages:
        return messages, 0

    context_parts: list[str] = []
    items_count = 0

    # Build context based on tier
    if tier in (ContextTier.GLOBAL, ContextTier.BOTH):
        # Determine task description from messages if not provided
        effective_task_desc = task_description
        if not effective_task_desc:
            for msg in messages:
                if msg.get("role") == "user":
                    content = msg.get("content", "")
                    if isinstance(content, str):
                        effective_task_desc = content[:500]  # Use first 500 chars
                    break

        global_ctx = await build_global_context(
            scope=scope,
            scope_id=scope_id,
            task_description=effective_task_desc,
            variant=variant,
        )
        if global_ctx:
            context_parts.append(global_ctx)
            items_count += 1

    if tier in (ContextTier.JIT, ContextTier.BOTH):
        # Use subtask_description or extract from last user message
        effective_subtask_desc = subtask_description
        if not effective_subtask_desc:
            for msg in reversed(messages):
                if msg.get("role") == "user":
                    content = msg.get("content", "")
                    if isinstance(content, str):
                        effective_subtask_desc = content
                    elif isinstance(content, list):
                        text_parts = [
                            block.get("text", "")
                            for block in content
                            if isinstance(block, dict) and block.get("type") == "text"
                        ]
                        effective_subtask_desc = " ".join(text_parts)
                    break

        if effective_subtask_desc:
            jit_ctx = await build_subtask_context(
                subtask_description=effective_subtask_desc,
                scope=scope,
                scope_id=scope_id,
                variant=variant,
            )
            if jit_ctx:
                context_parts.append(jit_ctx)
                items_count += 1

    if not context_parts:
        logger.debug("No memory context found for injection")
        return messages, 0

    # Combine context parts
    full_context = "\n\n".join(context_parts)

    # Inject into system message
    modified_messages = list(messages)
    first_msg = modified_messages[0] if modified_messages else None

    if first_msg and first_msg.get("role") == "system":
        existing_content = first_msg.get("content", "")
        modified_messages[0] = {
            "role": "system",
            "content": f"{existing_content}\n\n{full_context}",
        }
    else:
        modified_messages.insert(0, {"role": "system", "content": full_context})

    logger.info(
        "Injected memory context: tier=%s, scope=%s, items=%d",
        tier.value,
        scope.value,
        items_count,
    )

    return modified_messages, items_count
