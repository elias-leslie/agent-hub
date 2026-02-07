"""
Debug and statistics functions for context injection.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .context_injector import ProgressiveContext
    from .service import MemorySearchResult

# Token estimation constants (used for logging/debugging only, NOT for limiting)
CHARS_PER_TOKEN = 4

# Progressive disclosure directive blocks
MANDATE_DIRECTIVE = "## Mandates"
GUARDRAIL_DIRECTIVE = "## Guardrails"


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


def get_relevance_debug_info(context: ProgressiveContext) -> dict[str, Any]:
    """
    Get detailed relevance debug info for troubleshooting context injection.

    Includes memory IDs, categories, relevance scores, and content snippets.

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
