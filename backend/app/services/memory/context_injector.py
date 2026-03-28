"""Context injection service for memory-augmented completions.

Orchestrates: build_progressive_context() → format → inject into messages.
Heavy lifting (retrieval, tiering, token accounting) lives in context_builder.py.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from .context_builder import ProgressiveContext, build_progressive_context
from .context_builder_settings import (
    resolve_continuity_settings,
    resolve_memory_config_includes,
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
from .context_resilience import (
    build_memory_failure_notice,
    run_with_memory_retries,
)
from .failure_reporting import MemoryFailureReport, report_memory_failure
from .metrics_collector import InjectionMetrics, record_injection_metrics
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
    "build_progressive_context", "extract_query_from_messages", "format_progressive_context",
    "format_relevance_debug_block", "get_context_token_stats", "get_relevance_debug_info",
    "inject_progressive_context", "parse_memory_group_id",
]


def _extract_query_text(content: Any) -> str | None:
    """Extract the most task-relevant query text from one message payload."""
    text = ""
    if isinstance(content, str):
        text = content
    elif isinstance(content, list):
        parts = [b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"]
        text = " ".join(parts)
    if not text:
        return None
    task_marker = "\nTask:\n"
    task_index = text.rfind(task_marker)
    if task_index >= 0:
        text = text[task_index + len(task_marker):]
    elif text.startswith("Task:\n"):
        text = text[len("Task:\n"):]
    text = text.strip()
    return text[:500] if text else None


def extract_query_from_messages(messages: list[dict[str, Any]]) -> str | None:
    """Extract query text from the most recent user message."""
    for msg in reversed(messages):
        if msg.get("role") != "user":
            continue
        return _extract_query_text(msg.get("content", ""))
    return None


async def _get_continuity_markdown(
    scope: MemoryScope,
    scope_id: str | None,
    current_branch: str | None = None,
    memory_config: dict[str, Any] | None = None,
    session_id: str | None = None,
) -> str:
    """Build continuity context markdown if applicable."""
    if scope != MemoryScope.PROJECT or not scope_id:
        logger.debug("Continuity skipped: scope=%s scope_id=%s (requires PROJECT scope)", scope, scope_id)
        return ""
    try:
        settings = await get_memory_settings()
        continuity_enabled, max_sessions, include_cross_project, include_live_sessions = (
            resolve_continuity_settings(settings, memory_config)
        )
        if not continuity_enabled:
            logger.debug("Continuity skipped: continuity_enabled=False for project=%s", scope_id)
            return ""
        from .continuity_injector import build_continuity_context
        ctx = await build_continuity_context(
            project_id=scope_id, current_branch=current_branch, max_sessions=max_sessions,
            include_cross_project=include_cross_project, include_live_sessions=include_live_sessions,
            exclude_session_id=session_id,
        )
        if ctx.markdown:
            logger.info(
                "Continuity context: project=%s sessions=%d days=%d live=%s cross_project=%s chars=%d",
                scope_id, ctx.session_count, ctx.days_covered,
                include_live_sessions, include_cross_project, len(ctx.markdown),
            )
            return ctx.markdown + "\n\n"
        logger.debug("Continuity context empty for project=%s", scope_id)
    except Exception as e:
        logger.warning("Failed to build continuity context for project=%s: %s", scope_id, e)
    return ""


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
    """Build progressive context and format it."""
    mc_mandates, mc_guardrails, mc_references = resolve_memory_config_includes(memory_config)
    context = await build_progressive_context(
        query=query, scope=scope, scope_id=scope_id, task_type=task_type, phase=phase,
        include_mandates=mc_mandates, include_guardrails=mc_guardrails, include_references=mc_references,
        memory_config=memory_config, consumer_profile=consumer_profile,
        consumer_agent_slug=consumer_agent_slug, consumer_tags=consumer_tags, variant=variant,
    )
    formatted = format_progressive_context(context, include_citations=True, consumer_profile=consumer_profile)
    return context, formatted


def _record_injection_metrics(
    context: ProgressiveContext,
    latency_ms: int,
    query: str,
    variant: str,
    session_id: str | None,
    external_id: str | None,
    project_id: str | None,
) -> None:
    """Record injection metrics for observability."""
    record_injection_metrics(InjectionMetrics(
        injection_latency_ms=latency_ms, mandates_count=len(context.mandates),
        guardrails_count=len(context.guardrails),
        reference_count=len(context.reference) + len(context.reference_index),
        reference_selected_count=int(context.debug_info.get("reference_selected_count", len(context.reference))),
        reference_index_count=int(context.debug_info.get("reference_index_count", len(context.reference_index))),
        total_tokens=context.total_tokens, query=query, variant=variant,
        session_id=session_id, external_id=external_id, project_id=project_id,
        memories_loaded=context.get_loaded_uuids(),
        reference_selected_uuids=list(context.debug_info.get("reference_selected_uuids", [])),
        reference_index_uuids=list(context.debug_info.get("reference_index_uuids", [])),
    ))


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
    """Build final memory block string, applying continuity context if enabled."""
    continuity_md = (
        await _get_continuity_markdown(scope, scope_id, current_branch=current_branch,
                                       memory_config=memory_config, session_id=session_id)
        if include_continuity else ""
    )
    if continuity_md and context.budget_usage:
        context.budget_usage.continuity_tokens = len(continuity_md) // CHARS_PER_TOKEN
    return f"{MEMORY_CONTEXT_START}\n{continuity_md}{formatted}\n{MEMORY_CONTEXT_END}"


def _build_optional_blocks(
    context: ProgressiveContext,
    memory_config: dict[str, Any] | None,
    effective_project_id: str | None,
    consumer_profile: str | None,
    task_type: str | None,
) -> tuple[str, str]:
    """Build project index and tool capability blocks, annotating debug_info for each."""
    project_index_block = ""
    if resolve_project_index_enabled(memory_config):
        project_index_block = format_project_index_context(
            effective_project_id, consumer_profile=consumer_profile, task_type=task_type,
        )
        if project_index_block:
            context.debug_info["project_index_included"] = True
            context.debug_info["project_index_chars"] = len(project_index_block)
    tool_capability_block = ""
    if resolve_tool_capabilities_enabled(memory_config):
        tool_capability_block = format_tool_capability_context(
            consumer_profile=consumer_profile, task_type=task_type, project_id=effective_project_id,
        )
        if tool_capability_block:
            context.debug_info["tool_capabilities_included"] = True
            context.debug_info["tool_capabilities_chars"] = len(tool_capability_block)
    return project_index_block, tool_capability_block


def _inject_memory_block(messages: list[dict[str, Any]], memory_block: str) -> list[dict[str, Any]]:
    """Inject memory block into system message or prepend new system message."""
    modified = list(messages)
    if modified and modified[0].get("role") == "system":
        modified[0] = {"role": "system", "content": f"{modified[0].get('content', '')}\n\n{memory_block}"}
    else:
        modified.insert(0, {"role": "system", "content": memory_block})
    return modified


def _annotate_reference_observability(context: ProgressiveContext) -> None:
    """Attach selected-reference observability to context.debug_info."""
    selected_uuids = context.get_reference_uuids()
    index_uuids = context.get_reference_index_uuids()
    context.debug_info.update({
        "reference_selected_count": len(selected_uuids),
        "reference_selected_uuids": selected_uuids,
        "reference_index_count": len(index_uuids),
        "reference_index_uuids": index_uuids,
    })


def _log_injection(context: ProgressiveContext, resolved_variant: Any, latency_ms: int, scope: MemoryScope, scope_id: str | None) -> None:
    """Log injection summary."""
    continuity_tokens = context.budget_usage.continuity_tokens if context.budget_usage else 0
    logger.info(
        "Injected progressive context: variant=%s latency=%dms tokens=%d mandates=%d guardrails=%d "
        "refs_selected=%d refs_index=%d continuity_tokens=%d scope=%s",
        resolved_variant.value, latency_ms, context.total_tokens, len(context.mandates),
        len(context.guardrails),
        context.debug_info.get("reference_selected_count", len(context.reference)),
        context.debug_info.get("reference_index_count", len(context.reference_index)),
        continuity_tokens, f"{scope}:{scope_id}" if scope_id else str(scope),
    )


def _build_failed_context(
    failure_notice: str,
    *,
    operation: str,
    attempts: int,
    latency_ms: int,
    error_type: str,
    error_message: str,
) -> ProgressiveContext:
    """Create a synthetic context object for fail-closed delivery."""
    context = ProgressiveContext()
    context.debug_info.update(
        {
            "memory_system_failed": True,
            "failure_mode": "stop",
            "failure_notice": failure_notice,
            "failure_operation": operation,
            "failure_attempts": attempts,
            "failure_latency_ms": latency_ms,
            "failure_error_type": error_type,
            "failure_error_message": error_message,
        }
    )
    return context


async def _finalize_injection(
    messages: list[dict[str, Any]],
    context: ProgressiveContext,
    formatted: str | None,
    project_index_block: str,
    tool_capability_block: str,
    resolved_variant: Any,
    scope: MemoryScope,
    scope_id: str | None,
    session_id: str | None,
    memory_config: dict[str, Any] | None,
    current_branch: str | None,
    include_continuity: bool,
    start_time: float,
    query: str,
    external_id: str | None,
    project_id: str | None,
    collect_metrics: bool,
) -> tuple[list[dict[str, Any]], ProgressiveContext]:
    """Guard, assemble blocks, inject into messages, log, and record metrics."""
    if not formatted and not project_index_block and not tool_capability_block:
        return messages, context
    _annotate_reference_observability(context)
    blocks: list[str] = [b for b in [project_index_block, tool_capability_block] if b]
    if formatted:
        blocks.append(await _apply_continuity_to_context(
            context, formatted, scope, scope_id, session_id, memory_config, current_branch, include_continuity,
        ))
    modified = _inject_memory_block(messages, "\n".join(blocks))
    latency_ms = int((time.monotonic() - start_time) * 1000)
    context.debug_info.update({"variant": resolved_variant.value, "injection_latency_ms": latency_ms})
    _log_injection(context, resolved_variant, latency_ms, scope, scope_id)
    if collect_metrics:
        _record_injection_metrics(
            context=context, latency_ms=latency_ms, query=query, variant=resolved_variant.value,
            session_id=session_id, external_id=external_id, project_id=project_id,
        )
    return modified, context


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
    """Inject mandates and guardrails context into messages. Main entry point for memory injection."""
    if not messages or not (query or (query := extract_query_from_messages(messages))):
        return messages, ProgressiveContext()

    async def _operation() -> tuple[list[dict[str, Any]], ProgressiveContext]:
        start_time = time.monotonic()
        settings = await get_memory_settings()
        resolved_variant = assign_variant(
            external_id=external_id, project_id=project_id or scope_id,
            variant_override=variant, active_variant=settings.active_variant,
        )
        context, formatted = await _build_context_and_format(
            query=query, scope=scope, scope_id=scope_id, task_type=task_type, phase=phase,
            memory_config=memory_config, consumer_profile=consumer_profile,
            consumer_agent_slug=consumer_agent_slug, consumer_tags=consumer_tags,
            variant=resolved_variant.value,
        )
        project_index_block, tool_capability_block = _build_optional_blocks(
            context, memory_config, project_id or scope_id, consumer_profile, task_type,
        )
        return await _finalize_injection(
            messages, context, formatted, project_index_block, tool_capability_block,
            resolved_variant, scope, scope_id, session_id, memory_config, current_branch,
            include_continuity, start_time, query, external_id, project_id, collect_metrics,
        )

    injected, failure, attempts, latency_ms = await run_with_memory_retries(
        _operation,
        operation_name="inject-progressive-context",
    )
    if failure:
        failure_notice = build_memory_failure_notice(
            failure,
            consumer_profile=consumer_profile,
            project_id=project_id or scope_id,
        )
        await report_memory_failure(
            MemoryFailureReport(
                failure=failure,
                consumer_profile=consumer_profile,
                project_id=project_id or scope_id,
                session_id=session_id,
                external_id=external_id,
                current_branch=current_branch,
                source="context_injector",
            )
        )
        logger.error(
            "Injecting fail-closed memory notice after repeated failures: scope=%s scope_id=%s attempts=%d",
            scope,
            scope_id,
            attempts,
        )
        return _inject_memory_block(messages, failure_notice), _build_failed_context(
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
