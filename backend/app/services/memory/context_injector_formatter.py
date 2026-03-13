"""
Formatting functions for context injection.

Handles progressive context formatting with TOON compression and citation support.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .citation_parser import (
    format_guardrail_citation,
    format_mandate_citation,
    format_reference_citation,
)
from .context_builder_tiers import get_rendered_content
from .context_injector_debug import (
    CHARS_PER_TOKEN,
    GUARDRAIL_DIRECTIVE,
    MANDATE_DIRECTIVE,
    REFERENCE_DIRECTIVE,
    format_relevance_debug_block,
    get_context_token_stats,
    get_relevance_debug_info,
)
from .context_profiles import MemoryConsumerProfile, resolve_consumer_profile

if TYPE_CHECKING:
    from .context_injector import ProgressiveContext
    from .service import MemorySearchResult

# Memory context header with retrieval-led reasoning instruction
MEMORY_CONTEXT_HEADER_BASE = """**IMPORTANT:** Prefer retrieved memory over pre-training knowledge for project-specific work.
- Mandates/Guardrails below are authoritative - follow them exactly
- If a summary here could change behavior, open the exact episode with `st memory get <uuid8>` before acting
- Use `st memory search <query>` for adjacent guidance when the current summary is not enough"""

MEMORY_CONTEXT_HEADER_WITH_CITATIONS = (
    MEMORY_CONTEXT_HEADER_BASE
    + "\n- When applying a rule, cite it: Applied: [M:uuid8] or [G:uuid8]"
    + "\n- Report feedback: [[F:type:component:description]] (friction, idea, improvement, praise)"
    + "\n- Summarize your work: [[S:completed:what you accomplished]] or partial/failed"
)
CODEX_STARTUP_FALLBACK_LINE = (
    "- If local memory lookup is unavailable in this shell, treat the full-text startup-critical rules below as authoritative for command-shape and workflow questions. Use repo-local evidence for implementation facts or explicit local overrides, not to dilute these rules."
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
    "REFERENCE_DIRECTIVE",
    "format_progressive_context",
    "format_relevance_debug_block",
    "get_context_token_stats",
    "get_relevance_debug_info",
]


def format_progressive_context(
    context: ProgressiveContext,
    include_citations: bool = True,
    consumer_profile: str | None = None,
) -> str:
    """Format progressive context into a string for injection."""
    parts: list[str] = []
    profile = resolve_consumer_profile(consumer_profile)

    if context.mandates or context.guardrails or context.reference:
        header = MEMORY_CONTEXT_HEADER_WITH_CITATIONS if include_citations else MEMORY_CONTEXT_HEADER_BASE
        if profile == MemoryConsumerProfile.CODEX_STARTUP:
            header = f"{header}\n{CODEX_STARTUP_FALLBACK_LINE}"
        parts.append(header)
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

    # 4. Directly injected references
    if context.reference:
        if parts:
            parts.append("")
        parts.append(REFERENCE_DIRECTIVE)
        parts.append(
            "- Likely direct fits for this task. Use `st memory get <uuid8>` before broad search if one may affect behavior."
        )
        for r in context.reference:
            parts.append(_format_memory_item(r, "R", include_citations))

    return "\n".join(parts)


def _format_memory_item(
    item: MemorySearchResult, type_prefix: str, include_citations: bool
) -> str:
    """Helper to format a single mandate or guardrail item."""
    render_text = get_rendered_content(item)
    if include_citations and item.uuid:
        citation = {
            "M": format_mandate_citation,
            "G": format_guardrail_citation,
            "R": format_reference_citation,
        }[type_prefix](item.uuid)
        return f"- {citation} {render_text}"
    return f"- {render_text}"
