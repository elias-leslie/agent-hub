"""Request handlers for completion API."""

from __future__ import annotations

import hashlib
import logging
import uuid
from typing import Any, Literal, cast

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.base import CompletionResult, Message
from app.api.orchestration_models import AgentProgressInfo
from app.core.debug import debug, debug_async_timer
from app.models import Session as DBSession
from app.models import TruncationEvent
from app.services.agent_routing import complete_with_fallback, inject_system_prompt_into_messages
from app.services.context_tracker import log_token_usage
from app.services.events import publish_complete, publish_message, publish_session_start
from app.services.memory import (
    extract_uuid_prefixes,
    inject_progressive_context,
    parse_memory_group_id,
    resolve_full_uuids,
    track_loaded_batch,
    track_referenced_batch,
)
from app.services.response_cache import get_response_cache
from app.services.token_counter import build_output_usage, estimate_cost

from .core import complete_internal, get_or_create_session, save_messages, update_provider_metadata
from .helpers import get_adapter, is_error_response, should_enable_thinking
from .schemas import (
    CacheInfo,
    CompletionRequest,
    CompletionResponse,
    ContainerInfo,
    ContextUsageInfo,
    MessageInput,
    OutputUsageInfo,
    ThinkingInfo,
    ToolCallInfo,
    UsageInfo,
)

logger = logging.getLogger(__name__)


async def handle_agentic_execution(
    request: CompletionRequest,
    resolved_model: str,
    provider: str,
    agent_mandate_injection: Any,
    agent_used: str | None,
    fallback_used: bool,
    resolved_agent: Any,
    request_hash: str,
) -> CompletionResponse:
    """Handle agentic execution mode (max_turns > 1 or execute_tools=True)."""
    from app.services.agent_runner import AgentConfig, get_agent_runner

    logger.info(
        f"DEBUG[{request_hash}] Agentic mode: max_turns={request.max_turns}, "
        f"execute_tools={request.execute_tools}, working_dir={request.working_dir}"
    )

    # Build system prompt from agent mandate injection if available
    system_prompt = agent_mandate_injection.system_content if agent_mandate_injection else None

    # Extract the task from the last user message
    task = ""
    for msg in reversed(request.messages):
        if msg.role == "user":
            task = msg.content if isinstance(msg.content, str) else str(msg.content)
            break

    if not task:
        raise HTTPException(
            status_code=400,
            detail="No user message found for agentic execution",
        )

    # Get tool permissions from resolved agent if available
    tool_permissions: dict[str, Any] | None = None
    if resolved_agent and resolved_agent.agent.tool_permissions:
        tool_permissions = resolved_agent.agent.tool_permissions

    # Build AgentConfig
    agent_config = AgentConfig(
        provider=cast(Literal["claude", "gemini"], provider),
        model=resolved_model,
        system_prompt=system_prompt,
        temperature=request.temperature,
        max_turns=request.max_turns,
        thinking_level=request.thinking_level,
        enable_code_execution=request.enable_programmatic_tools or request.execute_tools,
        container_id=request.container_id,
        working_dir=request.working_dir,
        project_id=request.project_id,
        use_memory=request.use_memory,
        memory_group_id=request.memory_group_id,
        agent_slug=request.agent_slug,
        resume_session_id=request.session_id,
        tool_permissions=tool_permissions,
        trace_id=request.trace_id,
    )

    # Run the agent
    runner = get_agent_runner()
    agent_result = await runner.run(task=task, config=agent_config)

    logger.info(
        f"DEBUG[{request_hash}] Agentic execution complete: status={agent_result.status}, "
        f"turns={agent_result.turns}, tokens={agent_result.input_tokens}+{agent_result.output_tokens}"
    )

    # Convert AgentResult to CompletionResponse
    return CompletionResponse(
        content=agent_result.content,
        model=agent_result.model,
        provider=agent_result.provider,
        usage=UsageInfo(
            input_tokens=agent_result.input_tokens,
            output_tokens=agent_result.output_tokens,
            total_tokens=agent_result.input_tokens + agent_result.output_tokens,
            cache=None,
        ),
        context_usage=None,
        output_usage=None,
        session_id=agent_result.session_id or str(uuid.uuid4()),
        finish_reason="end_turn" if agent_result.status == "success" else agent_result.status,
        from_cache=False,
        thinking=ThinkingInfo(
            content="",
            tokens=agent_result.thinking_tokens,
            level_used=request.thinking_level,
        )
        if agent_result.thinking_tokens
        else None,
        tool_calls=None,
        container=ContainerInfo(
            id=agent_result.container_id,
            expires_at="",
        )
        if agent_result.container_id
        else None,
        memory_facts_injected=len(agent_result.memory_uuids),
        memory_uuids=",".join(agent_result.memory_uuids) if agent_result.memory_uuids else None,
        agent_used=agent_used,
        model_used=agent_result.model,
        fallback_used=fallback_used,
        turns=agent_result.turns,
        tool_calls_count=agent_result.tool_calls_count,
        progress_log=[
            AgentProgressInfo(
                turn=p.turn,
                status=p.status,
                message=p.message,
                tool_calls=p.tool_calls,
                tool_results=p.tool_results,
                thinking=p.thinking,
            )
            for p in agent_result.progress_log
        ]
        if agent_result.progress_log
        else None,
        trace_id=request.trace_id,
        cited_uuids=agent_result.cited_uuids,
    )


async def handle_cached_response(
    cached: Any,
    db: AsyncSession | None,
    session: DBSession | None,
    session_id: str,
    request: CompletionRequest,
    resolved_model: str,
    context_usage_info: ContextUsageInfo | None,
    memory_facts_injected: int,
) -> CompletionResponse:
    """Handle cached response."""
    logger.info(f"Returning cached response for {resolved_model}")
    # Always save to session (mandatory tracking)
    if db and session:
        await save_messages(
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


async def execute_completion(
    request: CompletionRequest,
    resolved_model: str,
    provider: str,
    messages_dict: list[dict[str, Any]],
    all_messages: list[Message],
    resolved_agent: Any,
    request_hash: str,
    client_id: str | None,
    request_source: str | None,
    skip_cache: bool,
) -> tuple[CompletionResult, str | None, bool, str, list[str]]:
    """Execute the completion request.

    Returns: (result, model_used, fallback_used, session_id, loaded_memory_uuids)
    """
    adapter = get_adapter(provider)

    # Determine thinking level
    thinking_level = request.thinking_level
    if request.auto_thinking and not thinking_level and should_enable_thinking(all_messages):
        thinking_level = "medium"

    # Convert tools to API format if provided
    tools_api: list[dict[str, Any]] | None = None
    if request.tools:
        tools_api = [
            {
                "name": t.name,
                "description": t.description,
                "input_schema": t.input_schema,
                **(
                    {"allowed_callers": t.allowed_callers}
                    if t.allowed_callers != ["direct"]
                    else {}
                ),
            }
            for t in request.tools
        ]

    # Build response_format dict for adapter
    response_format_dict: dict[str, Any] | None = None
    if request.response_format:
        response_format_dict = {
            "type": request.response_format.type,
            "schema": request.response_format.schema_,
        }

    # Make completion request with full context
    messages_for_adapter = [
        Message(
            role=cast(Literal["user", "assistant", "system"], m["role"]),
            content=m["content"],
        )
        for m in messages_dict
    ]

    model_used: str | None = None
    fallback_used = False
    loaded_memory_uuids: list[str] = []
    session_id = request.session_id or str(uuid.uuid4())

    # Use agent fallback chain if agent routing is enabled
    if resolved_agent and resolved_agent.agent.fallback_models:
        effective_temperature = resolved_agent.agent.temperature
        fallback_result = await complete_with_fallback(
            messages=messages_for_adapter,
            agent=resolved_agent.agent,
            temperature=effective_temperature,
            tools=tools_api,
        )
        result: CompletionResult = fallback_result.result
        model_used = fallback_result.model_used
        fallback_used = fallback_result.used_fallback
        if fallback_used:
            logger.info(f"DEBUG[{request_hash}] Agent fallback used: {model_used}")
    else:
        # Use complete_internal for simple completions
        if (
            not tools_api
            and not request.enable_programmatic_tools
            and not response_format_dict
        ):
            from app.db import get_db
            # Get DB session (this is a simplification - in real code it's passed in)
            db = None  # Will be passed from caller
            if db:
                internal_result = await complete_internal(
                    messages=messages_dict,
                    model=resolved_model,
                    provider=provider,
                    temperature=request.temperature,
                    project_id=request.project_id,
                    db=db,
                    session_id=request.session_id,
                    external_id=request.external_id,
                    client_id=client_id,
                    request_source=request_source,
                    agent_slug=request.agent_slug,
                    use_memory=request.use_memory,
                    memory_group_id=request.memory_group_id,
                    enable_caching=request.enable_caching,
                    cache_ttl=request.cache_ttl,
                    thinking_level=thinking_level,
                    skip_cache=skip_cache,
                    user_messages_for_db=request.messages,
                )
                result = CompletionResult(
                    content=internal_result.content,
                    model=internal_result.model,
                    provider=internal_result.provider,
                    input_tokens=internal_result.input_tokens,
                    output_tokens=internal_result.output_tokens,
                    finish_reason=internal_result.finish_reason,
                    cache_metrics=internal_result.cache_metrics,
                    thinking_content=internal_result.thinking_content,
                    thinking_tokens=internal_result.thinking_tokens,
                    tool_calls=internal_result.tool_calls,
                    container=internal_result.container,
                )
                model_used = resolved_model
                loaded_memory_uuids = internal_result.memory_uuids
                session_id = internal_result.session_id
                return result, model_used, fallback_used, session_id, loaded_memory_uuids

        # Standard completion with tools or special features
        debug(f"LLM request: model={resolved_model}, messages={len(messages_for_adapter)}")
        async with debug_async_timer(f"adapter.complete ({resolved_model})"):
            result = await adapter.complete(
                messages=messages_for_adapter,
                model=resolved_model,
                max_tokens=None,
                temperature=request.temperature,
                enable_caching=request.enable_caching,
                cache_ttl=request.cache_ttl,
                thinking_level=thinking_level,
                tools=tools_api,
                enable_programmatic_tools=request.enable_programmatic_tools,
                container_id=request.container_id,
                response_format=response_format_dict,
            )
        debug(f"LLM response: tokens={result.input_tokens}+{result.output_tokens}")
        model_used = resolved_model

    return result, model_used, fallback_used, session_id, loaded_memory_uuids


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
        logger.warning(
            f"Not caching error response for {request.model}: {result.content[:100]}..."
        )

    # Always save messages to database (mandatory tracking)
    if db and session:
        await save_messages(
            db,
            session_id,
            request.messages,
            result.content,
            result.input_tokens,
            result.output_tokens,
            model_used=resolved_model,
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
        logger.info(
            f"Response truncated: model={resolved_model}, tokens={result.output_tokens}"
        )

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
