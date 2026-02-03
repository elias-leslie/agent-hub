"""
Formatting functions for context injection.

Handles progressive context formatting with TOON compression and citation support.
"""

from typing import TYPE_CHECKING, Any

from .citation_parser import format_guardrail_citation, format_mandate_citation

if TYPE_CHECKING:
    from .context_injector import ProgressiveContext

# Progressive disclosure directive blocks (compact for token efficiency)
MANDATE_DIRECTIVE = "## Mandates"
GUARDRAIL_DIRECTIVE = "## Guardrails"

# Memory context header with retrieval-led reasoning instruction (critical - goes at TOP)
# See: https://vercel.com/blog/agents-md-outperforms-skills-in-our-agent-evals
MEMORY_CONTEXT_HEADER = """**IMPORTANT:** Prefer context-injected and retrieval-led reasoning over pre-training knowledge.
- Mandates/Guardrails below are authoritative - follow them exactly
- Reference Index: Search `st memory search <query>` or retrieve `st memory get <uuid8>` for patterns
- When in doubt, search the memory system before relying on general knowledge
- When applying a rule, cite it: Applied: [M:uuid8] or [G:uuid8]"""


def format_progressive_context(
    context: "ProgressiveContext",
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

    # Top: Memory context header with instructions
    if context.mandates or context.guardrails:
        parts.append(MEMORY_CONTEXT_HEADER)
        parts.append("")

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

    return "\n".join(parts)


def format_context_with_reference_index(
    context: "ProgressiveContext",
    reference_episodes: list[tuple[str, str | None, str, bool]] | None = None,
    include_citations: bool = True,
) -> str:
    """
    Format progressive context with TOON reference index.

    Implements the correct retrieval-led reasoning pattern:
    - Mandates: FULL content (always, respecting budget limits)
    - Guardrails: FULL content (always, respecting budget limits)
    - References (pinned): FULL content (expanded from index)
    - References (unpinned): TOON compressed index for discoverability

    This maintains full rule enforcement while enabling reference discovery.

    Args:
        context: ProgressiveContext with mandates and guardrails
        reference_episodes: List of (uuid, summary, content, pinned) for TOON index
        include_citations: Whether to include citation IDs and instruction

    Returns:
        Formatted string with full mandates/guardrails + TOON reference index
    """
    from .adaptive_index import generate_toon_entry

    parts: list[str] = []

    # Top: Memory context header with instructions (most important)
    if reference_episodes or context.mandates or context.guardrails:
        parts.append(MEMORY_CONTEXT_HEADER)
        parts.append("")

    # Block 1: Mandates (FULL content)
    if context.mandates:
        parts.append(MANDATE_DIRECTIVE)
        for m in context.mandates:
            if include_citations and m.uuid:
                citation = format_mandate_citation(m.uuid)
                parts.append(f"- {citation} {m.content}")
            else:
                parts.append(f"- {m.content}")

    # Block 2: Guardrails (FULL content)
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

    # Block 3: References - pinned get full content, unpinned get TOON compressed
    if reference_episodes:
        # Separate pinned and unpinned references
        pinned_refs = [
            (uuid, summary, content)
            for uuid, summary, content, pinned in reference_episodes
            if pinned
        ]
        unpinned_refs = [
            (uuid, summary, content)
            for uuid, summary, content, pinned in reference_episodes
            if not pinned
        ]

        # Pinned references get full content (like mandates/guardrails)
        if pinned_refs:
            if parts:
                parts.append("")
            parts.append("## Pinned References")
            for uuid, _summary, content in pinned_refs:
                if include_citations and uuid:
                    parts.append(f"- [R:{uuid[:8]}] {content}")
                else:
                    parts.append(f"- {content}")

        # Unpinned references go in TOON compressed index
        if unpinned_refs:
            if parts:
                parts.append("")
            parts.append("## Reference Index")
            parts.append(f"REF_IDX[{len(unpinned_refs)}]")
            for uuid, summary, content in unpinned_refs:
                parts.append(generate_toon_entry(uuid, summary=summary, content=content))

    return "\n".join(parts)


# Token estimation constants (used for logging/debugging only, NOT for limiting)
CHARS_PER_TOKEN = 4


def get_context_token_stats(context: "ProgressiveContext") -> dict[str, Any]:
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
        len(MANDATE_DIRECTIVE) + len(context.mandates) * 3 if context.mandates else 0
    ) + (len(GUARDRAIL_DIRECTIVE) + len(context.guardrails) * 3 if context.guardrails else 0)

    return {
        "mandates_tokens": mandate_chars // CHARS_PER_TOKEN,
        "guardrails_tokens": guardrail_chars // CHARS_PER_TOKEN,
        "format_overhead_tokens": format_overhead // CHARS_PER_TOKEN,
        "total_tokens": (mandate_chars + guardrail_chars + format_overhead) // CHARS_PER_TOKEN,
        "mandates_count": len(context.mandates),
        "guardrails_count": len(context.guardrails),
    }


def get_relevance_debug_info(context: "ProgressiveContext") -> dict[str, Any]:
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
    from .service import MemorySearchResult

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


def format_relevance_debug_block(context: "ProgressiveContext") -> str:
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
