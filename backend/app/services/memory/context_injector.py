"""Context injection service for memory-augmented completions.

Orchestrates: build_progressive_context() → format → inject into messages.
Heavy lifting (retrieval, budget) lives in context_builder.py.
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
MEMORY_CONTEXT_START = "<memory>"
MEMORY_CONTEXT_END = "</memory>"
logger = logging.getLogger(__name__)

__all__ = [
    "CHARS_PER_TOKEN", "CITATION_INSTRUCTION", "GUARDRAIL_DIRECTIVE", "MANDATE_DIRECTIVE",
    "MEMORY_CONTEXT_END", "MEMORY_CONTEXT_HEADER", "MEMORY_CONTEXT_START", "ProgressiveContext",
    "build_progressive_context", "build_reference_toon_index", "format_context_with_reference_index",
    "format_progressive_context", "format_relevance_debug_block", "get_context_token_stats",
    "get_relevance_debug_info", "inject_progressive_context", "parse_memory_group_id",
]


def _extract_query_from_messages(messages: list[dict[str, Any]]) -> str | None:
    """Extract query text from most recent user message."""
    for msg in reversed(messages):
        if msg.get("role") != "user":
            continue
        content = msg.get("content", "")
        if isinstance(content, str):
            return content[:500]
        if isinstance(content, list):
            parts = [b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"]
            return " ".join(parts)[:500]
    return None


async def _get_continuity_markdown(
    scope: MemoryScope,
    scope_id: str | None,
    current_branch: str | None = None,
    memory_config: dict[str, Any] | None = None,
    session_id: str | None = None,
) -> str:
    """Build continuity context markdown if applicable.

    Uses settings from MemorySettings (global) or memory_config (per-agent)
    to control continuity injection. Includes cross-project and live session
    awareness unless disabled.
    """
    if scope != MemoryScope.PROJECT or not scope_id:
        return ""
    try:
        settings = await get_memory_settings()

        # Check if continuity is enabled (per-agent config overrides global)
        continuity_enabled = (
            memory_config.get("continuity_enabled", settings.continuity_enabled)
            if memory_config
            else settings.continuity_enabled
        )
        if not continuity_enabled:
            return ""

        max_sessions = (
            memory_config.get("continuity_max_sessions", settings.continuity_max_sessions)
            if memory_config
            else settings.continuity_max_sessions
        )

        # Cross-project and live session toggles (per-agent config overrides)
        include_cross_project = (
            memory_config.get("cross_project_enabled", True)
            if memory_config
            else True
        )
        include_live_sessions = (
            memory_config.get("live_sessions_enabled", True)
            if memory_config
            else True
        )

        from .continuity_injector import build_continuity_context

        ctx = await build_continuity_context(
            project_id=scope_id,
            current_branch=current_branch,
            max_sessions=max_sessions,
            include_cross_project=include_cross_project,
            include_live_sessions=include_live_sessions,
            exclude_session_id=session_id,
        )
        if ctx.markdown:
            logger.info("Continuity context: %d sessions, %d days", ctx.session_count, ctx.days_covered)
            return ctx.markdown + "\n\n"
    except Exception as e:
        logger.warning("Failed to build continuity context: %s", e)
    return ""


def _inject_memory_block(messages: list[dict[str, Any]], memory_block: str) -> list[dict[str, Any]]:
    """Inject memory block into system message or prepend new system message."""
    modified = list(messages)
    if modified and modified[0].get("role") == "system":
        modified[0] = {"role": "system", "content": f"{modified[0].get('content', '')}\n\n{memory_block}"}
    else:
        modified.insert(0, {"role": "system", "content": memory_block})
    return modified


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
    memory_config: dict[str, Any] | None = None,
    current_branch: str | None = None,
) -> tuple[list[dict[str, Any]], ProgressiveContext]:
    """Inject mandates and guardrails context into messages. Main entry point for memory injection."""
    start_time = time.monotonic()
    if not messages or not (query or (query := _extract_query_from_messages(messages))):
        return messages, ProgressiveContext()

    # Build progressive context with memory config
    mc_mandates = memory_config.get("include_mandates", True) if memory_config else True
    mc_guardrails = memory_config.get("include_guardrails", True) if memory_config else True
    context = await build_progressive_context(
        query=query, scope=scope, scope_id=scope_id, task_type=task_type, phase=phase,
        include_mandates=mc_mandates, include_guardrails=mc_guardrails, memory_config=memory_config,
    )

    # Build reference index if enabled
    settings = await get_memory_settings()
    ref_enabled = (
        memory_config.get("reference_index_enabled", memory_config.get("reference_index", settings.reference_index_enabled))
        if memory_config else settings.reference_index_enabled
    )
    ref_episodes = await build_reference_toon_index(scope, scope_id) if ref_enabled else None

    formatted = format_context_with_reference_index(context, reference_episodes=ref_episodes, include_citations=True)
    if not formatted:
        return messages, context

    # Build and inject memory block
    continuity_md = (
        await _get_continuity_markdown(
            scope, scope_id, current_branch=current_branch,
            memory_config=memory_config, session_id=session_id,
        )
        if include_continuity
        else ""
    )

    # Track continuity tokens in budget usage
    if continuity_md and context.budget_usage:
        context.budget_usage.continuity_tokens = len(continuity_md) // CHARS_PER_TOKEN

    memory_block = f"{MEMORY_CONTEXT_START}\n{continuity_md}{formatted}\n{MEMORY_CONTEXT_END}"
    modified_messages = _inject_memory_block(messages, memory_block)

    # Record metrics
    latency_ms = int((time.monotonic() - start_time) * 1000)
    context.debug_info.update({"variant": variant, "injection_latency_ms": latency_ms})
    logger.info("Injected progressive context: variant=%s latency=%dms tokens=%d mandates=%d guardrails=%d",
                variant, latency_ms, context.total_tokens, len(context.mandates), len(context.guardrails))

    if collect_metrics:
        record_injection_metrics(InjectionMetrics(
            injection_latency_ms=latency_ms, mandates_count=len(context.mandates),
            guardrails_count=len(context.guardrails), reference_count=len(context.reference),
            total_tokens=context.total_tokens, query=query, variant=variant,
            session_id=session_id, external_id=external_id, project_id=project_id,
            memories_loaded=context.get_loaded_uuids(),
        ))

    return modified_messages, context


def parse_memory_group_id(memory_group_id: str | None) -> tuple[MemoryScope, str | None]:
    """Parse a memory_group_id string into explicit scope and scope_id."""
    if not memory_group_id or memory_group_id in ("global", "default"):
        return MemoryScope.GLOBAL, None
    if memory_group_id.startswith("project:"):
        return MemoryScope.PROJECT, memory_group_id.split(":", 1)[1]
    return MemoryScope.GLOBAL, None
