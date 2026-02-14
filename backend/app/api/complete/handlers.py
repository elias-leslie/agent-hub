"""Request handlers for completion API."""

from __future__ import annotations

import logging
from typing import Any, cast

from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.base import CompletionResult
from app.models import Session as DBSession
from app.models import TruncationEvent
from app.services.context_tracker import log_token_usage
from app.services.events import publish_complete, publish_message
from app.services.memory import (
    extract_uuid_prefixes,
    parse_memory_group_id,
    resolve_full_uuids,
    track_helpful,
    track_referenced_batch,
)
from app.services.response_cache import get_response_cache
from app.services.token_counter import build_output_usage, estimate_cost

from .event_helpers import save_events
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
from .session_manager import update_provider_metadata

logger = logging.getLogger(__name__)


async def _save_and_track(
    db: AsyncSession, session: DBSession, session_id: str,
    request: CompletionRequest, result: Any, resolved_model: str,
    is_new_session: bool, publish_messages: bool = False,
    duration_ms: int | None = None,
) -> None:
    """Save events and track usage."""
    await save_events(
        db, session_id, request.messages, result.content,
        result.input_tokens, result.output_tokens, resolved_model,
        getattr(result, "thinking_content", None), getattr(result, "thinking_tokens", None),
        agent_id=request.agent_slug, duration_ms=duration_ms,
    )
    if publish_messages:
        for msg in request.messages:
            if msg.role in ("user", "system"):
                await publish_message(
                    session_id, msg.role,
                    msg.content if isinstance(msg.content, str) else str(msg.content),
                )
        await publish_message(session_id, "assistant", result.content, result.output_tokens)
    cost = estimate_cost(result.input_tokens, result.output_tokens, resolved_model)
    await log_token_usage(db, session_id, resolved_model,
                          result.input_tokens, result.output_tokens, cost.total_cost_usd)
    await publish_complete(session_id, result.input_tokens, result.output_tokens, cost.total_cost_usd)
    if hasattr(result, "cache_metrics") and result.cache_metrics:
        await update_provider_metadata(db, session, {
            "cache_creation_input_tokens": result.cache_metrics.cache_creation_input_tokens,
            "cache_read_input_tokens": result.cache_metrics.cache_read_input_tokens,
        })
    if is_new_session:
        session.status = "completed"
    await db.commit()


def _make_output_usage_info(result: Any, resolved_model: str) -> OutputUsageInfo:
    """Build OutputUsageInfo from result."""
    usage = build_output_usage(result.output_tokens, None, resolved_model, result.finish_reason)
    return OutputUsageInfo(
        output_tokens=usage.output_tokens, max_tokens_requested=usage.max_tokens_requested,
        model_limit=usage.model_limit, was_truncated=usage.was_truncated, warning=usage.warning,
    )


def _make_response(
    result: Any, session_id: str, context_usage: ContextUsageInfo | None,
    output_usage: OutputUsageInfo, from_cache: bool = False, **kwargs: Any,
) -> CompletionResponse:
    """Build CompletionResponse with common fields."""
    return CompletionResponse(
        content=result.content, model=result.model, provider=result.provider,
        usage=UsageInfo(
            input_tokens=result.input_tokens, output_tokens=result.output_tokens,
            total_tokens=result.input_tokens + result.output_tokens,
            cache=kwargs.get("cache_info"),
        ),
        context_usage=context_usage, output_usage=output_usage,
        session_id=session_id, finish_reason=result.finish_reason, from_cache=from_cache,
        thinking=kwargs.get("thinking_info"), tool_calls=kwargs.get("tool_calls_info"),
        container=kwargs.get("container_info"),
        memory_facts_injected=kwargs.get("memory_facts_injected", 0),
        memory_uuids=kwargs.get("memory_uuids"),
        agent_used=kwargs.get("agent_used"), model_used=kwargs.get("model_used"),
        fallback_used=kwargs.get("fallback_used", False), turns=1,
        tool_calls_count=len(kwargs["tool_calls_info"]) if kwargs.get("tool_calls_info") else 0,
        progress_log=None, trace_id=None, cited_uuids=kwargs.get("cited_uuids", []),
    )


async def handle_cached_response(
    cached: Any, db: AsyncSession | None, session: DBSession | None,
    session_id: str, request: CompletionRequest, resolved_model: str,
    context_usage_info: ContextUsageInfo | None, memory_facts_injected: int,
    is_new_session: bool = False,
) -> CompletionResponse:
    """Handle cached response."""
    logger.info(f"Returning cached response for {resolved_model}")
    if db and session:
        await _save_and_track(
            db, session, session_id, request, cached, resolved_model, is_new_session
        )
    return _make_response(
        cached, session_id, context_usage_info, _make_output_usage_info(cached, resolved_model),
        from_cache=True, memory_facts_injected=memory_facts_injected,
    )


async def process_completion_result(
    result: CompletionResult, request: CompletionRequest, resolved_model: str,
    session_id: str, db: AsyncSession | None, session: DBSession | None,
    skip_cache: bool, messages_dict: list[dict[str, Any]],
    context_usage_info: ContextUsageInfo | None, memory_facts_injected: int,
    loaded_memory_uuids: list[str], agent_used: str | None,
    model_used: str | None, fallback_used: bool, is_new_session: bool = False,
    external_id: str | None = None, duration_ms: int | None = None,
) -> CompletionResponse:
    """Process completion result and build response."""
    # Cache if appropriate
    if not skip_cache and not is_error_response(result.content):
        await get_response_cache().set(
            model=resolved_model, messages=cast(list[dict[str, str]], messages_dict),
            temperature=request.temperature, content=result.content,
            provider=result.provider, input_tokens=result.input_tokens,
            output_tokens=result.output_tokens, finish_reason=result.finish_reason,
        )
    elif is_error_response(result.content):
        logger.warning(f"Not caching error response for {request.model}")
    # Save and publish
    if db and session:
        await _save_and_track(
            db, session, session_id, request, result, resolved_model, is_new_session,
            publish_messages=True, duration_ms=duration_ms,
        )
    # Build usage and log truncation
    output_usage_info = _make_output_usage_info(result, resolved_model)
    if output_usage_info.was_truncated and db:
        db.add(TruncationEvent(
            session_id=session_id if session else None, model=resolved_model,
            endpoint="complete", max_tokens_requested=None,
            output_tokens=result.output_tokens, model_limit=output_usage_info.model_limit,
            was_capped=0, project_id=request.project_id,
        ))
        await db.commit()
        logger.info(f"Truncated: {resolved_model}, {result.output_tokens} tokens")
    # Track citations
    cited_uuids: list[str] = []
    if loaded_memory_uuids and result.content:
        try:
            cited_prefixes = extract_uuid_prefixes(result.content)
            if cited_prefixes:
                scope, scope_id = parse_memory_group_id(request.memory_group_id)
                group_id = "global" if scope.value == "global" else f"{scope.value}-{scope_id}"
                cited_uuids = list((await resolve_full_uuids(cited_prefixes, group_id)).values())
                if cited_uuids:
                    await track_referenced_batch(cited_uuids)
                    from app.services.memory.metrics_collector import update_citation_metrics
                    await update_citation_metrics(
                        session_id=session_id,
                        external_id=external_id,
                        memories_cited=cited_uuids,
                    )
                    logger.info(f"Tracked {len(cited_uuids)} citations")
                    if not is_error_response(result.content):
                        for cited_uuid in cited_uuids:
                            track_helpful(cited_uuid)
                        logger.info(f"Auto-rated {len(cited_uuids)} cited memories as helpful")
        except Exception as e:
            logger.warning(f"Citation tracking failed: {e}")
    # Build metadata
    cache_info = (CacheInfo(
        cache_creation_input_tokens=result.cache_metrics.cache_creation_input_tokens,
        cache_read_input_tokens=result.cache_metrics.cache_read_input_tokens,
        cache_hit_rate=result.cache_metrics.cache_hit_rate,
    ) if result.cache_metrics else None)
    thinking_info = None
    if result.thinking_content:
        thinking_cost = (estimate_cost(result.thinking_tokens, 0, resolved_model).input_cost_usd
                        if result.thinking_tokens else None)
        thinking_info = ThinkingInfo(
            content=result.thinking_content, tokens=result.thinking_tokens,
            level_used=request.thinking_level, cost_usd=thinking_cost,
        )
    tool_calls_info = ([ToolCallInfo(
        id=tc.id, name=tc.name, input=tc.input,
        caller_type=tc.caller_type, caller_tool_id=tc.caller_tool_id,
    ) for tc in result.tool_calls] if result.tool_calls else None)
    container_info = (ContainerInfo(id=result.container.id, expires_at=result.container.expires_at)
                     if result.container else None)
    return _make_response(
        result, session_id, context_usage_info, output_usage_info,
        cache_info=cache_info, thinking_info=thinking_info,
        tool_calls_info=tool_calls_info, container_info=container_info,
        memory_facts_injected=memory_facts_injected,
        memory_uuids=",".join(loaded_memory_uuids) if loaded_memory_uuids else None,
        agent_used=agent_used, model_used=model_used,
        fallback_used=fallback_used, cited_uuids=cited_uuids,
    )
