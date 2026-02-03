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
    track_referenced_batch,
)
from app.services.response_cache import get_response_cache
from app.services.token_counter import build_output_usage, estimate_cost

from .core import save_events, update_provider_metadata
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

logger = logging.getLogger(__name__)


async def handle_cached_response(
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
    # Always save to session (mandatory tracking)
    if db and session:
        await save_events(
            db,
            session_id,
            request.messages,
            cached.content,
            cached.input_tokens,
            cached.output_tokens,
            model_used=resolved_model,
        )
        # Log token usage for cached response too
        cost = estimate_cost(cached.input_tokens, cached.output_tokens, resolved_model)
        await log_token_usage(
            db,
            session_id,
            resolved_model,
            cached.input_tokens,
            cached.output_tokens,
            cost.total_cost_usd,
        )
        # Publish complete event for cached response (skip message events)
        await publish_complete(
            session_id, cached.input_tokens, cached.output_tokens, cost.total_cost_usd
        )

        # Mark new sessions as completed (cached single-turn completions are done)
        if is_new_session and session:
            session.status = "completed"

        await db.commit()
    # Build output_usage for cached response
    cached_output_usage = build_output_usage(
        output_tokens=cached.output_tokens,
        max_tokens_requested=None,
        model=resolved_model,
        finish_reason=cached.finish_reason,
    )
    cached_output_usage_info = OutputUsageInfo(
        output_tokens=cached_output_usage.output_tokens,
        max_tokens_requested=cached_output_usage.max_tokens_requested,
        model_limit=cached_output_usage.model_limit,
        was_truncated=cached_output_usage.was_truncated,
        warning=cached_output_usage.warning,
    )
    return CompletionResponse(
        content=cached.content,
        model=cached.model,
        provider=cached.provider,
        usage=UsageInfo(
            input_tokens=cached.input_tokens,
            output_tokens=cached.output_tokens,
            total_tokens=cached.input_tokens + cached.output_tokens,
            cache=None,
        ),
        context_usage=context_usage_info,
        output_usage=cached_output_usage_info,
        session_id=session_id,
        finish_reason=cached.finish_reason,
        from_cache=True,
        memory_facts_injected=memory_facts_injected,
        turns=1,
        tool_calls_count=0,
        progress_log=None,
        trace_id=None,
        cited_uuids=[],
    )


async def process_completion_result(
    result: CompletionResult,
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
    is_new_session: bool = False,
) -> CompletionResponse:
    """Process completion result and build response."""
    # Cache the response for future identical requests (but NOT errors)
    cache = get_response_cache()
    if not skip_cache and not is_error_response(result.content):
        await cache.set(
            model=resolved_model,
            messages=cast(list[dict[str, str]], messages_dict),
            temperature=request.temperature,
            content=result.content,
            provider=result.provider,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            finish_reason=result.finish_reason,
        )
    elif is_error_response(result.content):
        logger.warning(f"Not caching error response for {request.model}: {result.content[:100]}...")

    # Always save messages to database (mandatory tracking)
    if db and session:
        await save_events(
            db,
            session_id,
            request.messages,
            result.content,
            result.input_tokens,
            result.output_tokens,
            model_used=resolved_model,
            thinking_content=result.thinking_content,
            thinking_tokens=result.thinking_tokens,
        )
        # Publish message events for user input and assistant response
        for msg in request.messages:
            if msg.role in ("user", "system"):
                content_str = msg.content if isinstance(msg.content, str) else str(msg.content)
                await publish_message(session_id, msg.role, content_str)
        await publish_message(session_id, "assistant", result.content, result.output_tokens)

        # Log token usage for cost tracking
        cost = estimate_cost(result.input_tokens, result.output_tokens, resolved_model)
        await log_token_usage(
            db,
            session_id,
            resolved_model,
            result.input_tokens,
            result.output_tokens,
            cost.total_cost_usd,
        )
        # Publish complete event
        await publish_complete(
            session_id, result.input_tokens, result.output_tokens, cost.total_cost_usd
        )
        # Update provider metadata (cache info, etc.)
        if result.cache_metrics:
            await update_provider_metadata(
                db,
                session,
                {
                    "cache_creation_input_tokens": result.cache_metrics.cache_creation_input_tokens,
                    "cache_read_input_tokens": result.cache_metrics.cache_read_input_tokens,
                },
            )

        # Mark new sessions as completed (single-turn completions are done)
        if is_new_session and session:
            session.status = "completed"

        await db.commit()

    # Build cache info if available
    cache_info = None
    if result.cache_metrics:
        cache_info = CacheInfo(
            cache_creation_input_tokens=result.cache_metrics.cache_creation_input_tokens,
            cache_read_input_tokens=result.cache_metrics.cache_read_input_tokens,
            cache_hit_rate=result.cache_metrics.cache_hit_rate,
        )

    # Build thinking info if available
    thinking_info = None
    if result.thinking_content:
        thinking_cost = None
        if result.thinking_tokens:
            cost_estimate = estimate_cost(result.thinking_tokens, 0, resolved_model)
            thinking_cost = cost_estimate.input_cost_usd

        thinking_info = ThinkingInfo(
            content=result.thinking_content,
            tokens=result.thinking_tokens,
            level_used=request.thinking_level,
            cost_usd=thinking_cost,
        )

    # Build tool calls info if available
    tool_calls_info: list[ToolCallInfo] | None = None
    if result.tool_calls:
        tool_calls_info = [
            ToolCallInfo(
                id=tc.id,
                name=tc.name,
                input=tc.input,
                caller_type=tc.caller_type,
                caller_tool_id=tc.caller_tool_id,
            )
            for tc in result.tool_calls
        ]

    # Build container info if available
    container_info: ContainerInfo | None = None
    if result.container:
        container_info = ContainerInfo(
            id=result.container.id,
            expires_at=result.container.expires_at,
        )

    # Build output usage info with truncation detection
    output_usage = build_output_usage(
        output_tokens=result.output_tokens,
        max_tokens_requested=None,
        model=resolved_model,
        finish_reason=result.finish_reason,
    )
    output_usage_info = OutputUsageInfo(
        output_tokens=output_usage.output_tokens,
        max_tokens_requested=output_usage.max_tokens_requested,
        model_limit=output_usage.model_limit,
        was_truncated=output_usage.was_truncated,
        warning=output_usage.warning,
    )

    # Log truncation event for telemetry
    if output_usage.was_truncated and db:
        truncation_event = TruncationEvent(
            session_id=session_id if session else None,
            model=resolved_model,
            endpoint="complete",
            max_tokens_requested=None,
            output_tokens=result.output_tokens,
            model_limit=output_usage.model_limit,
            was_capped=0,
            project_id=request.project_id,
        )
        db.add(truncation_event)
        await db.commit()
        logger.info(f"Response truncated: model={resolved_model}, tokens={result.output_tokens}")

    # Track cited memory rules from response
    cited_uuids: list[str] = []
    if loaded_memory_uuids and result.content:
        try:
            cited_prefixes = extract_uuid_prefixes(result.content)
            if cited_prefixes:
                memory_group = request.memory_group_id
                scope, scope_id = parse_memory_group_id(memory_group)
                group_id = "global" if scope.value == "global" else f"{scope.value}-{scope_id}"
                prefix_to_uuid = await resolve_full_uuids(cited_prefixes, group_id)
                cited_uuids = list(prefix_to_uuid.values())
                if cited_uuids:
                    await track_referenced_batch(cited_uuids)
                    logger.info(f"Tracked {len(cited_uuids)} cited memory rules")
        except Exception as e:
            logger.warning(f"Citation tracking failed (continuing): {e}")

    # Build memory UUIDs string for feedback attribution
    memory_uuids_str = ",".join(loaded_memory_uuids) if loaded_memory_uuids else None

    return CompletionResponse(
        content=result.content,
        model=result.model,
        provider=result.provider,
        usage=UsageInfo(
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            total_tokens=result.input_tokens + result.output_tokens,
            cache=cache_info,
        ),
        context_usage=context_usage_info,
        output_usage=output_usage_info,
        session_id=session_id,
        finish_reason=result.finish_reason,
        from_cache=False,
        thinking=thinking_info,
        tool_calls=tool_calls_info,
        container=container_info,
        memory_facts_injected=memory_facts_injected,
        memory_uuids=memory_uuids_str,
        agent_used=agent_used,
        model_used=model_used,
        fallback_used=fallback_used,
        turns=1,
        tool_calls_count=len(tool_calls_info) if tool_calls_info else 0,
        progress_log=None,
        trace_id=None,
        cited_uuids=cited_uuids,
    )
