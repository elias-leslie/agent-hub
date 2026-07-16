"""Canonical context delivery for legacy in-process memory injection callers."""

from __future__ import annotations

import hashlib
import hmac
import logging
import re
import time
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.db import async_session
from app.services.llm_messages import prepend_system_context_dicts

from .context_builder import ProgressiveContext
from .context_builder_settings import (
    resolve_continuity_settings,
    resolve_excluded_memory_uuids,
    resolve_memory_config_includes,
    resolve_memory_tags,
    resolve_project_index_enabled,
    resolve_reference_index_enabled,
    resolve_tool_capabilities_enabled,
)
from .failure_reporting import MemoryFailureReport, report_memory_failure
from .metrics_collector import InjectionMetrics, record_injection_metrics
from .service import MemoryScope
from .settings import get_memory_settings
from .variants import assign_variant

logger = logging.getLogger(__name__)

_CANONICAL_ENVELOPE_RE = re.compile(
    r'<agent-hub-context payload-sha256="(?P<digest>[0-9a-f]{64})">\n'
    r"(?P<rendered>.*?)\n</agent-hub-context>",
    re.DOTALL,
)


def _canonical_context_envelope(rendered: str) -> str:
    digest = hashlib.sha256(rendered.encode("utf-8")).hexdigest()
    return (
        f'<agent-hub-context payload-sha256="{digest}">\n'
        f"{rendered}\n"
        "</agent-hub-context>"
    )


def has_verified_canonical_context(messages: list[dict[str, Any]]) -> bool:
    """Return whether messages contain a hash-verified canonical envelope."""
    for message in messages:
        if message.get("role") != "system":
            continue
        content = message.get("content")
        candidates: list[str] = []
        if isinstance(content, str):
            candidates.append(content)
        elif isinstance(content, list):
            candidates.extend(
                text
                for block in content
                if isinstance(block, dict) and block.get("type") == "text"
                if isinstance((text := block.get("text")), str)
            )
        for candidate in candidates:
            for match in _CANONICAL_ENVELOPE_RE.finditer(candidate):
                actual = hashlib.sha256(
                    match.group("rendered").encode("utf-8")
                ).hexdigest()
                if hmac.compare_digest(actual, match.group("digest")):
                    return True
    return False


def record_injection_metrics_for_context(
    context: ProgressiveContext,
    latency_ms: int,
    query: str,
    variant: str,
    session_id: str | None,
    external_id: str | None,
    project_id: str | None,
) -> None:
    """Record canonical delivery metrics through the established collector."""
    metrics_session_id = (
        session_id.removeprefix("ephemeral:")
        if session_id and session_id.startswith("ephemeral:")
        else session_id
    )
    record_injection_metrics(
        InjectionMetrics(
            injection_latency_ms=latency_ms,
            mandates_count=len(context.mandates),
            guardrails_count=len(context.guardrails),
            reference_count=len(context.reference) + len(context.reference_index),
            reference_selected_count=len(context.reference),
            reference_index_count=len(context.reference_index),
            total_tokens=context.total_tokens,
            query=query,
            variant=variant,
            session_id=metrics_session_id,
            external_id=external_id,
            project_id=project_id,
            memories_loaded=context.get_loaded_uuids(),
            reference_selected_uuids=context.get_reference_uuids(),
            reference_index_uuids=context.get_reference_index_uuids(),
        )
    )


def inject_memory_block(
    messages: list[dict[str, Any]],
    memory_block: str,
) -> list[dict[str, Any]]:
    """Prepend hash-verifiable canonical context to one lossless system message."""
    return prepend_system_context_dicts(
        messages,
        _canonical_context_envelope(memory_block),
    )


def build_failed_context(
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


async def _build_delivery(
    *,
    db: AsyncSession,
    messages: list[dict[str, Any]],
    scope: MemoryScope,
    scope_id: str | None,
    query: str,
    variant: str | None,
    session_id: str | None,
    external_id: str | None,
    project_id: str | None,
    task_type: str | None,
    phase: str | None,
    include_continuity: bool,
    memory_config: dict[str, Any] | None,
    current_branch: str | None,
    consumer_surface: str,
    consumer_profile: str | None,
    consumer_agent_slug: str | None,
    consumer_tags: list[str] | None,
    include_prompts: bool,
    include_memories: bool,
) -> tuple[Any, str]:
    from app.services.canonical_context_adapters import require_canonical_context
    from app.services.runtime_context import (
        CanonicalContextDeliveryRequest,
        build_canonical_context_delivery,
    )

    settings = await get_memory_settings(db)
    resolved_variant = assign_variant(
        external_id=external_id,
        project_id=project_id or scope_id,
        variant_override=variant,
        active_variant=settings.active_variant,
    )
    variant_value = getattr(resolved_variant, "value", str(resolved_variant))
    include_mandates, include_guardrails, include_references = (
        resolve_memory_config_includes(memory_config)
    )
    audience_tags, exclude_tags = resolve_memory_tags(memory_config)
    resolved_tags = list(consumer_tags or audience_tags)
    continuity_enabled, max_sessions, cross_project, live_sessions = (
        resolve_continuity_settings(settings, memory_config)
    )
    effective_project_id = project_id or (
        scope_id if scope == MemoryScope.PROJECT else None
    )
    delivery = await build_canonical_context_delivery(
        db,
        CanonicalContextDeliveryRequest(
            consumer_surface=consumer_surface,
            consumer_profile=consumer_profile or "agent_runtime",
            agent_slug=consumer_agent_slug,
            consumer_tags=resolved_tags,
            project_id=effective_project_id,
            session_id=session_id,
            task=query,
            query=query,
            task_type=task_type,
            phase=phase,
            current_branch=current_branch,
            include_global=True,
            include_prompts=include_prompts,
            include_memories=include_memories,
            include_mandates=include_mandates,
            include_guardrails=include_guardrails,
            include_references=include_references,
            include_reference_index=resolve_reference_index_enabled(memory_config),
            exclude_tags=exclude_tags,
            exclude_memory_uuids=resolve_excluded_memory_uuids(memory_config),
            include_project_index=resolve_project_index_enabled(memory_config),
            include_tool_capabilities=resolve_tool_capabilities_enabled(memory_config),
            include_continuity=include_continuity and continuity_enabled,
            continuity_max_sessions=max_sessions,
            continuity_cross_project=cross_project,
            continuity_live_sessions=live_sessions,
            variant=variant_value,
            client_metadata={
                "external_id": external_id or "",
                "message_count": str(len(messages)),
            },
        ),
    )
    return require_canonical_context(delivery), variant_value


async def run_injection_operation(
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
    consumer_surface: str = "agent_runtime",
    include_prompts: bool = True,
    include_memories: bool = True,
    db: AsyncSession | None = None,
) -> tuple[list[dict[str, Any]], ProgressiveContext]:
    """Inject one canonical delivery; no independent selection/render path exists."""
    start_time = time.monotonic()

    async def _run(session: AsyncSession) -> tuple[Any, str]:
        return await _build_delivery(
            db=session,
            messages=messages,
            scope=scope,
            scope_id=scope_id,
            query=query,
            variant=variant,
            session_id=session_id,
            external_id=external_id,
            project_id=project_id,
            task_type=task_type,
            phase=phase,
            include_continuity=include_continuity,
            memory_config=memory_config,
            current_branch=current_branch,
            consumer_surface=consumer_surface,
            consumer_profile=consumer_profile,
            consumer_agent_slug=consumer_agent_slug,
            consumer_tags=consumer_tags,
            include_prompts=include_prompts,
            include_memories=include_memories,
        )

    if db is not None:
        delivery, variant_value = await _run(db)
    else:
        async with async_session() as session:
            delivery, variant_value = await _run(session)

    from app.services.canonical_context_adapters import (
        progressive_context_from_delivery,
    )

    context = progressive_context_from_delivery(delivery)
    latency_ms = int((time.monotonic() - start_time) * 1000)
    context.debug_info.update(
        {"variant": variant_value, "injection_latency_ms": latency_ms}
    )
    modified = inject_memory_block(messages, delivery.rendered)
    logger.info(
        "Injected canonical context: delivery=%s hash=%s tokens=%d memories=%d surface=%s",
        delivery.delivery_id,
        delivery.payload_hash,
        delivery.estimated_tokens,
        len(context.get_loaded_uuids()),
        consumer_surface,
    )
    if collect_metrics:
        record_injection_metrics_for_context(
            context=context,
            latency_ms=latency_ms,
            query=query,
            variant=variant_value,
            session_id=session_id,
            external_id=external_id,
            project_id=project_id or scope_id,
        )
    return modified, context


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
    """Build and inject fail-closed context notice after repeated failures."""
    from .context_resilience import build_memory_failure_notice

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
            source="canonical_context_injector",
        )
    )
    logger.error(
        "Injecting fail-closed canonical context notice after %d attempts",
        attempts,
    )
    return inject_memory_block(messages, failure_notice), build_failed_context(
        failure_notice,
        operation=failure.operation,
        attempts=attempts,
        latency_ms=latency_ms,
        error_type=failure.error_type,
        error_message=failure.error_message,
    )


__all__ = [
    "build_failed_context",
    "handle_injection_failure",
    "inject_memory_block",
    "record_injection_metrics_for_context",
    "run_injection_operation",
]
