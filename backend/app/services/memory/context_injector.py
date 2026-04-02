"""Context injection service for memory-augmented completions.

Orchestrates: build_progressive_context() → format → inject into messages.
Heavy lifting (retrieval, tiering, token accounting) lives in context_builder.py.
Private operation helpers live in context_injector_ops.py.
"""

from __future__ import annotations

import logging
from typing import Any

from .context_builder import ProgressiveContext, build_progressive_context
from .context_injector_formatter import (
    CHARS_PER_TOKEN,
    GUARDRAIL_DIRECTIVE,
    MANDATE_DIRECTIVE,
    MEMORY_CONTEXT_HEADER,
    format_progressive_context,
    format_relevance_debug_block,
    get_context_token_stats,
    get_relevance_debug_info,
)
from .context_injector_ops import (
    handle_injection_failure,
    run_injection_operation,
)
from .context_resilience import run_with_memory_retries
from .service import MemoryScope

CITATION_INSTRUCTION = "When applying a rule, cite it: Applied: [M:uuid8] or [G:uuid8]"
MEMORY_CONTEXT_START = "<memory>"
MEMORY_CONTEXT_END = "</memory>"
logger = logging.getLogger(__name__)

__all__ = [
    "CHARS_PER_TOKEN", "CITATION_INSTRUCTION", "GUARDRAIL_DIRECTIVE", "MANDATE_DIRECTIVE",
    "MEMORY_CONTEXT_END", "MEMORY_CONTEXT_HEADER", "MEMORY_CONTEXT_START", "ProgressiveContext",
    "build_progressive_context", "extract_query_from_messages", "format_progressive_context",
    "format_relevance_debug_block", "get_context_token_stats", "get_relevance_debug_info",
    "inject_progressive_context", "parse_memory_group_id",
]


def extract_query_from_messages(messages: list[dict[str, Any]]) -> str | None:
    """Extract query text from the most recent user message."""
    for msg in reversed(messages):
        if msg.get("role") != "user":
            continue
        content = msg.get("content", "")
        if isinstance(content, list):
            text = " ".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")
        elif isinstance(content, str):
            text = content
        else:
            continue
        if not text:
            return None
        task_marker = "\nTask:\n"
        idx = text.rfind(task_marker)
        if idx >= 0:
            text = text[idx + len(task_marker):]
        elif text.startswith("Task:\n"):
            text = text[len("Task:\n"):]
        return (text.strip())[:500] or None
    return None


async def inject_progressive_context(
    messages: list[dict[str, Any]],
    scope: MemoryScope = MemoryScope.GLOBAL, scope_id: str | None = None,
    query: str | None = None, variant: str | None = None,
    session_id: str | None = None, external_id: str | None = None,
    project_id: str | None = None, collect_metrics: bool = True,
    task_type: str | None = None, phase: str | None = None,
    include_continuity: bool = True, memory_config: dict[str, Any] | None = None,
    current_branch: str | None = None, consumer_profile: str | None = None,
    consumer_agent_slug: str | None = None, consumer_tags: list[str] | None = None,
) -> tuple[list[dict[str, Any]], ProgressiveContext]:
    """Inject mandates and guardrails context into messages. Main entry point for memory injection."""
    if not messages or not (query or (query := extract_query_from_messages(messages))):
        return messages, ProgressiveContext()

    async def _op() -> tuple[list[dict[str, Any]], ProgressiveContext]:
        return await run_injection_operation(
            messages, scope, scope_id, query, variant, session_id, external_id,
            project_id, collect_metrics, task_type, phase, include_continuity,
            memory_config, current_branch, consumer_profile, consumer_agent_slug, consumer_tags,
        )

    injected, failure, attempts, latency_ms = await run_with_memory_retries(
        _op, operation_name="inject-progressive-context",
    )
    if failure:
        return await handle_injection_failure(
            messages, failure, attempts, latency_ms,
            consumer_profile=consumer_profile, project_id=project_id,
            scope=scope, scope_id=scope_id, session_id=session_id,
            external_id=external_id, current_branch=current_branch,
        )
    assert injected is not None
    return injected


def parse_memory_group_id(memory_group_id: str | None) -> tuple[MemoryScope, str | None]:
    """Parse a memory_group_id string into explicit scope and scope_id."""
    if not memory_group_id or memory_group_id in ("global", "default"):
        return MemoryScope.GLOBAL, None
    if memory_group_id.startswith("project:"):
        return MemoryScope.PROJECT, memory_group_id.split(":", 1)[1]
    logger.warning("Unrecognized memory_group_id format %r — falling back to GLOBAL scope", memory_group_id)
    return MemoryScope.GLOBAL, None
