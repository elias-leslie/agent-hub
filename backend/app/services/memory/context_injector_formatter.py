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
    CAPABILITY_INDEX_DIRECTIVE,
    CHARS_PER_TOKEN,
    GUARDRAIL_DIRECTIVE,
    MANDATE_DIRECTIVE,
    REFERENCE_DIRECTIVE,
    REFERENCE_INDEX_DIRECTIVE,
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
- If a summary here could change behavior, open the exact episode with `st memory get <uuid8>` before acting
- If the request says the rule is vague, remembered, or not exact, treat that as a trigger to open the exact episode first
- Use `st memory search <query>` for adjacent guidance when the current summary is not enough"""

MEMORY_CONTEXT_HEADER_WITH_CITATIONS = (
    MEMORY_CONTEXT_HEADER_BASE
    + "\n- Report feedback: [[F:type:component:description]] (friction, idea, improvement, praise)"
)
STARTUP_FALLBACK_LINE = (
    "- If local memory lookup is unavailable in this shell, treat the full-text startup-critical rules below as authoritative for command-shape and workflow questions. Use repo-local evidence for implementation facts or explicit local overrides, not to dilute these rules."
)
# Backwards-compatible alias for the prior codex-only constant name.
CODEX_STARTUP_FALLBACK_LINE = STARTUP_FALLBACK_LINE

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
    mandates = getattr(context, "mandates", [])
    guardrails = getattr(context, "guardrails", [])
    reference_index = getattr(context, "reference_index", [])
    references = getattr(context, "reference", [])

    if mandates or guardrails or reference_index or references:
        parts.append(_build_memory_context_header(context, include_citations, profile))
        parts.append("")

    # 2. Mandates
    if mandates:
        parts.append(MANDATE_DIRECTIVE)
        for m in mandates:
            parts.append(_format_memory_item(m, "M", include_citations))

    # 3. Guardrails
    if guardrails:
        if parts:
            parts.append("")
        parts.append(GUARDRAIL_DIRECTIVE)
        for g in guardrails:
            parts.append(_format_memory_item(g, "G", include_citations))

    capability_index = [
        item for item in reference_index if getattr(item, "context_kind", None) == "capability"
    ]
    general_index = [
        item for item in reference_index if getattr(item, "context_kind", None) != "capability"
    ]

    if capability_index:
        if parts:
            parts.append("")
        parts.append(CAPABILITY_INDEX_DIRECTIVE)
        parts.append(
            "- Lightweight catalog of tools and control surfaces for this consumer."
            "\n- Open the exact episode with `st memory get <uuid8>` before acting when command or workflow shape matters."
        )
        for item in capability_index:
            parts.append(_format_index_item(item, "R", include_citations))

    if general_index:
        if parts:
            parts.append("")
        parts.append(REFERENCE_INDEX_DIRECTIVE)
        parts.append(
            "- Passive lookup index for adjacent docs that may matter soon."
            "\n- Keep these as lookup hints; fetch the exact episode before relying on one."
        )
        for item in general_index:
            parts.append(_format_index_item(item, "R", include_citations))

    # 4. Directly injected references
    if references:
        if parts:
            parts.append("")
        parts.append(REFERENCE_DIRECTIVE)
        parts.append(
            "- Likely direct fits for this task. Use `st memory get <uuid8>` before broad search if one may affect behavior."
            "\n- When a reference informs your work, cite it inline as [R:uuid8] so the system can measure reference quality."
        )
        for r in references:
            parts.append(_format_memory_item(r, "R", include_citations))

    return "\n".join(parts)


def _build_memory_context_header(
    context: ProgressiveContext,
    include_citations: bool,
    profile: MemoryConsumerProfile,
) -> str:
    header = MEMORY_CONTEXT_HEADER_WITH_CITATIONS if include_citations else MEMORY_CONTEXT_HEADER_BASE
    lines = header.splitlines()
    if getattr(context, "mandates", []) or getattr(context, "guardrails", []):
        lines.insert(1, "- Mandates/Guardrails below are authoritative - follow them exactly")
        if include_citations:
            lines.insert(2, "- When applying a rule, cite it: Applied: [M:uuid8] or [G:uuid8]")
    if profile == MemoryConsumerProfile.AGENT_STARTUP:
        lines.append(STARTUP_FALLBACK_LINE)
    return "\n".join(lines)


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


def _format_index_item(
    item: MemorySearchResult,
    type_prefix: str,
    include_citations: bool,
) -> str:
    """Format a reference-index line using the compact rendered content."""
    render_text = get_rendered_content(item)
    if include_citations and item.uuid:
        citation = {
            "M": format_mandate_citation,
            "G": format_guardrail_citation,
            "R": format_reference_citation,
        }[type_prefix](item.uuid)
        return f"- {citation} {render_text}"
    return f"- {render_text}"
