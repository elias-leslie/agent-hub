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
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from .citation_parser import format_guardrail_citation, format_mandate_citation
from .service import (
    MemoryCategory,
    MemoryScope,
    MemorySearchResult,
    MemorySource,
    get_memory_service,
)

logger = logging.getLogger(__name__)

# Context injection markers
MEMORY_CONTEXT_START = "<memory>"
MEMORY_CONTEXT_END = "</memory>"

# Maximum approximate tokens for context injection (rough estimate: 4 chars = 1 token)
MAX_CONTEXT_TOKENS = 2000
CHARS_PER_TOKEN = 4
MAX_CONTEXT_CHARS = MAX_CONTEXT_TOKENS * CHARS_PER_TOKEN

# Progressive disclosure token targets
# Note: These limits apply to each block individually, not total
MANDATE_TOKEN_LIMIT = 250  # ~1000 chars for golden standards (important, always inject)
GUARDRAIL_TOKEN_LIMIT = 150  # ~600 chars for anti-patterns
REFERENCE_TOKEN_LIMIT = 100  # ~400 chars for patterns


@dataclass
class ProgressiveContext:
    """Result of progressive disclosure context retrieval."""

    mandates: list[MemorySearchResult] = field(default_factory=list)
    guardrails: list[MemorySearchResult] = field(default_factory=list)
    reference: list[MemorySearchResult] = field(default_factory=list)
    total_tokens: int = 0
    debug_info: dict[str, Any] = field(default_factory=dict)

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
) -> list[MemorySearchResult]:
    """
    Get always-inject mandates: golden standards and critical constraints.

    Mandates are critical system knowledge that should always be injected:
    - Core coding principles (simplicity, async patterns, etc.)
    - Critical constraints from system design
    - Authentication and security patterns

    These are retrieved by querying golden standards directly from Neo4j
    (source_description contains 'golden_standard' or 'confidence:100').

    All golden standards are fetched; token truncation is the only limit.

    Args:
        scope: Memory scope to query
        scope_id: Project or task ID for scoping

    Returns:
        List of mandate search results, truncated to fit MANDATE_TOKEN_LIMIT
    """
    from .golden_standards import list_golden_standards

    try:
        golden = await list_golden_standards(
            scope=scope,
            scope_id=scope_id,
        )
        logger.debug("Retrieved %d golden standards for mandates", len(golden))
    except Exception as e:
        logger.warning("Failed to retrieve mandates: %s", e, exc_info=True)
        return []

    max_chars = MANDATE_TOKEN_LIMIT * CHARS_PER_TOKEN

    # Convert golden standard dicts to MemorySearchResult format
    results: list[MemorySearchResult] = []
    for g in golden:
        content = g.get("content") or ""
        if not content:
            logger.info("Skipping golden standard without content: %s", g.get("uuid"))
            continue

        # Convert neo4j.time.DateTime to Python datetime if needed
        created_at = g.get("created_at")
        if created_at is not None and hasattr(created_at, "to_native"):
            created_at = created_at.to_native()

        try:
            results.append(
                MemorySearchResult(
                    uuid=g.get("uuid", ""),
                    content=content,
                    source=MemorySource.SYSTEM,  # Golden standards are system-provided
                    relevance_score=1.0,  # Golden standards always max relevance
                    created_at=created_at,
                    facts=[content],
                )
            )
        except Exception as e:
            logger.warning(
                "Failed to create MemorySearchResult: %s (content=%s...)", e, content[:50]
            )

    logger.info("Created %d MemorySearchResults from golden standards", len(results))
    return _truncate_by_score(results, max_chars)


async def get_guardrails(
    query: str,
    scope: MemoryScope = MemoryScope.GLOBAL,
    scope_id: str | None = None,
    max_results: int = 5,
) -> list[MemorySearchResult]:
    """
    Get type-filtered guardrails: anti-patterns and gotchas.

    Guardrails are warnings about pitfalls and known issues relevant to
    the current query - things to avoid or be careful about.

    Args:
        query: Query to find relevant guardrails for
        scope: Memory scope to query
        scope_id: Project or task ID for scoping
        max_results: Maximum guardrails to return

    Returns:
        List of guardrail search results (anti-patterns, gotchas)
    """
    service = get_memory_service(scope=scope, scope_id=scope_id)

    try:
        # Search for warnings and pitfalls related to the query
        search_query = f"gotcha pitfall warning avoid error issue: {query}"
        edges = await service._graphiti.search(
            query=search_query,
            group_ids=[service._group_id],
            num_results=max_results * 2,
        )
    except Exception as e:
        logger.warning("Failed to retrieve guardrails: %s", e)
        return []

    results: list[MemorySearchResult] = []
    max_chars = GUARDRAIL_TOKEN_LIMIT * CHARS_PER_TOKEN

    for edge in edges:
        name = getattr(edge, "name", "") or ""
        fact = edge.fact or ""

        # Check if content is warning-related (gotcha, pitfall, error, issue)
        combined = f"{name} {fact}".lower()
        is_warning = any(
            kw in combined
            for kw in ["gotcha", "pitfall", "warning", "error", "issue", "avoid", "don't", "never"]
        )

        if is_warning:
            results.append(
                MemorySearchResult(
                    uuid=edge.uuid,
                    content=fact,
                    source=service._map_episode_type(getattr(edge, "source", None)),
                    relevance_score=getattr(edge, "score", 1.0),
                    created_at=edge.created_at,
                    facts=[fact] if fact else [],
                )
            )

        if len(results) >= max_results:
            break

    return _truncate_by_score(results, max_chars)


async def get_reference(
    query: str,
    scope: MemoryScope = MemoryScope.GLOBAL,
    scope_id: str | None = None,
    max_results: int = 5,
) -> list[MemorySearchResult]:
    """
    Get semantic search reference: patterns, workflows, and operational context.

    Reference items provide positive guidance on how to do things correctly -
    patterns, standards, and operational knowledge relevant to the query.

    Args:
        query: Query to find relevant reference for
        scope: Memory scope to query
        scope_id: Project or task ID for scoping
        max_results: Maximum reference items to return

    Returns:
        List of reference search results (patterns, workflows)
    """
    service = get_memory_service(scope=scope, scope_id=scope_id)

    try:
        # Search for patterns and standards related to the query
        search_query = f"pattern standard workflow command: {query}"
        edges = await service._graphiti.search(
            query=search_query,
            group_ids=[service._group_id],
            num_results=max_results * 2,
        )
    except Exception as e:
        logger.warning("Failed to retrieve reference: %s", e)
        return []

    results: list[MemorySearchResult] = []
    max_chars = REFERENCE_TOKEN_LIMIT * CHARS_PER_TOKEN

    for edge in edges:
        fact = edge.fact or ""

        # Accept any relevant search result that isn't a warning
        fact_lower = fact.lower()
        is_warning = any(
            kw in fact_lower
            for kw in ["gotcha", "pitfall", "warning", "error", "issue", "avoid", "don't", "never"]
        )

        if not is_warning and fact:
            results.append(
                MemorySearchResult(
                    uuid=edge.uuid,
                    content=fact,
                    source=service._map_episode_type(getattr(edge, "source", None)),
                    relevance_score=getattr(edge, "score", 1.0),
                    created_at=edge.created_at,
                    facts=[fact] if fact else [],
                )
            )

        if len(results) >= max_results:
            break

    return _truncate_by_score(results, max_chars)


async def build_progressive_context(
    query: str,
    scope: MemoryScope = MemoryScope.GLOBAL,
    scope_id: str | None = None,
    include_mandates: bool = True,
    include_guardrails: bool = True,
    include_reference: bool = True,
    include_global: bool = True,
) -> ProgressiveContext:
    """
    Build 3-block progressive disclosure context for a query.

    Combines:
    - Mandates: Always-inject golden standards (confidence=100)
    - Guardrails: Type-filtered anti-patterns (TROUBLESHOOTING_GUIDE)
    - Reference: Semantic search patterns (CODING_STANDARD, OPERATIONAL_CONTEXT)

    Args:
        query: Query to retrieve context for
        scope: Memory scope to query
        scope_id: Project or task ID for scoping
        include_mandates: Whether to include mandates block
        include_guardrails: Whether to include guardrails block
        include_reference: Whether to include reference block
        include_global: Whether to also include global scope when querying project scope

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
                asyncio.create_task(get_mandates(scope=query_scope, scope_id=query_scope_id))
            )
            task_keys.append(f"mandates_{query_scope.value}")
        if include_guardrails:
            tasks.append(
                asyncio.create_task(
                    get_guardrails(query, scope=query_scope, scope_id=query_scope_id)
                )
            )
            task_keys.append(f"guardrails_{query_scope.value}")
        if include_reference:
            tasks.append(
                asyncio.create_task(
                    get_reference(query, scope=query_scope, scope_id=query_scope_id)
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

    # Calculate total tokens
    total_chars = (
        sum(len(r.content) for r in context.mandates)
        + sum(len(r.content) for r in context.guardrails)
        + sum(len(r.content) for r in context.reference)
    )
    context.total_tokens = total_chars // CHARS_PER_TOKEN

    # Build debug info for relevance debugger
    context.debug_info = {
        "mandates_count": len(context.mandates),
        "guardrails_count": len(context.guardrails),
        "reference_count": len(context.reference),
        "total_tokens": context.total_tokens,
        "query": query[:100],  # Truncate for logging
    }

    logger.info(
        "Progressive context: mandates=%d guardrails=%d reference=%d tokens=%d",
        len(context.mandates),
        len(context.guardrails),
        len(context.reference),
        context.total_tokens,
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
) -> tuple[list[dict[str, Any]], ProgressiveContext]:
    """
    Inject 3-block progressive disclosure context into messages.

    This is the main entry point for progressive disclosure injection.

    Args:
        messages: List of message dicts with role and content
        scope: Memory scope for context retrieval
        scope_id: Project or task ID for scoping
        query: Optional explicit query; if None, extracts from last user message

    Returns:
        Tuple of (modified messages, ProgressiveContext with debug info)
    """
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

    logger.info(
        "Injected progressive context: tokens=%d mandates=%d guardrails=%d reference=%d",
        context.total_tokens,
        len(context.mandates),
        len(context.guardrails),
        len(context.reference),
    )

    return modified_messages, context


# ============================================================================
# Agent-Based Mandate Injection
# ============================================================================


async def get_mandates_by_tags(
    tags: list[str],
    scope: MemoryScope = MemoryScope.GLOBAL,
    scope_id: str | None = None,
) -> list[MemorySearchResult]:
    """
    Get mandates relevant to the given tags via semantic search.

    Tags like ["coding", "implementation"] or ["self-healing", "quick-fix"]
    are used to build a search query that finds relevant golden standards.

    Args:
        tags: List of semantic tags to search for
        scope: Memory scope to query
        scope_id: Project or task ID for scoping

    Returns:
        List of relevant mandate search results
    """
    if not tags:
        return await get_mandates(scope=scope, scope_id=scope_id)

    # Build search query from tags
    tag_query = " ".join(tags)

    service = get_memory_service(scope=scope, scope_id=scope_id)

    try:
        # Search for golden standards matching the tags
        search_query = f"golden standard critical constraint: {tag_query}"
        edges = await service._graphiti.search(
            query=search_query,
            group_ids=[service._group_id],
            num_results=10,
        )
    except Exception as e:
        logger.warning("Failed to search mandates by tags: %s", e)
        # Fall back to all mandates
        return await get_mandates(scope=scope, scope_id=scope_id)

    results: list[MemorySearchResult] = []
    max_chars = MANDATE_TOKEN_LIMIT * CHARS_PER_TOKEN

    for edge in edges:
        fact = edge.fact or ""
        if not fact:
            continue

        # Check if this is a golden standard
        source_desc = getattr(edge, "source_description", "") or ""
        is_golden = "golden_standard" in source_desc or "confidence:100" in source_desc

        if is_golden:
            results.append(
                MemorySearchResult(
                    uuid=edge.uuid,
                    content=fact,
                    source=MemorySource.SYSTEM,
                    relevance_score=getattr(edge, "score", 1.0),
                    created_at=edge.created_at,
                    facts=[fact],
                )
            )

    logger.info("Found %d mandates for tags %s", len(results), tags)
    return _truncate_by_score(results, max_chars)


async def build_agent_mandate_context(
    mandate_tags: list[str],
    scope: MemoryScope = MemoryScope.GLOBAL,
    scope_id: str | None = None,
) -> tuple[str, list[str]]:
    """
    Build mandate context for an agent based on its mandate_tags.

    This function is used by the OpenAI-compatible endpoint when processing
    agent:X model requests. It queries golden standards relevant to the
    agent's mandate_tags and formats them for injection.

    Args:
        mandate_tags: Tags from agent config (e.g., ["coding", "implementation"])
        scope: Memory scope to query
        scope_id: Project or task ID for scoping

    Returns:
        Tuple of (formatted_context, list_of_injected_uuids)
    """
    mandates = await get_mandates_by_tags(
        tags=mandate_tags,
        scope=scope,
        scope_id=scope_id,
    )

    if not mandates:
        return "", []

    # Format mandates with citations
    parts = [MANDATE_DIRECTIVE]
    for m in mandates:
        if m.uuid:
            citation = format_mandate_citation(m.uuid)
            parts.append(f"- {citation} {m.content}")
        else:
            parts.append(f"- {m.content}")

    parts.append("")
    parts.append(CITATION_INSTRUCTION)

    formatted = "\n".join(parts)
    uuids = [m.uuid for m in mandates if m.uuid]

    logger.info(
        "Built agent mandate context: %d mandates, %d chars",
        len(mandates),
        len(formatted),
    )

    return formatted, uuids


# ============================================================================
# Legacy 2-Tier Functions (preserved for backwards compatibility)
# ============================================================================


def _truncate_by_score(
    results: list[MemorySearchResult],
    max_chars: int,
) -> list[MemorySearchResult]:
    """
    Truncate results by relevance score to fit within character limit.

    Args:
        results: List of search results with scores
        max_chars: Maximum total characters

    Returns:
        Truncated list fitting within limit
    """
    # Sort by score descending
    sorted_results = sorted(results, key=lambda r: r.relevance_score, reverse=True)

    truncated = []
    current_chars = 0

    for result in sorted_results:
        content_chars = len(result.content)
        if current_chars + content_chars > max_chars:
            break
        truncated.append(result)
        current_chars += content_chars

    return truncated


async def build_global_context(
    scope: MemoryScope = MemoryScope.PROJECT,
    scope_id: str | None = None,
    task_description: str | None = None,
    max_results: int = 10,
) -> str:
    """
    Build global context for task-start injection.

    Retrieves system design and domain knowledge relevant to the task.

    Args:
        scope: Memory scope to query
        scope_id: Project or task ID
        task_description: Optional task description to improve search relevance
        max_results: Maximum results to include

    Returns:
        Formatted context string for system prompt injection
    """
    service = get_memory_service(scope=scope, scope_id=scope_id)

    query = task_description or "project architecture system design domain knowledge"

    # Search for system design content
    try:
        edges = await service._graphiti.search(
            query=f"system design architecture: {query}",
            group_ids=[service._group_id],
            num_results=max_results,
        )
    except Exception as e:
        logger.warning("Failed to search for global context: %s", e)
        return ""

    # Filter for relevant categories and build results
    relevant_categories = {MemoryCategory.SYSTEM_DESIGN, MemoryCategory.DOMAIN_KNOWLEDGE}
    results: list[MemorySearchResult] = []

    for edge in edges:
        source_desc = getattr(edge, "source_description", "") or ""
        name = getattr(edge, "name", "") or ""
        category = service._infer_category(source_desc, name)

        if category in relevant_categories:
            results.append(
                MemorySearchResult(
                    uuid=edge.uuid,
                    content=edge.fact or "",
                    source=service._map_episode_type(getattr(edge, "source", None)),
                    relevance_score=getattr(edge, "score", 1.0),
                    created_at=edge.created_at,
                    facts=[edge.fact] if edge.fact else [],
                )
            )

    if not results:
        return ""

    # Truncate to fit within limit
    truncated = _truncate_by_score(results, MAX_CONTEXT_CHARS // 2)  # Half for global

    # Format context
    parts = [GLOBAL_CONTEXT_DIRECTIVE.strip(), "", MEMORY_CONTEXT_START]

    if truncated:
        parts.append("### System & Domain Knowledge")
        for r in truncated:
            parts.append(f"- {r.content}")

    parts.append(MEMORY_CONTEXT_END)
    return "\n".join(parts)


async def build_subtask_context(
    subtask_description: str,
    scope: MemoryScope = MemoryScope.PROJECT,
    scope_id: str | None = None,
    max_results: int = 10,
) -> str:
    """
    Build JIT context for subtask execution.

    Retrieves patterns and gotchas relevant to the specific subtask.

    Args:
        subtask_description: Description of the subtask being executed
        scope: Memory scope to query
        scope_id: Project or task ID
        max_results: Maximum results per category

    Returns:
        Formatted context string for injection
    """
    service = get_memory_service(scope=scope, scope_id=scope_id)

    # Get patterns and gotchas using the dedicated method
    try:
        patterns, gotchas = await service.get_patterns_and_gotchas(
            query=subtask_description,
            num_results=max_results,
            min_score=0.4,
        )
    except Exception as e:
        logger.warning("Failed to get patterns/gotchas: %s", e)
        return ""

    if not patterns and not gotchas:
        return ""

    # Truncate combined results
    combined = patterns + gotchas
    truncated = _truncate_by_score(combined, MAX_CONTEXT_CHARS // 2)

    # Separate back into patterns and gotchas
    truncated_patterns = [r for r in truncated if r in patterns]
    truncated_gotchas = [r for r in truncated if r in gotchas]

    # Format context
    parts = [JIT_CONTEXT_DIRECTIVE.strip(), "", MEMORY_CONTEXT_START]

    if truncated_patterns:
        parts.append("### Relevant Patterns")
        for p in truncated_patterns:
            parts.append(f"- {p.content}")

    if truncated_gotchas:
        parts.append("")
        parts.append("### Known Gotchas (IMPORTANT)")
        for g in truncated_gotchas:
            parts.append(f"- ⚠️ {g.content}")

    parts.append(MEMORY_CONTEXT_END)
    return "\n".join(parts)


def parse_memory_group_id(memory_group_id: str | None) -> tuple[MemoryScope, str | None]:
    """
    Parse a memory_group_id string into explicit scope and scope_id.

    Format:
    - None, "global", "default" → (GLOBAL, None)
    - "project:<id>" → (PROJECT, <id>)
    - "task:<id>" → (TASK, <id>)

    Args:
        memory_group_id: String identifier for memory group

    Returns:
        Tuple of (MemoryScope, scope_id)
    """
    if not memory_group_id or memory_group_id in ("global", "default"):
        return MemoryScope.GLOBAL, None
    if memory_group_id.startswith("project:"):
        return MemoryScope.PROJECT, memory_group_id.split(":", 1)[1]
    if memory_group_id.startswith("task:"):
        return MemoryScope.TASK, memory_group_id.split(":", 1)[1]
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
    max_facts: int = 10,
) -> tuple[list[dict[str, Any]], int]:
    """
    Inject relevant memory context into messages.

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
        max_facts: Maximum facts to include per tier

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
            max_results=max_facts,
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
                max_results=max_facts,
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
