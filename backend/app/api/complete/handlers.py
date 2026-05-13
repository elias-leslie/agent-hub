"""Request handlers for completion API."""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Session as DBSession

from .citation_tracker import track_citations_with_metrics
from .handler_helpers import (
    build_cache_info,
    build_container_info,
    build_thinking_info,
    build_tool_calls_info,
    cache_result_if_needed,
    log_truncation_if_needed,
    make_completion_response,
    make_output_usage_info,
    save_and_track,
)
from .helpers import is_error_response
from .schemas import CompletionRequest, CompletionResponse, ContextUsageInfo

logger = logging.getLogger(__name__)


async def build_cached_completion_response(
    cached: Any,
    db: AsyncSession | None,
    session: DBSession | None,
    session_id: str,
    request: CompletionRequest,
    resolved_model: str,
    context_usage_info: ContextUsageInfo | None,
    memory_facts_injected: int,
    is_new_session: bool = False,
) -> CompletionResponse:
    """Handle cached response."""
    logger.info(f"Returning cached response for {resolved_model}")
    if db and session:
        await save_and_track(
            db, session, session_id, request, cached, resolved_model, is_new_session,
            model_used=getattr(cached, "model", resolved_model),
        )
    output_usage = make_output_usage_info(cached, resolved_model)
    return make_completion_response(
        cached, session_id, context_usage_info, output_usage,
        from_cache=True, memory_facts_injected=memory_facts_injected,
    )


async def process_completion_result(
    result: Any,
    request: CompletionRequest,
    resolved_model: str,
    session_id: str,
    db: AsyncSession | None,
    session: DBSession | None,
    skip_cache: bool,
    messages_dict: list[dict[str, Any]],
    context_usage_info: ContextUsageInfo | None,
    memory_facts_injected: int,
    loaded_memory_uuids: list[str],
    agent_used: str | None,
    model_used: str | None,
    fallback_used: bool,
    fallback_reason: str | None = None,
    is_new_session: bool = False,
    external_id: str | None = None,
    duration_ms: int | None = None,
    effective_thinking_level: str | None = None,
) -> CompletionResponse:
    """Process completion result and build response."""
    await cache_result_if_needed(result, request, resolved_model, messages_dict, skip_cache)
    if db and session:
        await save_and_track(
            db, session, session_id, request, result, resolved_model, is_new_session,
            model_used=model_used,
            fallback_reason=fallback_reason,
            publish_messages=True, duration_ms=duration_ms,
        )
    output_usage_info = make_output_usage_info(result, resolved_model)
    await log_truncation_if_needed(
        result, output_usage_info, resolved_model, session_id, request, db, session,
    )
    cited_uuids = await track_citations_with_metrics(
        content=result.content,
        loaded_memory_uuids=loaded_memory_uuids,
        memory_group_id=request.memory_group_id,
        session_id=session_id,
        external_id=external_id,
        is_error=is_error_response(result.content),
        db=db,
        agent_id=agent_used,
        model_used=model_used,
    )
    return make_completion_response(
        result, session_id, context_usage_info, output_usage_info,
        cache_info=build_cache_info(result),
        thinking_info=build_thinking_info(result, request, resolved_model, effective_thinking_level),
        tool_calls_info=build_tool_calls_info(result),
        container_info=build_container_info(result),
        memory_facts_injected=memory_facts_injected,
        memory_uuids=",".join(loaded_memory_uuids) if loaded_memory_uuids else None,
        agent_used=agent_used,
        model_used=model_used,
        fallback_used=fallback_used,
        fallback_reason=fallback_reason,
        cited_uuids=cited_uuids,
    )
