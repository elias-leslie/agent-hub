"""Context injection service for memory-augmented completions.

Orchestrates: build_progressive_context() → format → inject into messages.
Heavy lifting (retrieval, tiering, token accounting) lives in context_builder.py.
Private operation helpers live in context_injector_ops.py.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from .context_builder import ProgressiveContext, build_progressive_context
from .context_builder_settings import (
    resolve_project_index_enabled,
    resolve_tool_capabilities_enabled,
)
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
    build_failed_context as _ops_build_failed_context,
)
from .context_injector_ops import (
    inject_memory_block as _inject_memory_block,
)
from .context_injector_ops import (
    record_injection_metrics_for_context as _ops_record_injection_metrics,
)
from .context_resilience import build_memory_failure_notice, run_with_memory_retries
from .failure_reporting import MemoryFailureReport, report_memory_failure
from .project_index_context import format_project_index_context
from .service import MemoryScope
from .settings import get_memory_settings
from .tool_capability_context import format_tool_capability_context
from .variants import assign_variant

CITATION_INSTRUCTION = "When applying a rule, cite it: Applied: [M:uuid8] or [G:uuid8]"
MEMORY_CONTEXT_START = "<memory>"
MEMORY_CONTEXT_END = "</memory>"
logger = logging.getLogger(__name__)

__all__ = [
    "CHARS_PER_TOKEN", "CITATION_INSTRUCTION", "GUARDRAIL_DIRECTIVE", "MANDATE_DIRECTIVE",
    "MEMORY_CONTEXT_END", "MEMORY_CONTEXT_HEADER", "MEMORY_CONTEXT_START", "ProgressiveContext",
    "_apply_continuity_to_context", "_build_context_and_format", "_record_injection_metrics",
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
    """Compatibility wrapper for the refactored context-builder path."""
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
    """Compatibility wrapper for the refactored continuity path."""
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
        start_time = time.monotonic()
        settings = await get_memory_settings()
        resolved_variant = assign_variant(
            external_id=external_id,
            project_id=project_id or scope_id,
            variant_override=variant,
            active_variant=settings.active_variant,
        )
        context, formatted = await _build_context_and_format(
            query,
            scope,
            scope_id,
            task_type,
            phase,
            memory_config,
            consumer_profile,
            consumer_agent_slug,
            consumer_tags,
            resolved_variant.value,
        )
        project_index_block = ""
        if resolve_project_index_enabled(memory_config):
            project_index_block = format_project_index_context(
                project_id or scope_id,
                consumer_profile=consumer_profile,
                task_type=task_type,
            )
            if project_index_block:
                context.debug_info.update(
                    {
                        "project_index_included": True,
                        "project_index_chars": len(project_index_block),
                    }
                )
        tool_capability_block = ""
        if resolve_tool_capabilities_enabled(memory_config):
            tool_capability_block = format_tool_capability_context(
                consumer_profile=consumer_profile,
                task_type=task_type,
                project_id=project_id or scope_id,
            )
            if tool_capability_block:
                context.debug_info.update(
                    {
                        "tool_capabilities_included": True,
                        "tool_capabilities_chars": len(tool_capability_block),
                    }
                )
        if not formatted and not project_index_block and not tool_capability_block:
            return messages, context

        selected_uuids = context.get_reference_uuids()
        index_uuids = context.get_reference_index_uuids()
        context.debug_info.update(
            {
                "reference_selected_count": len(selected_uuids),
                "reference_selected_uuids": selected_uuids,
                "reference_index_count": len(index_uuids),
                "reference_index_uuids": index_uuids,
            }
        )

        blocks = [block for block in (project_index_block, tool_capability_block) if block]
        if formatted:
            blocks.append(
                await _apply_continuity_to_context(
                    context,
                    formatted,
                    scope,
                    scope_id,
                    session_id,
                    memory_config,
                    current_branch,
                    include_continuity,
                )
            )

        modified = _inject_memory_block(messages, "\n".join(blocks))
        latency_ms = int((time.monotonic() - start_time) * 1000)
        context.debug_info.update(
            {
                "variant": resolved_variant.value,
                "injection_latency_ms": latency_ms,
            }
        )
        if collect_metrics:
            _record_injection_metrics(
                context=context,
                latency_ms=latency_ms,
                query=query,
                variant=resolved_variant.value,
                session_id=session_id,
                external_id=external_id,
                project_id=project_id,
            )
        return modified, context

    injected, failure, attempts, latency_ms = await run_with_memory_retries(
        _op, operation_name="inject-progressive-context",
    )
    if failure:
        effective_project_id = project_id or scope_id
        failure_notice = build_memory_failure_notice(
            failure,
            consumer_profile=consumer_profile,
            project_id=effective_project_id,
        )
        await report_memory_failure(
            MemoryFailureReport(
                failure=failure,
                consumer_profile=consumer_profile,
                project_id=effective_project_id,
                session_id=session_id,
                external_id=external_id,
                current_branch=current_branch,
                source="context_injector",
            )
        )
        return _inject_memory_block(messages, failure_notice), _ops_build_failed_context(
            failure_notice,
            operation=failure.operation,
            attempts=attempts,
            latency_ms=latency_ms,
            error_type=failure.error_type,
            error_message=failure.error_message,
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
