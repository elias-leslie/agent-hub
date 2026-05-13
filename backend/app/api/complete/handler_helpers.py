"""Private helpers for completion request handlers."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any, cast

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Session as DBSession
from app.models import SessionEventType, TruncationEvent
from app.services.context_tracker import log_token_usage
from app.services.event_storage import store_child_session_lifecycle_event
from app.services.events import publish_complete, publish_message
from app.services.response_cache import get_response_cache
from app.services.session_live_activity import mark_session_completed
from app.services.token_counter import build_output_usage, estimate_cost

from .event_helpers import save_events
from .execution_observability import persist_execution_observability
from .helpers import is_error_response
from .schemas import (
    CacheInfo,
    CompletionRequest,
    CompletionResponse,
    ContainerInfo,
    ContextUsageInfo,
    OutputUsageInfo,
    ThinkingInfo,
    ToolCallInfo,
    UsageInfo,
)
from .session_repo import apply_execution_metadata, update_provider_metadata

logger = logging.getLogger(__name__)

async def save_and_track(
    db: AsyncSession,
    session: DBSession,
    session_id: str,
    request: CompletionRequest,
    result: Any,
    resolved_model: str,
    is_new_session: bool,
    model_used: str | None = None,
    fallback_reason: str | None = None,
    publish_messages: bool = False,
    duration_ms: int | None = None,
) -> None:
    """Save events and track token usage, costs, and session status."""
    source_metadata = (
        request.source_metadata.model_dump(exclude_none=True)
        if request.source_metadata is not None
        else None
    )
    effective_model = model_used or resolved_model
    tool_calls_count = getattr(result, "tool_calls_count", None)
    if tool_calls_count is None:
        tool_calls_count = len(getattr(result, "tool_calls", None) or [])
    turns_completed = getattr(result, "turns", 1)
    apply_execution_metadata(
        session,
        requested_model=resolved_model,
        effective_model=effective_model,
        fallback_used=effective_model != resolved_model,
        fallback_reason=fallback_reason,
    )
    await persist_execution_observability(
        db,
        session,
        session_id,
        provider=getattr(result, "provider", session.provider),
        model_used=effective_model,
        requested_max_turns=request.max_turns,
        orchestration_path="tool_loop" if request.execute_tools or request.max_turns > 1 else "single_turn",
        final_finish_reason=getattr(result, "finish_reason", None),
        execution_status="success",
        execution_error=None,
        turns_completed=turns_completed,
        tool_calls_count=tool_calls_count,
    )
    await save_events(
        db, session_id, request.messages, result.content,
        result.input_tokens, result.output_tokens, effective_model,
        getattr(result, "thinking_content", None),
        getattr(result, "thinking_tokens", None),
        agent_id=request.agent_slug, duration_ms=duration_ms,
        source_metadata=source_metadata,
    )
    if publish_messages:
        for msg in request.messages:
            if msg.role in ("user", "system"):
                await publish_message(
                    session_id, msg.role,
                    msg.content if isinstance(msg.content, str) else str(msg.content),
                )
        await publish_message(session_id, "assistant", result.content, result.output_tokens)
    cost = estimate_cost(result.input_tokens, result.output_tokens, effective_model)
    await log_token_usage(
        db, session_id, effective_model,
        result.input_tokens, result.output_tokens, cost.total_cost_usd,
    )
    await publish_complete(session_id, result.input_tokens, result.output_tokens, cost.total_cost_usd)
    # Record token usage for quota tracking
    if request.agent_slug:
        from app.services.quota import record_token_usage

        total_tokens = result.input_tokens + result.output_tokens
        await record_token_usage(request.agent_slug, total_tokens)
    # Record cost for project budget tracking
    if request.project_id and cost.total_cost_usd > 0:
        from app.services.project_budget import record_project_cost

        await record_project_cost(request.project_id, cost.total_cost_usd)
    if getattr(result, "cache_metrics", None):
        await update_provider_metadata(db, session, {
            "cache_creation_input_tokens": result.cache_metrics.cache_creation_input_tokens,
            "cache_read_input_tokens": result.cache_metrics.cache_read_input_tokens,
        })
    if is_new_session:
        mark_session_completed(
            session,
            summary="Execution completed",
            termination_reason=None,
        )
    else:
        session.health_detail = "completed"
    session.last_activity_at = datetime.now(UTC)
    await store_child_session_lifecycle_event(
        db,
        session,
        SessionEventType.CHILD_SESSION_RESULT,
        summary="Child session completed",
        status="completed",
    )
    await db.commit()


def make_output_usage_info(result: Any, resolved_model: str) -> OutputUsageInfo:
    """Build OutputUsageInfo from completion result."""
    usage = build_output_usage(result.output_tokens, None, resolved_model, result.finish_reason)
    return OutputUsageInfo(
        output_tokens=usage.output_tokens,
        max_tokens_requested=usage.max_tokens_requested,
        model_limit=usage.model_limit,
        was_truncated=usage.was_truncated,
        warning=usage.warning,
    )


def make_completion_response(
    result: Any,
    session_id: str,
    context_usage: ContextUsageInfo | None,
    output_usage: OutputUsageInfo,
    from_cache: bool = False,
    **kwargs: Any,
) -> CompletionResponse:
    """Build a CompletionResponse with all standard fields."""
    tool_calls_info = kwargs.get("tool_calls_info")
    tool_calls_count = kwargs.get("tool_calls_count")
    if tool_calls_count is None:
        tool_calls_count = len(tool_calls_info) if tool_calls_info else 0
    return CompletionResponse(
        content=result.content,
        model=result.model,
        provider=result.provider,
        usage=UsageInfo(
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            total_tokens=result.input_tokens + result.output_tokens,
            cache=kwargs.get("cache_info"),
        ),
        context_usage=context_usage,
        output_usage=output_usage,
        session_id=session_id,
        finish_reason=result.finish_reason,
        from_cache=from_cache,
        thinking=kwargs.get("thinking_info"),
        tool_calls=kwargs.get("tool_calls_info"),
        container=kwargs.get("container_info"),
        memory_facts_injected=kwargs.get("memory_facts_injected", 0),
        memory_uuids=kwargs.get("memory_uuids"),
        agent_used=kwargs.get("agent_used"),
        model_used=kwargs.get("model_used"),
        fallback_used=kwargs.get("fallback_used", False),
        fallback_reason=kwargs.get("fallback_reason"),
        turns=kwargs.get("turns", 1),
        tool_calls_count=tool_calls_count,
        progress_log=kwargs.get("progress_log"),
        error_summary=kwargs.get("error_summary"),
        trace_id=kwargs.get("trace_id"),
        cited_uuids=kwargs.get("cited_uuids", []),
    )


def build_cache_info(result: Any) -> CacheInfo | None:
    """Build CacheInfo from result cache_metrics, or None."""
    if not result.cache_metrics:
        return None
    return CacheInfo(
        cache_creation_input_tokens=result.cache_metrics.cache_creation_input_tokens,
        cache_read_input_tokens=result.cache_metrics.cache_read_input_tokens,
        cache_hit_rate=result.cache_metrics.cache_hit_rate,
    )


def build_thinking_info(
    result: Any, request: CompletionRequest, resolved_model: str,
    effective_thinking_level: str | None = None,
) -> ThinkingInfo | None:
    """Build ThinkingInfo from result, or None."""
    if not result.thinking_content:
        return None
    thinking_cost = (
        estimate_cost(result.thinking_tokens, 0, resolved_model).input_cost_usd
        if result.thinking_tokens else None
    )
    return ThinkingInfo(
        content=result.thinking_content,
        tokens=result.thinking_tokens,
        level_used=effective_thinking_level or request.thinking_level,
        cost_usd=thinking_cost,
    )


def build_tool_calls_info(result: Any) -> list[ToolCallInfo] | None:
    """Build list of ToolCallInfo from result tool_calls, or None."""
    if not result.tool_calls:
        return None
    return [
        ToolCallInfo(
            id=tc.id, name=tc.name, input=tc.input,
            caller_type=tc.caller_type, caller_tool_id=tc.caller_tool_id,
        )
        for tc in result.tool_calls
    ]


def build_container_info(result: Any) -> ContainerInfo | None:
    """Build ContainerInfo from result container, or None."""
    if not result.container:
        return None
    return ContainerInfo(id=result.container.id, expires_at=result.container.expires_at)


async def cache_result_if_needed(
    result: Any,
    request: CompletionRequest,
    resolved_model: str,
    messages_dict: list[dict[str, Any]],
    skip_cache: bool,
) -> None:
    """Store result in response cache unless skipped or error."""
    if skip_cache:
        return
    if is_error_response(result.content):
        logger.warning(f"Not caching error response for {request.model}")
        return
    await get_response_cache().set(
        model=resolved_model,
        messages=cast(list[dict[str, str]], messages_dict),
        temperature=request.temperature,
        content=result.content,
        provider=result.provider,
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
        finish_reason=result.finish_reason,
    )


async def log_truncation_if_needed(
    result: Any,
    output_usage: OutputUsageInfo,
    resolved_model: str,
    session_id: str,
    request: CompletionRequest,
    db: AsyncSession | None,
    session: DBSession | None,
) -> None:
    """Record a TruncationEvent if the output was truncated."""
    if not output_usage.was_truncated or not db:
        return
    db.add(TruncationEvent(
        session_id=session_id if session else None,
        model=resolved_model,
        endpoint="complete",
        max_tokens_requested=None,
        output_tokens=result.output_tokens,
        model_limit=output_usage.model_limit,
        was_capped=0,
        project_id=request.project_id,
    ))
    await db.commit()
    logger.info(f"Truncated: {resolved_model}, {result.output_tokens} tokens")
