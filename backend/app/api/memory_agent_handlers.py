"""Handler functions for complex memory agent endpoints."""

import time

from app.services.memory.context_builder_tiers import get_rendered_content
from app.services.memory.context_resilience import (
    MemoryFailureDetails,
    build_memory_failure_notice,
    run_with_memory_retries,
)
from app.services.memory.project_index_context import format_project_index_context
from app.services.memory.service import MemoryScope
from app.services.memory.tool_capability_context import format_tool_capability_context
from app.services.project_permission_service import get_visible_tools_for_project

from .memory_agent_context_builder import (
    build_progressive_context_with_variant,
    format_context_with_continuity,
    track_and_record_metrics,
)
from .memory_agent_helpers import build_budget_usage, build_scoring_breakdown
from .memory_agent_learning_saver import save_learning_with_validation
from .memory_agent_schemas import (
    ProgressiveContextBlock,
    ProgressiveContextFailure,
    ProgressiveContextResponse,
    SaveLearningRequest,
    SaveLearningResponse,
)


def _assemble_context_response(
    context,
    formatted,
    variant,
    debug,
    *,
    attempts: int,
    latency_ms: int,
) -> ProgressiveContextResponse:
    """Assemble the ProgressiveContextResponse from a built context object."""
    from app.services.memory.context_injector import get_relevance_debug_info

    return ProgressiveContextResponse(
        mandates=ProgressiveContextBlock(
            items=[get_rendered_content(m) for m in context.mandates],
            count=len(context.mandates),
        ),
        guardrails=ProgressiveContextBlock(
            items=[get_rendered_content(g) for g in context.guardrails],
            count=len(context.guardrails),
        ),
        reference=ProgressiveContextBlock(
            items=[get_rendered_content(r) for r in context.reference],
            count=len(context.reference),
        ),
        total_tokens=context.total_tokens,
        formatted=formatted,
        variant=variant,
        debug=get_relevance_debug_info(context) if debug else None,
        scoring_breakdown=build_scoring_breakdown(context) if debug else None,
        budget_usage=build_budget_usage(context),
        attempts=attempts,
        latency_ms=latency_ms,
    )


def _build_failure_response(
    failure: MemoryFailureDetails,
    *,
    consumer_profile: str | None,
    project_id: str | None,
) -> ProgressiveContextResponse:
    """Return a fail-closed response instructing the caller to stop and notify the operator."""
    return ProgressiveContextResponse(
        mandates=ProgressiveContextBlock(items=[], count=0),
        guardrails=ProgressiveContextBlock(items=[], count=0),
        reference=ProgressiveContextBlock(items=[], count=0),
        total_tokens=0,
        formatted=build_memory_failure_notice(
            failure,
            consumer_profile=consumer_profile,
            project_id=project_id,
        ),
        variant="FAILED",
        budget_usage=None,
        status="failed",
        failure=ProgressiveContextFailure(
            operation=failure.operation,
            attempts=failure.attempts,
            error_type=failure.error_type,
            error_message=failure.error_message,
            latency_ms=failure.latency_ms,
        ),
        attempts=failure.attempts,
        latency_ms=failure.latency_ms,
    )


async def _build_progressive_context_response_once(
    query: str,
    scope: MemoryScope,
    scope_id: str | None,
    debug: bool,
    include_global: bool,
    task_type: str | None,
    phase: str | None = None,
    variant_override: str | None = None,
    external_id: str | None = None,
    project_id: str | None = None,
    session_id: str | None = None,
    current_branch: str | None = None,
    consumer_profile: str | None = None,
) -> ProgressiveContextResponse:
    """Build one progressive-context response attempt."""
    start_time = time.monotonic()

    context, variant = await build_progressive_context_with_variant(
        query=query,
        scope=scope,
        scope_id=scope_id,
        include_global=include_global,
        task_type=task_type,
        phase=phase,
        variant_override=variant_override,
        external_id=external_id,
        project_id=project_id,
        consumer_profile=consumer_profile,
    )

    memory_formatted = await format_context_with_continuity(
        context=context,
        scope=scope,
        scope_id=scope_id,
        current_branch=current_branch,
        session_id=session_id,
        consumer_profile=consumer_profile,
    )

    effective_project_id = project_id or scope_id
    blocks: list[str] = []

    project_index_block = format_project_index_context(
        effective_project_id, consumer_profile=consumer_profile, task_type=task_type,
    )
    if project_index_block:
        blocks.append(project_index_block)
        context.debug_info["project_index_included"] = True

    visible_tool_names = (
        await get_visible_tools_for_project(effective_project_id)
        if effective_project_id
        else frozenset()
    )
    tool_capability_block = format_tool_capability_context(
        consumer_profile=consumer_profile,
        task_type=task_type,
        project_id=effective_project_id,
        bash_available=("bash" in visible_tool_names) if effective_project_id else None,
    )
    if tool_capability_block:
        blocks.append(tool_capability_block)
        context.debug_info["tool_capabilities_included"] = True

    if memory_formatted:
        blocks.append(memory_formatted)

    formatted = "\n".join(blocks) if blocks else ""
    latency_ms = int((time.monotonic() - start_time) * 1000)

    await track_and_record_metrics(
        context=context,
        variant=variant,
        start_time=start_time,
        query=query,
        session_id=session_id,
        external_id=external_id,
        project_id=project_id,
        scope_id=scope_id,
    )

    return _assemble_context_response(
        context,
        formatted,
        variant,
        debug,
        attempts=1,
        latency_ms=latency_ms,
    )


async def build_progressive_context_response(
    query: str,
    scope: MemoryScope,
    scope_id: str | None,
    debug: bool,
    include_global: bool,
    task_type: str | None,
    phase: str | None = None,
    variant_override: str | None = None,
    external_id: str | None = None,
    project_id: str | None = None,
    session_id: str | None = None,
    current_branch: str | None = None,
    consumer_profile: str | None = None,
) -> ProgressiveContextResponse:
    """Build progressive context response with retries and fail-closed fallback."""

    async def _operation() -> ProgressiveContextResponse:
        return await _build_progressive_context_response_once(
            query=query,
            scope=scope,
            scope_id=scope_id,
            debug=debug,
            include_global=include_global,
            task_type=task_type,
            phase=phase,
            variant_override=variant_override,
            external_id=external_id,
            project_id=project_id,
            session_id=session_id,
            current_branch=current_branch,
            consumer_profile=consumer_profile,
        )

    response, failure, attempts, latency_ms = await run_with_memory_retries(
        _operation,
        operation_name="progressive-context",
    )
    if failure:
        return _build_failure_response(
            failure,
            consumer_profile=consumer_profile,
            project_id=project_id or scope_id,
        )
    assert response is not None
    response.attempts = attempts
    response.latency_ms = latency_ms
    return response


async def handle_save_learning(
    request: SaveLearningRequest,
    scope: MemoryScope,
    scope_id: str | None,
) -> SaveLearningResponse:
    """Handle save learning request with all validation and storage logic."""
    return await save_learning_with_validation(request, scope, scope_id)
