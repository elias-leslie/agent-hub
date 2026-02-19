"""
Formatting functions for context injection.

Handles progressive context formatting with TOON compression and citation support.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .citation_parser import format_guardrail_citation, format_mandate_citation
from .context_injector_debug import (
    CHARS_PER_TOKEN,
    GUARDRAIL_DIRECTIVE,
    MANDATE_DIRECTIVE,
    format_relevance_debug_block,
    get_context_token_stats,
    get_relevance_debug_info,
)

if TYPE_CHECKING:
    from .context_injector import ProgressiveContext
    from .service import MemorySearchResult

# Memory context header with retrieval-led reasoning instruction
MEMORY_CONTEXT_HEADER_BASE = """**IMPORTANT:** Prefer context-injected and retrieval-led reasoning over pre-training knowledge.
- Mandates/Guardrails below are authoritative - follow them exactly
- Reference Index: Search `st memory search <query>` or retrieve `st memory get <uuid8>` for patterns
- When in doubt, search the memory system before relying on general knowledge"""

MEMORY_CONTEXT_HEADER_WITH_CITATIONS = (
    MEMORY_CONTEXT_HEADER_BASE
    + "\n- When applying a rule, cite it: Applied: [M:uuid8] or [G:uuid8]"
    + "\n- Report feedback (friction, ideas, improvements, praise): `st feedback report <component> 'title' --type <type>`"
)

# Keep for backward compatibility
MEMORY_CONTEXT_HEADER = MEMORY_CONTEXT_HEADER_WITH_CITATIONS

__all__ = [
    "CHARS_PER_TOKEN",
    "GUARDRAIL_DIRECTIVE",
    "MANDATE_DIRECTIVE",
    "MEMORY_CONTEXT_HEADER",
    "MEMORY_CONTEXT_HEADER_BASE",
    "MEMORY_CONTEXT_HEADER_WITH_CITATIONS",
    "format_context_with_reference_index",
    "format_progressive_context",
    "format_relevance_debug_block",
    "get_context_token_stats",
    "get_relevance_debug_info",
]


def format_progressive_context(
    context: ProgressiveContext,
    include_citations: bool = True,
) -> str:
    """Format progressive context into a string for injection."""
    return format_context_with_reference_index(
        context,
        reference_episodes=None,
        include_citations=include_citations,
    )


def format_context_with_reference_index(
    context: ProgressiveContext,
    reference_episodes: list[tuple[str, str | None, str, bool]] | None = None,
    include_citations: bool = True,
) -> str:
    """Format progressive context with TOON reference index."""
    parts: list[str] = []

    # 1. Header
    if reference_episodes or context.mandates or context.guardrails:
        parts.append(
            MEMORY_CONTEXT_HEADER_WITH_CITATIONS if include_citations else MEMORY_CONTEXT_HEADER_BASE
        )
        parts.append("")

    # 2. Mandates
    if context.mandates:
        parts.append(MANDATE_DIRECTIVE)
        for m in context.mandates:
            parts.append(_format_memory_item(m, "M", include_citations))

    # 3. Guardrails
    if context.guardrails:
        if parts:
            parts.append("")
        parts.append(GUARDRAIL_DIRECTIVE)
        for g in context.guardrails:
            parts.append(_format_memory_item(g, "G", include_citations))

    # 4. References
    if reference_episodes:
        parts.extend(_format_references(reference_episodes, include_citations))

    return "\n".join(parts)


def _format_memory_item(
    item: MemorySearchResult, type_prefix: str, include_citations: bool
) -> str:
    """Helper to format a single mandate or guardrail item."""
    if include_citations and item.uuid:
        citation = (
            format_mandate_citation(item.uuid)
            if type_prefix == "M"
            else format_guardrail_citation(item.uuid)
        )
        return f"- {citation} {item.content}"
    return f"- {item.content}"


def _format_references(
    reference_episodes: list[tuple[str, str | None, str, bool]],
    include_citations: bool,
) -> list[str]:
    """Helper to format pinned and unpinned references."""
    from .adaptive_index import generate_toon_entry

    parts: list[str] = []
    pinned = [r for r in reference_episodes if r[3]]
    unpinned = [r for r in reference_episodes if not r[3]]

    if pinned:
        parts.append("\n## Pinned References")
        for uuid, _, content, _ in pinned:
            cit = f"[R:{uuid[:8]}] " if include_citations and uuid else ""
            parts.append(f"- {cit}{content}")

    if unpinned:
        parts.append("\n## Reference Index")
        parts.append(f"REF_IDX[{len(unpinned)}]")
        for uuid, summary, content, _ in unpinned:
            parts.append(generate_toon_entry(uuid, summary=summary, content=content))

    return parts
