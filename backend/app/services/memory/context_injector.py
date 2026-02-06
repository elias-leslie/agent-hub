"""Context injection service for memory-augmented completions.

Thin orchestration layer that:
1. Calls build_progressive_context() from context_builder
2. Formats the result via context_injector_formatter
3. Optionally prepends continuity context
4. Injects into the message list

The heavy lifting (block retrieval, budget enforcement) lives in context_builder.py.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from .context_builder import ProgressiveContext, build_progressive_context
from .context_injector_formatter import (
    CHARS_PER_TOKEN,
    GUARDRAIL_DIRECTIVE,
    MANDATE_DIRECTIVE,
    MEMORY_CONTEXT_HEADER,
    format_context_with_reference_index,
    format_progressive_context,
    format_relevance_debug_block,
    get_context_token_stats,
    get_relevance_debug_info,
)
from .context_injector_queries import build_reference_toon_index
from .metrics_collector import InjectionMetrics, record_injection_metrics
from .service import MemoryScope
from .settings import get_memory_settings

CITATION_INSTRUCTION = "When applying a rule, cite it: Applied: [M:uuid8] or [G:uuid8]"

__all__ = [
    "CHARS_PER_TOKEN",
    "CITATION_INSTRUCTION",
    "GUARDRAIL_DIRECTIVE",
    "MANDATE_DIRECTIVE",
    "MEMORY_CONTEXT_END",
    "MEMORY_CONTEXT_HEADER",
    "MEMORY_CONTEXT_START",
    "ProgressiveContext",
    "build_progressive_context",
    "build_reference_toon_index",
    "format_context_with_reference_index",
    "format_progressive_context",
    "format_relevance_debug_block",
    "get_context_token_stats",
    "get_relevance_debug_info",
    "inject_progressive_context",
    "parse_memory_group_id",
]

logger = logging.getLogger(__name__)

MEMORY_CONTEXT_START = "<memory>"
MEMORY_CONTEXT_END = "</memory>"


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
    task_type: str | None = None,
    phase: str | None = None,
    include_continuity: bool = True,
) -> tuple[list[dict[str, Any]], ProgressiveContext]:
    """
    Inject mandates and guardrails context into messages.

    Main entry point for memory injection at SessionStart.
    Reference items are NOT injected here - use /api/memory/search for on-demand lookup.
    When task_type or phase is provided, triggered references are also injected.
    """
    start_time = time.monotonic()

    if not messages:
        return messages, ProgressiveContext()

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

    context = await build_progressive_context(
        query=query,
        scope=scope,
        scope_id=scope_id,
        task_type=task_type,
        phase=phase,
    )

    settings = await get_memory_settings()

    reference_episodes: list[tuple[str, str | None, str, bool]] | None = None
    if settings.reference_index_enabled:
        reference_episodes = await build_reference_toon_index(scope, scope_id)

    formatted = format_context_with_reference_index(
        context,
        reference_episodes=reference_episodes,
        include_citations=True,
    )

    if not formatted:
        return messages, context

    continuity_md = ""
    if include_continuity and scope == MemoryScope.PROJECT and scope_id:
        try:
            from .continuity_injector import build_continuity_context

            continuity_ctx = await build_continuity_context(project_id=scope_id)
            if continuity_ctx.markdown:
                continuity_md = continuity_ctx.markdown + "\n\n"
                logger.info(
                    "Continuity context: %d sessions, %d days",
                    continuity_ctx.session_count,
                    continuity_ctx.days_covered,
                )
        except Exception as e:
            logger.warning("Failed to build continuity context: %s", e)

    memory_block = f"{MEMORY_CONTEXT_START}\n{continuity_md}{formatted}\n{MEMORY_CONTEXT_END}"

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

    latency_ms = int((time.monotonic() - start_time) * 1000)

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

    if collect_metrics:
        metrics = InjectionMetrics(
            injection_latency_ms=latency_ms,
            mandates_count=len(context.mandates),
            guardrails_count=len(context.guardrails),
            reference_count=0,
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
    """Parse a memory_group_id string into explicit scope and scope_id."""
    if not memory_group_id or memory_group_id in ("global", "default"):
        return MemoryScope.GLOBAL, None
    if memory_group_id.startswith("project:"):
        return MemoryScope.PROJECT, memory_group_id.split(":", 1)[1]
    return MemoryScope.GLOBAL, None
