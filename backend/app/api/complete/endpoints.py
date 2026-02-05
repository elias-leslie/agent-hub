"""Completion API endpoint."""

from __future__ import annotations

import hashlib
import logging
import uuid
from typing import TYPE_CHECKING, Annotated, Any, Literal, cast

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.base import (
    AuthenticationError,
    CompletionResult,
    Message,
    ProviderError,
    RateLimitError,
)
from app.api.complete.core import (
    complete_internal,
    get_or_create_session,
    stream_completion,
)
from app.api.complete.handlers import (
    handle_cached_response,
    process_completion_result,
)
from app.api.complete.helpers import (
    get_adapter,
    get_provider,
    parse_mention,
    should_enable_thinking,
    validate_json_response,
)
from app.api.complete.schemas import (
    CompletionRequest,
    CompletionResponse,
    ContainerInfo,
    ContextUsageInfo,
    EstimateRequest,
    EstimateResponse,
    ThinkingInfo,
    UsageInfo,
)
from app.core.debug import debug, debug_async_timer
from app.db import get_db
from app.models import Session as DBSession
from app.services.agent_routing import (
    complete_with_fallback,
    inject_agent_mandates,
    inject_system_prompt_into_messages,
    resolve_agent,
)
from app.services.context_tracker import (
    check_context_before_request,
)
from app.services.event_storage import store_memory_inject_event
from app.services.events import (
    publish_error,
    publish_session_start,
)
from app.services.memory import (
    inject_progressive_context,
    parse_memory_group_id,
    track_loaded_batch,
)
from app.services.response_cache import get_response_cache
from app.services.token_counter import (
    count_message_tokens,
    estimate_request,
)

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/complete", response_model=CompletionResponse)
async def complete(
    request: CompletionRequest,
    http_request: Request,
    x_skip_cache: Annotated[str | None, Header(alias="X-Skip-Cache")] = None,
    db: Annotated[AsyncSession | None, Depends(get_db)] = None,
) -> CompletionResponse | StreamingResponse:
    """Generate a completion for the given messages.

    Routes to appropriate provider (Claude or Gemini) based on model name.
    Optionally persists messages to database for session continuity.

    Headers:
        X-Skip-Cache: Set to "true" to bypass response cache
    """
    # Validate: agent_slug is required (model parameter is deprecated)
    if not request.agent_slug:
        available_agents: list[str] = []
        if db:
            from app.services.agent_service import get_agent_service

            service = get_agent_service()
            agents = await service.list_agents(db, active_only=True, limit=50)
            available_agents = [f"{a.slug}: {a.description or a.name}" for a in agents]
        raise HTTPException(
            status_code=400,
            detail={
                "error": "agent_slug_required",
                "message": "'agent_slug' is required.",
                "available_agents": available_agents,
                "docs": "/api/agents",
            },
        )

    # Validate project_id against client's allowed projects
    client = getattr(http_request.state, "client", None)
    if client and client.allowed_projects:
        from app.models.client import check_project_access

        if not check_project_access(client.allowed_projects, request.project_id):
            raise HTTPException(
                status_code=403,
                detail={
                    "error": "project_not_allowed",
                    "message": f"Client '{client.display_name}' is not authorized for project '{request.project_id}'",
                    "project_id": request.project_id,
                },
            )

    # DEBUG logging
    request_hash = hashlib.md5(
        f"{request.model or request.agent_slug}:{len(request.messages)}".encode()
    ).hexdigest()[:8]
    logger.info(
        f"DEBUG[{request_hash}] complete() called: model={request.model or 'via-agent'}, "
        f"agent_slug={request.agent_slug}, messages={len(request.messages)}"
    )

    # Resolve agent and model
    resolved_agent = None
    agent_mandate_injection = None
    agent_used: str | None = None
    model_used: str | None = None
    fallback_used = False

    if request.agent_slug:
        if not db:
            raise HTTPException(
                status_code=400,
                detail="Database connection required for agent routing.",
            )
        resolved_agent = await resolve_agent(request.agent_slug, db)
        resolved_model = resolved_agent.model
        provider = resolved_agent.provider
        agent_used = resolved_agent.agent.slug
        http_request.state.agent_slug = request.agent_slug
        agent_mandate_injection = await inject_agent_mandates(resolved_agent.agent, db)
        logger.info(
            f"DEBUG[{request_hash}] Agent routing: {request.agent_slug} -> {resolved_model}"
        )
    else:
        from app.constants import resolve_model as resolve_model_const

        assert request.model is not None
        resolved_model = resolve_model_const(request.model)
        provider = get_provider(resolved_model)

    skip_cache = bool(x_skip_cache and x_skip_cache.lower() == "true")

    # Check for @mention routing
    if request.messages:
        last_user_msg = next((m for m in reversed(request.messages) if m.role == "user"), None)
        if last_user_msg:
            mentioned_model, _ = parse_mention(last_user_msg.content)
            if mentioned_model:
                resolved_model = mentioned_model
                provider = get_provider(resolved_model)

    # Handle streaming mode
    if request.stream:
        session_id = request.session_id or str(uuid.uuid4())
        client_id = getattr(http_request.state, "client_id", None)
        request_source = getattr(http_request.state, "request_source", None)
        stream_context_messages: list[Message] = []
        is_new_session = False
        if db:
            stream_session, stream_context_messages, is_new_session = await get_or_create_session(
                db,
                request.session_id,
                request.project_id,
                provider,
                resolved_model,
                session_type="chat",
                external_id=request.external_id,
                client_id=client_id,
                request_source=request_source,
                agent_slug=request.agent_slug,
            )
            session_id = stream_session.id
            if is_new_session:
                await publish_session_start(session_id, resolved_model, request.project_id)

        new_messages = [
            Message(role=cast(Literal["user", "assistant", "system"], m.role), content=m.content)
            for m in request.messages
        ]
        messages_for_streaming = (
            stream_context_messages + new_messages if stream_context_messages else new_messages
        )

        if agent_mandate_injection:
            messages_for_streaming = inject_system_prompt_into_messages(
                messages_for_streaming, agent_mandate_injection.system_content
            )

        # Inject memory context for streaming requests
        if request.use_memory:
            messages_dict_for_memory = [
                {"role": m.role, "content": m.content} for m in messages_for_streaming
            ]
            scope, scope_id = parse_memory_group_id(request.memory_group_id)
            try:
                messages_dict_for_memory, progressive_context = await inject_progressive_context(
                    messages=messages_dict_for_memory,
                    scope=scope,
                    scope_id=scope_id,
                )
                memory_facts_count = (
                    len(progressive_context.mandates)
                    + len(progressive_context.guardrails)
                    + len(progressive_context.reference)
                )
                if memory_facts_count > 0:
                    logger.info(
                        f"Streaming: Injected {memory_facts_count} memory facts (scope={scope.value})"
                    )
                # Rebuild messages_for_streaming from injected dict
                messages_for_streaming = [
                    Message(
                        role=cast(Literal["user", "assistant", "system"], m["role"]),
                        content=m["content"],
                    )
                    for m in messages_dict_for_memory
                ]
            except Exception as e:
                logger.warning(f"Streaming: Memory injection failed (continuing without): {e}")

        return StreamingResponse(
            stream_completion(
                messages=messages_for_streaming,
                model=resolved_model,
                provider=provider,
                temperature=request.temperature,
                session_id=session_id,
                agent_used=agent_used,
                model_used=model_used,
                fallback_used=fallback_used,
                db=db,
                user_messages=request.messages,
                is_new_session=is_new_session,
                is_one_shot=not request.session_id,
            ),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    # Handle agentic execution mode (consolidated into complete_internal)
    is_agentic = request.max_turns > 1 or request.execute_tools
    if is_agentic:
        logger.info(
            f"DEBUG[{request_hash}] Agentic mode: max_turns={request.max_turns}, "
            f"execute_tools={request.execute_tools}, working_dir={request.working_dir}"
        )

    # Get or create session
    session: DBSession | None = None
    context_messages: list[Message] = []
    session_id = request.session_id or str(uuid.uuid4())
    is_new_session = False
    client_id = getattr(http_request.state, "client_id", None)
    request_source = getattr(http_request.state, "request_source", None)

    if db:
        session, context_messages, is_new_session = await get_or_create_session(
            db,
            request.session_id,
            request.project_id,
            provider,
            resolved_model,
            session_type="completion",
            external_id=request.external_id,
            client_id=client_id,
            request_source=request_source,
            agent_slug=request.agent_slug,
        )
        session_id = session.id
        if is_new_session:
            await publish_session_start(session_id, resolved_model, request.project_id)

    # Build message list
    new_messages = [
        Message(role=cast(Literal["user", "assistant", "system"], m.role), content=m.content)
        for m in request.messages
    ]
    all_messages = context_messages + new_messages if context_messages else new_messages
    messages_dict = [{"role": m.role, "content": m.content} for m in all_messages]

    # Inject agent system prompt
    if agent_mandate_injection:
        temp_messages = [
            Message(
                role=cast(Literal["user", "assistant", "system"], m["role"]), content=m["content"]
            )
            for m in messages_dict
        ]
        temp_messages = inject_system_prompt_into_messages(
            temp_messages, agent_mandate_injection.system_content
        )
        messages_dict = [{"role": m.role, "content": m.content} for m in temp_messages]

    # Inject memory context
    memory_facts_injected = 0
    loaded_memory_uuids: list[str] = []
    if request.use_memory:
        scope, scope_id = parse_memory_group_id(request.memory_group_id)
        try:
            messages_dict, progressive_context = await inject_progressive_context(
                messages=messages_dict,
                scope=scope,
                scope_id=scope_id,
            )
            memory_facts_injected = (
                len(progressive_context.mandates)
                + len(progressive_context.guardrails)
                + len(progressive_context.reference)
            )
            loaded_memory_uuids = progressive_context.get_loaded_uuids()
            if memory_facts_injected > 0:
                await track_loaded_batch(loaded_memory_uuids)
                # Store memory injection event for observability
                if db:
                    await store_memory_inject_event(
                        db, session_id, loaded_memory_uuids, memory_facts_injected
                    )
        except Exception as e:
            logger.warning(f"Memory injection failed: {e}")

    # Check context window usage
    estimated_input_tokens = count_message_tokens(messages_dict)
    context_usage_info: ContextUsageInfo | None = None
    if db and session:
        can_proceed, ctx_usage = await check_context_before_request(
            db, session_id, resolved_model, estimated_input_tokens
        )
        if not can_proceed:
            raise HTTPException(
                status_code=413,
                detail=f"Context window limit exceeded ({ctx_usage.percent_used:.0%} used).",
            )
        context_usage_info = ContextUsageInfo(
            used_tokens=ctx_usage.used_tokens,
            limit_tokens=ctx_usage.limit_tokens,
            percent_used=ctx_usage.percent_used,
            remaining_tokens=ctx_usage.remaining_tokens,
            warning=ctx_usage.warning,
        )

    # Check response cache
    cache = get_response_cache()
    if not skip_cache:
        cached = await cache.get(
            model=resolved_model,
            messages=cast(list[dict[str, str]], messages_dict),
            temperature=request.temperature,
        )
        if cached:
            return await handle_cached_response(
                cached,
                db,
                session,
                session_id,
                request,
                resolved_model,
                context_usage_info,
                memory_facts_injected,
                is_new_session=is_new_session,
            )

    try:
        adapter = get_adapter(provider)
        thinking_level = request.thinking_level
        if request.auto_thinking and not thinking_level and should_enable_thinking(all_messages):
            thinking_level = "medium"

        # Convert tools to API format
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

        # Build response_format dict
        response_format_dict: dict[str, Any] | None = None
        if request.response_format:
            response_format_dict = {
                "type": request.response_format.type,
                "schema": request.response_format.schema_,
            }

        # Convert messages for adapter
        messages_for_adapter = [
            Message(
                role=cast(Literal["user", "assistant", "system"], m["role"]), content=m["content"]
            )
            for m in messages_dict
        ]

        # Execute completion with fallback chain if applicable
        # Note: fallback chain is single-turn only; agentic requests use complete_internal
        if resolved_agent and resolved_agent.agent.fallback_models and not is_agentic:
            fallback_result = await complete_with_fallback(
                messages=messages_for_adapter,
                agent=resolved_agent.agent,
                temperature=resolved_agent.agent.temperature,
                tools=tools_api,
            )
            result: CompletionResult = fallback_result.result
            model_used = fallback_result.model_used
            fallback_used = fallback_result.used_fallback
        else:
            # Use complete_internal for ALL completions (single-turn and multi-turn)
            if db:
                internal_result = await complete_internal(
                    messages=messages_dict,
                    model=resolved_model,
                    provider=provider,
                    temperature=request.temperature,
                    project_id=request.project_id,
                    db=db,
                    session_id=session_id,  # Use local var, not request.session_id
                    external_id=request.external_id,
                    client_id=client_id,
                    request_source=request_source,
                    agent_slug=request.agent_slug,
                    use_memory=False,  # Memory already injected above
                    memory_group_id=request.memory_group_id,
                    enable_caching=request.enable_caching,
                    cache_ttl=request.cache_ttl,
                    thinking_level=thinking_level,
                    tools=tools_api,
                    enable_programmatic_tools=request.enable_programmatic_tools,
                    container_id=request.container_id,
                    response_format=response_format_dict,
                    skip_cache=skip_cache,
                    user_messages_for_db=request.messages,
                    # Multi-turn parameters
                    max_turns=request.max_turns,
                    execute_tools=request.execute_tools,
                    working_dir=request.working_dir,
                    # Permission config: API param overrides agent config
                    permission_config=request.permission_config.model_dump()
                    if request.permission_config
                    else (resolved_agent.agent.tool_permissions if resolved_agent else None),
                    trace_id=request.trace_id,
                )

                # For multi-turn execution, return agentic response format
                if is_agentic:
                    from app.api.orchestration_models import AgentProgressInfo

                    return CompletionResponse(
                        content=internal_result.content,
                        model=internal_result.model,
                        provider=internal_result.provider,
                        usage=UsageInfo(
                            input_tokens=internal_result.input_tokens,
                            output_tokens=internal_result.output_tokens,
                            total_tokens=internal_result.input_tokens
                            + internal_result.output_tokens,
                            cache=None,
                        ),
                        context_usage=context_usage_info,
                        output_usage=None,
                        session_id=internal_result.session_id,
                        finish_reason="end_turn"
                        if internal_result.status == "success"
                        else internal_result.status,
                        from_cache=internal_result.from_cache,
                        thinking=ThinkingInfo(
                            content=internal_result.thinking_content or "",
                            tokens=internal_result.thinking_tokens,
                            level_used=thinking_level,
                        )
                        if internal_result.thinking_tokens
                        else None,
                        tool_calls=None,
                        container=ContainerInfo(
                            id=internal_result.container_id or "",
                            expires_at="",
                        )
                        if internal_result.container_id
                        else None,
                        memory_facts_injected=len(internal_result.memory_uuids),
                        memory_uuids=",".join(internal_result.memory_uuids)
                        if internal_result.memory_uuids
                        else None,
                        agent_used=agent_used,
                        model_used=internal_result.model,
                        fallback_used=fallback_used,
                        turns=internal_result.turns,
                        tool_calls_count=internal_result.tool_calls_count,
                        progress_log=[
                            AgentProgressInfo(
                                turn=p.turn,
                                status=p.status,
                                message=p.message,
                                tool_calls=p.tool_calls or [],
                                tool_results=p.tool_results or [],
                                thinking=p.thinking,
                            )
                            for p in internal_result.progress_log
                        ]
                        if internal_result.progress_log
                        else None,
                        trace_id=request.trace_id,
                        cited_uuids=internal_result.cited_uuids,
                    )

                # Single-turn response
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
            else:
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

        # Validate JSON schema if requested
        if (
            request.response_format
            and request.response_format.type == "json_object"
            and request.response_format.schema_
        ):
            is_valid, validation_error = validate_json_response(
                result.content, request.response_format.schema_
            )
            if not is_valid:
                raise HTTPException(
                    status_code=400,
                    detail=f"Model output does not match JSON schema: {validation_error}",
                )

        # Process and return result
        return await process_completion_result(
            result,
            request,
            resolved_model,
            session_id,
            db,
            session,
            skip_cache,
            messages_dict,
            context_usage_info,
            memory_facts_injected,
            loaded_memory_uuids,
            agent_used,
            model_used,
            fallback_used,
            is_new_session=is_new_session,
        )

    except ValueError as e:
        logger.error(f"Configuration error: {e}")
        if session_id:
            await publish_error(session_id, "ConfigurationError", str(e))
        raise HTTPException(status_code=500, detail=f"Configuration error: {e}") from e

    except RateLimitError as e:
        logger.warning(f"Rate limit for {e.provider}")
        if session_id:
            await publish_error(session_id, "RateLimitError", str(e))
        retry_after = str(int(e.retry_after)) if e.retry_after else "60"
        raise HTTPException(
            status_code=429,
            detail=f"Rate limit exceeded for {e.provider}. Wait {retry_after}s.",
            headers={"Retry-After": retry_after},
        ) from e

    except AuthenticationError as e:
        logger.error(f"Auth error for {e.provider}")
        if session_id:
            await publish_error(session_id, "AuthenticationError", str(e))
        env_var = "ANTHROPIC_API_KEY" if e.provider == "claude" else "GEMINI_API_KEY"
        raise HTTPException(
            status_code=401,
            detail=f"Authentication failed for {e.provider}. Verify {env_var}.",
        ) from e

    except ProviderError as e:
        logger.error(f"Provider error: {e}")
        if session_id:
            await publish_error(session_id, "ProviderError", str(e))
        raise HTTPException(status_code=e.status_code or 500, detail=str(e)) from e

    except HTTPException:
        raise

    except Exception as e:
        logger.exception(f"Unexpected error in /complete: {e}")
        if session_id:
            await publish_error(session_id, "UnexpectedError", str(e))
        raise HTTPException(status_code=500, detail="Internal server error.") from e


@router.post("/estimate", response_model=EstimateResponse)
async def estimate(request: EstimateRequest) -> EstimateResponse:
    """Estimate tokens and cost before making a completion request."""
    from app.constants import resolve_model

    resolved_model = resolve_model(request.model)
    messages_dict = [{"role": m.role, "content": m.content} for m in request.messages]
    estimate_result = estimate_request(
        messages=cast(list[dict[str, str]], messages_dict),
        model=resolved_model,
    )
    return EstimateResponse(
        input_tokens=estimate_result.input_tokens,
        estimated_output_tokens=estimate_result.estimated_output_tokens,
        total_tokens=estimate_result.total_tokens,
        estimated_cost_usd=estimate_result.estimated_cost_usd,
        context_limit=estimate_result.context_limit,
        context_usage_percent=estimate_result.context_usage_percent,
        context_warning=estimate_result.context_warning,
    )
