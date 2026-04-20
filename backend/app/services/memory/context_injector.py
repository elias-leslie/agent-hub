"""Context injection service for memory-augmented completions.

Public facade for query extraction, compatibility wrappers, and memory injection.
Heavy lifting lives in context_builder.py and context_injector_ops.py.
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
    apply_continuity_to_context as _ops_apply_continuity_to_context,
)
from .context_injector_ops import (
    build_context_and_format as _ops_build_context_and_format,
)
from .context_injector_ops import (
    handle_injection_failure as _ops_handle_injection_failure,
)
from .context_injector_ops import (
    record_injection_metrics_for_context as _ops_record_injection_metrics,
)
from .context_injector_ops import run_injection_operation as _ops_run_injection_operation
from .context_resilience import run_with_memory_retries
from .service import MemoryScope

CITATION_INSTRUCTION = "When applying a rule, cite it: Applied: [M:uuid8] or [G:uuid8]"
MEMORY_CONTEXT_START = "<memory>"
MEMORY_CONTEXT_END = "</memory>"
logger = logging.getLogger(__name__)

__all__ = [
    "CHARS_PER_TOKEN",
    "CITATION_INSTRUCTION",
    "GUARDRAIL_DIRECTIVE",
    "MANDATE_DIRECTIVE",
    "MEMORY_CONTEXT_END",
    "MEMORY_CONTEXT_HEADER",
    "MEMORY_CONTEXT_START",
    "ProgressiveContext",
    "_apply_continuity_to_context",
    "_build_context_and_format",
    "_record_injection_metrics",
    "build_progressive_context",
    "extract_query_from_messages",
    "format_progressive_context",
    "format_relevance_debug_block",
    "get_context_token_stats",
    "get_relevance_debug_info",
    "inject_progressive_context",
    "parse_memory_group_id",
]


def extract_query_from_messages(messages: list[dict[str, Any]]) -> str | None:
    """Extract query text from most recent user message."""
    for msg in reversed(messages):
        if msg.get("role") != "user":
            continue
        content = msg.get("content", "")
        if isinstance(content, list):
            text = " ".join(
                block.get("text", "")
                for block in content
                if isinstance(block, dict) and block.get("type") == "text"
            )
        elif isinstance(content, str):
            text = content
        else:
            continue
        if not text:
            return None
        task_marker = "\nTask:\n"
        idx = text.rfind(task_marker)
        if idx >= 0:
            text = text[idx + len(task_marker) :]
        elif text.startswith("Task:\n"):
            text = text[len("Task:\n") :]
        return text.strip()[:500] or None
    return None


async def _build_context_and_format(
    query: str,
    scope: MemoryScope,
    scope_id: str | None,
    task_type: str | None,
    phase: str | None,
    memory_config: dict[str, Any] | None,
    consumer_profile: str | None,
    consumer_agent_slug: str | None,
    consumer_tags: list[str] | None,
    variant: str | None,
) -> tuple[ProgressiveContext, str | None]:
    """Compatibility wrapper for refactored context-builder path."""
    return await _ops_build_context_and_format(
        query,
        scope,
        scope_id,
        task_type,
        phase,
        memory_config,
        consumer_profile,
        consumer_agent_slug,
        consumer_tags,
        variant,
    )


async def _apply_continuity_to_context(
    context: ProgressiveContext,
    formatted: str,
    scope: MemoryScope,
    scope_id: str | None,
    session_id: str | None,
    memory_config: dict[str, Any] | None,
    current_branch: str | None,
    include_continuity: bool,
) -> str:
    """Compatibility wrapper for refactored continuity path."""
    return await _ops_apply_continuity_to_context(
        context,
        formatted,
        scope,
        scope_id,
        session_id,
        memory_config,
        current_branch,
        include_continuity,
    )


def _record_injection_metrics(
    context: ProgressiveContext,
    latency_ms: int,
    query: str,
    variant: str,
    session_id: str | None,
    external_id: str | None,
    project_id: str | None,
) -> None:
    """Compatibility wrapper for injection metrics recording."""
    _ops_record_injection_metrics(
        context,
        latency_ms,
        query,
        variant,
        session_id,
        external_id,
        project_id,
    )


def _resolve_query(messages: list[dict[str, Any]], query: str | None) -> str | None:
    """Resolve query from explicit arg or message history."""
    if not messages:
        return None
    return query or extract_query_from_messages(messages)


def _build_injection_kwargs(
    messages: list[dict[str, Any]],
    scope: MemoryScope,
    scope_id: str | None,
    query: str,
    variant: str | None,
    session_id: str | None,
    external_id: str | None,
    project_id: str | None,
    collect_metrics: bool,
    task_type: str | None,
    phase: str | None,
    include_continuity: bool,
    memory_config: dict[str, Any] | None,
    current_branch: str | None,
    consumer_profile: str | None,
    consumer_agent_slug: str | None,
    consumer_tags: list[str] | None,
) -> dict[str, Any]:
    """Build kwargs for ops injection helper."""
    return {
        "messages": messages,
        "scope": scope,
        "scope_id": scope_id,
        "query": query,
        "variant": variant,
        "session_id": session_id,
        "external_id": external_id,
        "project_id": project_id,
        "collect_metrics": collect_metrics,
        "task_type": task_type,
        "phase": phase,
        "include_continuity": include_continuity,
        "memory_config": memory_config,
        "current_branch": current_branch,
        "consumer_profile": consumer_profile,
        "consumer_agent_slug": consumer_agent_slug,
        "consumer_tags": consumer_tags,
    }


async def _run_injection_with_retries(kwargs: dict[str, Any]) -> tuple[Any, Any, int, int]:
    """Run core injection operation under retry wrapper."""
    return await run_with_memory_retries(
        lambda: _ops_run_injection_operation(**kwargs),
        operation_name="inject-progressive-context",
    )


def _build_failure_kwargs(
    messages: list[dict[str, Any]],
    failure: Any,
    attempts: int,
    latency_ms: int,
    consumer_profile: str | None,
    project_id: str | None,
    scope: MemoryScope,
    scope_id: str | None,
    session_id: str | None,
    external_id: str | None,
    current_branch: str | None,
) -> dict[str, Any]:
    """Build kwargs for fail-closed injection helper."""
    return {
        "messages": messages,
        "failure": failure,
        "attempts": attempts,
        "latency_ms": latency_ms,
        "consumer_profile": consumer_profile,
        "project_id": project_id,
        "scope": scope,
        "scope_id": scope_id,
        "session_id": session_id,
        "external_id": external_id,
        "current_branch": current_branch,
    }


async def _handle_failed_injection(kwargs: dict[str, Any]) -> tuple[list[dict[str, Any]], ProgressiveContext]:
    """Delegate fail-closed injection handling."""
    return await _ops_handle_injection_failure(**kwargs)


async def inject_progressive_context(
    messages: list[dict[str, Any]],
    scope: MemoryScope = MemoryScope.GLOBAL,
    scope_id: str | None = None,
    query: str | None = None,
    variant: str | None = None,
    session_id: str | None = None,
    external_id: str | None = None,
    project_id: str | None = None,
    collect_metrics: bool = True,
    task_type: str | None = None,
    phase: str | None = None,
    include_continuity: bool = True,
    memory_config: dict[str, Any] | None = None,
    current_branch: str | None = None,
    consumer_profile: str | None = None,
    consumer_agent_slug: str | None = None,
    consumer_tags: list[str] | None = None,
) -> tuple[list[dict[str, Any]], ProgressiveContext]:
    """Inject mandates and guardrails context into messages."""
    resolved_query = _resolve_query(messages, query)
    if not resolved_query:
        return messages, ProgressiveContext()
    kwargs = _build_injection_kwargs(
        messages, scope, scope_id, resolved_query, variant, session_id,
        external_id, project_id, collect_metrics, task_type, phase,
        include_continuity, memory_config, current_branch,
        consumer_profile, consumer_agent_slug, consumer_tags,
    )
    injected, failure, attempts, latency_ms = await _run_injection_with_retries(kwargs)
    if failure:
        return await _handle_failed_injection(_build_failure_kwargs(
            messages, failure, attempts, latency_ms, consumer_profile,
            project_id, scope, scope_id, session_id, external_id, current_branch,
        ))
    assert injected is not None
    return injected


def parse_memory_group_id(memory_group_id: str | None) -> tuple[MemoryScope, str | None]:
    """Parse memory_group_id into explicit scope and scope_id."""
    if not memory_group_id or memory_group_id in ("global", "default"):
        return MemoryScope.GLOBAL, None
    if memory_group_id.startswith("project:"):
        return MemoryScope.PROJECT, memory_group_id.split(":", 1)[1]
    logger.warning("Unrecognized memory_group_id format %r — falling back to GLOBAL scope", memory_group_id)
    return MemoryScope.GLOBAL, None
