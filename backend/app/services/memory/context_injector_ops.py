"""Internal helpers for context injection operations.

Private implementation details: continuity context, metrics recording,
block assembly, and the core injection operation loop.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from app.services.project_permission_service import get_visible_tools_for_project

from .context_builder import ProgressiveContext, build_progressive_context
from .context_builder_settings import (
    resolve_continuity_settings,
    resolve_memory_config_includes,
    resolve_project_index_enabled,
    resolve_tool_capabilities_enabled,
)
from .context_injector_formatter import (
    CHARS_PER_TOKEN,
    format_progressive_context,
)
from .failure_reporting import MemoryFailureReport, report_memory_failure
from .metrics_collector import InjectionMetrics, record_injection_metrics
from .project_index_context import format_project_index_context
from .service import MemoryScope
from .settings import get_memory_settings
from .st_usage_memory import get_recent_st_usage_memory
from .tool_capability_context import format_tool_capability_context
from .variants import assign_variant

MEMORY_CONTEXT_START = "<memory>"
MEMORY_CONTEXT_END = "</memory>"

logger = logging.getLogger(__name__)


async def get_continuity_markdown(
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


async def build_context_and_format(
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


def record_injection_metrics_for_context(
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


async def apply_continuity_to_context(
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
        await get_continuity_markdown(
            scope, scope_id, current_branch=current_branch,
            memory_config=memory_config, session_id=session_id,
        )
        if include_continuity else ""
    )
    if continuity_md and context.budget_usage:
        context.budget_usage.continuity_tokens = len(continuity_md) // CHARS_PER_TOKEN
    return f"{MEMORY_CONTEXT_START}\n{continuity_md}{formatted}\n{MEMORY_CONTEXT_END}"


def inject_memory_block(messages: list[dict[str, Any]], memory_block: str) -> list[dict[str, Any]]:
    """Inject memory block into system message or prepend new system message."""
    modified = list(messages)
    if modified and modified[0].get("role") == "system":
        modified[0] = {"role": "system", "content": f"{modified[0].get('content', '')}\n\n{memory_block}"}
    else:
        modified.insert(0, {"role": "system", "content": memory_block})
    return modified


def build_failed_context(
    failure_notice: str, *, operation: str, attempts: int,
    latency_ms: int, error_type: str, error_message: str,
) -> ProgressiveContext:
    """Create a synthetic context object for fail-closed delivery."""
    context = ProgressiveContext()
    context.debug_info.update({
        "memory_system_failed": True, "failure_mode": "stop",
        "failure_notice": failure_notice, "failure_operation": operation,
        "failure_attempts": attempts, "failure_latency_ms": latency_ms,
        "failure_error_type": error_type, "failure_error_message": error_message,
    })
    return context


def log_injection(
    context: ProgressiveContext, resolved_variant: Any, latency_ms: int,
    scope: MemoryScope, scope_id: str | None,
) -> None:
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


async def finalize_injection(
    messages: list[dict[str, Any]], context: ProgressiveContext, formatted: str | None,
    project_index_block: str, tool_capability_block: str, resolved_variant: Any,
    scope: MemoryScope, scope_id: str | None, session_id: str | None,
    memory_config: dict[str, Any] | None, current_branch: str | None,
    include_continuity: bool, start_time: float, query: str,
    external_id: str | None, project_id: str | None, collect_metrics: bool,
) -> tuple[list[dict[str, Any]], ProgressiveContext]:
    """Assemble blocks, inject into messages, log, and record metrics."""
    if not formatted and not project_index_block and not tool_capability_block:
        return messages, context
    selected_uuids = context.get_reference_uuids()
    index_uuids = context.get_reference_index_uuids()
    context.debug_info.update({
        "reference_selected_count": len(selected_uuids), "reference_selected_uuids": selected_uuids,
        "reference_index_count": len(index_uuids), "reference_index_uuids": index_uuids,
    })
    blocks: list[str] = [b for b in [project_index_block, tool_capability_block] if b]
    if formatted:
        blocks.append(await apply_continuity_to_context(
            context, formatted, scope, scope_id, session_id, memory_config,
            current_branch, include_continuity,
        ))
    modified = inject_memory_block(messages, "\n".join(blocks))
    latency_ms = int((time.monotonic() - start_time) * 1000)
    context.debug_info.update({"variant": resolved_variant.value, "injection_latency_ms": latency_ms})
    log_injection(context, resolved_variant, latency_ms, scope, scope_id)
    if collect_metrics:
        record_injection_metrics_for_context(
            context=context, latency_ms=latency_ms, query=query,
            variant=resolved_variant.value, session_id=session_id,
            external_id=external_id, project_id=project_id,
        )
    return modified, context


async def run_injection_operation(
    messages: list[dict[str, Any]], scope: MemoryScope, scope_id: str | None,
    query: str, variant: str | None, session_id: str | None, external_id: str | None,
    project_id: str | None, collect_metrics: bool, task_type: str | None,
    phase: str | None, include_continuity: bool, memory_config: dict[str, Any] | None,
    current_branch: str | None, consumer_profile: str | None,
    consumer_agent_slug: str | None, consumer_tags: list[str] | None,
) -> tuple[list[dict[str, Any]], ProgressiveContext]:
    """Execute the core injection operation (caller retries on failure)."""
    start_time = time.monotonic()
    settings = await get_memory_settings()
    resolved_variant = assign_variant(
        external_id=external_id, project_id=project_id or scope_id,
        variant_override=variant, active_variant=settings.active_variant,
    )
    context, formatted = await build_context_and_format(
        query=query, scope=scope, scope_id=scope_id, task_type=task_type, phase=phase,
        memory_config=memory_config, consumer_profile=consumer_profile,
        consumer_agent_slug=consumer_agent_slug, consumer_tags=consumer_tags,
        variant=resolved_variant.value,
    )
    project_index_block = ""
    if resolve_project_index_enabled(memory_config):
        project_index_block = format_project_index_context(
            project_id or scope_id, consumer_profile=consumer_profile, task_type=task_type,
        )
        if project_index_block:
            context.debug_info.update({"project_index_included": True, "project_index_chars": len(project_index_block)})
    tool_capability_block = ""
    if resolve_tool_capabilities_enabled(memory_config):
        effective_project_id = project_id or scope_id
        visible_tool_names = (
            await get_visible_tools_for_project(effective_project_id)
            if effective_project_id
            else frozenset()
        )
        bash_available = ("bash" in visible_tool_names) if effective_project_id else None
        st_usage_memory = (
            await get_recent_st_usage_memory(project_id=effective_project_id, task_type=task_type)
            if bash_available is not False
            else None
        )
        tool_capability_block = format_tool_capability_context(
            consumer_profile=consumer_profile,
            task_type=task_type,
            project_id=effective_project_id,
            bash_available=bash_available,
            st_quick=st_usage_memory.quick if st_usage_memory else None,
        )
        if tool_capability_block:
            context.debug_info.update({
                "tool_capabilities_included": True,
                "tool_capabilities_chars": len(tool_capability_block),
                "st_usage_observed": st_usage_memory.observed if st_usage_memory else 0,
                "st_quick_entries": len(st_usage_memory.quick) if st_usage_memory else 0,
            })
    return await finalize_injection(
        messages, context, formatted, project_index_block, tool_capability_block,
        resolved_variant, scope, scope_id, session_id, memory_config, current_branch,
        include_continuity, start_time, query, external_id, project_id, collect_metrics,
    )


async def handle_injection_failure(
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
) -> tuple[list[dict[str, Any]], ProgressiveContext]:
    """Build and inject fail-closed memory notice after repeated failures."""
    from .context_resilience import build_memory_failure_notice
    eff_pid = project_id or scope_id
    failure_notice = build_memory_failure_notice(
        failure, consumer_profile=consumer_profile, project_id=eff_pid,
    )
    await report_memory_failure(MemoryFailureReport(
        failure=failure, consumer_profile=consumer_profile, project_id=eff_pid,
        session_id=session_id, external_id=external_id,
        current_branch=current_branch, source="context_injector",
    ))
    logger.error(
        "Injecting fail-closed memory notice after repeated failures: scope=%s scope_id=%s attempts=%d",
        scope, scope_id, attempts,
    )
    return inject_memory_block(messages, failure_notice), build_failed_context(
        failure_notice, operation=failure.operation, attempts=attempts,
        latency_ms=latency_ms, error_type=failure.error_type,
        error_message=failure.error_message,
    )
