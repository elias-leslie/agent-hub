"""
Debug and statistics functions for context injection.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .context_builder_tiers import get_rendered_content

if TYPE_CHECKING:
    from .context_injector import ProgressiveContext
    from .service import MemorySearchResult

# Token estimation constants (used for logging/debugging only, NOT for limiting)
CHARS_PER_TOKEN = 4

# Progressive disclosure directive blocks
MANDATE_DIRECTIVE = "## Mandates"
GUARDRAIL_DIRECTIVE = "## Guardrails"
REFERENCE_DIRECTIVE = "## References"


def get_context_token_stats(context: ProgressiveContext) -> dict[str, Any]:
    """
    Get detailed token statistics for a progressive context.

    Uses the currently rendered prompt text, not the full stored episode body.

    Args:
        context: ProgressiveContext to analyze

    Returns:
        Dict with token counts per block and total
    """
    mandate_chars = sum(len(get_rendered_content(r)) for r in context.mandates)
    guardrail_chars = sum(len(get_rendered_content(r)) for r in context.guardrails)
    reference_chars = sum(len(get_rendered_content(r)) for r in context.reference)

    # Add overhead for formatting (headers, bullets, newlines)
    format_overhead = (
        len(MANDATE_DIRECTIVE) + len(context.mandates) * 3 if context.mandates else 0
    ) + (len(GUARDRAIL_DIRECTIVE) + len(context.guardrails) * 3 if context.guardrails else 0) + (
        len(REFERENCE_DIRECTIVE) + len(context.reference) * 3 if context.reference else 0
    )

    return {
        "mandates_tokens": mandate_chars // CHARS_PER_TOKEN,
        "guardrails_tokens": guardrail_chars // CHARS_PER_TOKEN,
        "reference_tokens": reference_chars // CHARS_PER_TOKEN,
        "format_overhead_tokens": format_overhead // CHARS_PER_TOKEN,
        "total_tokens": (
            mandate_chars + guardrail_chars + reference_chars + format_overhead
        ) // CHARS_PER_TOKEN,
        "mandates_count": len(context.mandates),
        "guardrails_count": len(context.guardrails),
        "reference_count": len(context.reference),
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
        rendered = get_rendered_content(r)
        return {
            "id": r.uuid[:8],  # Short ID for readability
            "score": round(r.relevance_score, 3),
            "snippet": rendered[:80] + "..." if len(rendered) > 80 else rendered,
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
        "Tokens: "
        f"{stats['total_tokens']} "
        f"(M:{stats['mandates_tokens']} G:{stats['guardrails_tokens']} R:{stats['reference_tokens']})"
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
        lines.append("REFERENCES:")
        for r in debug["reference"]:
            lines.append(f"  [{r['id']}] score={r['score']}: {r['snippet']}")

    if not (debug["mandates"] or debug["guardrails"] or debug["reference"]):
        lines.append("No memories matched query")

    lines.append("</memory-debug>")
    return "\n".join(lines)
