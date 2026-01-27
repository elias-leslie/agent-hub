"""
Context injection service for memory-augmented completions.

Implements 3-block progressive disclosure context injection:
- Block 1 (Mandates): Always-inject golden standards (confidence=100), critical constraints
- Block 2 (Guardrails): Type-filtered anti-patterns and gotchas (TROUBLESHOOTING_GUIDE)
- Block 3 (Reference): Semantic search for patterns and workflows (CODING_STANDARD, OPERATIONAL_CONTEXT)

This ensures relevant context surfaces when needed without overwhelming
the context window.

"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from .budget import BudgetUsage, count_tokens
from .citation_parser import format_guardrail_citation, format_mandate_citation
from .graphiti_client import get_graphiti
from .metrics_collector import InjectionMetrics, record_injection_metrics
from .service import (
    MemoryScope,
    MemorySearchResult,
    MemorySource,
    build_group_id,
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
      AND COALESCE(e.vector_indexed, true) = true
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



# Progressive disclosure directive blocks (compact for token efficiency)
MANDATE_DIRECTIVE = "## Mandates"
GUARDRAIL_DIRECTIVE = "## Guardrails"

# Citation instruction for LLM (compact)
CITATION_INSTRUCTION = """When applying a rule, cite it: Applied: [M:uuid8] or [G:uuid8]"""


# ============================================================================
# 3-Block Progressive Disclosure Functions
# ============================================================================


async def get_mandates(
    scope: MemoryScope = MemoryScope.GLOBAL,
    scope_id: str | None = None,
) -> list[MemorySearchResult]:
    """
    Get all mandates for a scope (deterministic injection).

    Uses injection_tier='mandate' field for filtering.
    Returns ALL non-demoted mandates - no scoring or thresholds.
    Mandates are critical system knowledge that must always be injected.

    Args:
        scope: Memory scope to query
        scope_id: Project or task ID for scoping

    Returns:
        List of all non-demoted mandate search results
    """
    from .adaptive_index import get_adaptive_index

    # Get adaptive index for demotion logic only
    adaptive_index = await get_adaptive_index()
    demoted_uuids = {e.uuid for e in adaptive_index.entries if e.is_demoted}

    # Get mandates by injection_tier field
    episodes = await get_episodes_by_tier("mandate", scope, scope_id)
    logger.debug("Retrieved %d mandate episodes", len(episodes))

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

        try:
            results.append(
                MemorySearchResult(
                    uuid=uuid,
                    content=content,
                    source=MemorySource.SYSTEM,
                    relevance_score=1.0,  # All mandates are equally important
                    created_at=created_at,
                    facts=[content],
                )
            )
        except Exception as e:
            logger.warning(
                "Failed to create MemorySearchResult: %s (content=%s...)", e, content[:50]
            )

    logger.info(
        "Mandate injection: %d/%d included (demoted=%d)",
        len(results),
        len(episodes),
        len(demoted_uuids),
    )
    return results


async def get_guardrails(
    scope: MemoryScope = MemoryScope.GLOBAL,
    scope_id: str | None = None,
) -> list[MemorySearchResult]:
    """
    Get all guardrails for a scope (deterministic injection).

    Uses injection_tier='guardrail' field for filtering.
    Returns ALL guardrails - no scoring or thresholds.
    Guardrails are anti-patterns that must always be injected.

    Args:
        scope: Memory scope to query
        scope_id: Project or task ID for scoping

    Returns:
        List of all guardrail search results
    """
    # Get guardrails by injection_tier field
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

        results.append(
            MemorySearchResult(
                uuid=uuid,
                content=content,
                source=MemorySource.SYSTEM,
                relevance_score=1.0,  # All guardrails are equally important
                created_at=created_at,
                facts=[content],
            )
        )

    logger.info("Guardrail injection: %d included", len(results))
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
    include_global: bool = True,
) -> ProgressiveContext:
    """
    Build 2-block progressive context (mandates + guardrails).

    Deterministic injection: ALL mandates and guardrails for the scope are injected.
    No scoring, no thresholds - just demotion filtering for mandates.

    Reference items are NOT included at SessionStart. For on-demand lookup,
    use the /api/memory/search endpoint when a real task context exists.

    Args:
        query: Query for context (unused for mandates/guardrails, kept for API compat)
        scope: Memory scope to query
        scope_id: Project or task ID for scoping
        include_mandates: Whether to include mandates block
        include_guardrails: Whether to include guardrails block
        include_global: Whether to also include global scope when querying project scope

    Returns:
        ProgressiveContext with mandates and guardrails
    """
    context = ProgressiveContext()

    # Determine which scopes to query
    # When scope is PROJECT and include_global=True, query both project AND global
    scopes_to_query: list[tuple[MemoryScope, str | None]] = [(scope, scope_id)]
    if include_global and scope == MemoryScope.PROJECT and scope_id:
        scopes_to_query.append((MemoryScope.GLOBAL, None))

    # Retrieve mandates and guardrails in parallel
    tasks: list[asyncio.Task[list[MemorySearchResult]]] = []
    task_keys: list[str] = []

    for query_scope, query_scope_id in scopes_to_query:
        if include_mandates:
            tasks.append(
                asyncio.create_task(
                    get_mandates(
                        scope=query_scope,
                        scope_id=query_scope_id,
                    )
                )
            )
            task_keys.append(f"mandates_{query_scope.value}")
        if include_guardrails:
            tasks.append(
                asyncio.create_task(
                    get_guardrails(
                        scope=query_scope,
                        scope_id=query_scope_id,
                    )
                )
            )
            task_keys.append(f"guardrails_{query_scope.value}")

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
        context.budget_usage = budget
        context.total_tokens = 0
        return context

    # Count tokens for mandates and guardrails
    budget.mandates_tokens = sum(count_tokens(m.content) for m in context.mandates)
    budget.guardrails_tokens = sum(count_tokens(g.content) for g in context.guardrails)

    # Apply budget enforcement only when budget_enabled is True
    # With reference removed, mandates get 60% and guardrails get 40%
    if settings.budget_enabled:
        total_budget = settings.total_budget
        mandates_cap = int(total_budget * 0.6)
        guardrails_cap = int(total_budget * 0.4)

        # Filter mandates by budget cap
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

        # Filter guardrails by budget cap
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

    # Build debug info
    context.debug_info = {
        "mandates_count": len(context.mandates),
        "guardrails_count": len(context.guardrails),
        "total_tokens": context.total_tokens,
        "budget_limit": settings.total_budget,
        "budget_hit": budget.hit_limit,
        "query": query[:100] if query else "",
    }

    logger.info(
        "Progressive context: mandates=%d guardrails=%d tokens=%d/%d%s",
        len(context.mandates),
        len(context.guardrails),
        context.total_tokens,
        settings.total_budget,
        " (budget exceeded)" if budget.hit_limit else "",
    )

    return context


SEARCH_INSTRUCTION = """For additional context (coding patterns, operational procedures), use: /api/memory/search?query=<topic>"""


def format_progressive_context(
    context: ProgressiveContext,
    include_citations: bool = True,
) -> str:
    """
    Format progressive context into a string for injection.

    Uses compact format to minimize token usage:
    - Mandates: bullet list with [M:uuid8] prefix (always injected)
    - Guardrails: bullet list with [G:uuid8] prefix
    - Search instruction for on-demand reference lookup

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

    # Add citation instruction and search instruction
    if include_citations and (context.mandates or context.guardrails):
        if parts:
            parts.append("")
        parts.append(CITATION_INSTRUCTION)
        parts.append(SEARCH_INSTRUCTION)

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

    # Add overhead for formatting (headers, bullets, newlines)
    format_overhead = (
        (len(MANDATE_DIRECTIVE) + len(context.mandates) * 3 if context.mandates else 0)
        + (len(GUARDRAIL_DIRECTIVE) + len(context.guardrails) * 3 if context.guardrails else 0)
    )

    return {
        "mandates_tokens": mandate_chars // CHARS_PER_TOKEN,
        "guardrails_tokens": guardrail_chars // CHARS_PER_TOKEN,
        "format_overhead_tokens": format_overhead // CHARS_PER_TOKEN,
        "total_tokens": (mandate_chars + guardrail_chars + format_overhead)
        // CHARS_PER_TOKEN,
        "mandates_count": len(context.mandates),
        "guardrails_count": len(context.guardrails),
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
        f"Tokens: {stats['total_tokens']} (M:{stats['mandates_tokens']} G:{stats['guardrails_tokens']})"
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

    if not (debug["mandates"] or debug["guardrails"]):
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
    Inject mandates and guardrails context into messages.

    This is the main entry point for memory injection at SessionStart.
    Reference items are NOT injected here - use /api/memory/search for on-demand lookup.

    Args:
        messages: List of message dicts with role and content
        scope: Memory scope for context retrieval
        scope_id: Project or task ID for scoping
        query: Optional explicit query (kept for API compatibility)
        variant: A/B test variant (kept for API compatibility)
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
        "Injected progressive context: variant=%s latency=%dms tokens=%d mandates=%d guardrails=%d",
        variant,
        latency_ms,
        context.total_tokens,
        len(context.mandates),
        len(context.guardrails),
    )

    # Collect metrics asynchronously (non-blocking)
    if collect_metrics:
        metrics = InjectionMetrics(
            injection_latency_ms=latency_ms,
            mandates_count=len(context.mandates),
            guardrails_count=len(context.guardrails),
            reference_count=0,  # Reference removed from SessionStart
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
    return MemoryScope.GLOBAL, None
