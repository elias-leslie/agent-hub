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
from app.api.complete import (
    CacheInfo,
    CompletionRequest,
    CompletionResponse,
    ContainerInfo,
    ContextUsageInfo,
    EstimateRequest,
    EstimateResponse,
    MessageInput,
    OutputUsageInfo,
    ThinkingInfo,
    ToolCallInfo,
    UsageInfo,
    complete_internal,
    get_adapter,
    get_or_create_session,
    get_provider,
    is_error_response,
    parse_mention,
    save_messages,
    should_enable_thinking,
    stream_completion,
    update_provider_metadata,
    validate_json_response,
)
from app.api.orchestration_models import AgentProgressInfo
from app.core.debug import debug, debug_async_timer
from app.db import get_db
from app.models import Session as DBSession
from app.models import TruncationEvent
from app.services.agent_routing import (
    complete_with_fallback,
    inject_agent_mandates,
    inject_system_prompt_into_messages,
    resolve_agent,
)
from app.services.context_tracker import (
    check_context_before_request,
    log_token_usage,
    should_emit_warning,
)
from app.services.events import publish_complete, publish_error, publish_message, publish_session_start
from app.services.memory import (
    extract_uuid_prefixes,
    inject_progressive_context,
    parse_memory_group_id,
    resolve_full_uuids,
    track_loaded_batch,
    track_referenced_batch,
)
from app.services.response_cache import get_response_cache
from app.services.token_counter import (
    build_output_usage,
    count_message_tokens,
    estimate_cost,
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
    """
    Generate a completion for the given messages.

    Routes to appropriate provider (Claude or Gemini) based on model name.
    Optionally persists messages to database for session continuity.

    Headers:
        X-Skip-Cache: Set to "true" to bypass response cache
    """
    # Validate: agent_slug is required (model parameter is deprecated)
    if not request.agent_slug:
        # Fetch available agents to include in error response
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
                    "agent_instructions": {
                        "severity": "MANDATORY",
                        "action": "STOP - Do not attempt to bypass or work around this restriction.",
                        "guidance": "If you need this access, ask the user to grant permissions via the Agent Hub dashboard or update the client's allowed_projects.",
                        "reason": "This access control exists to prevent unauthorized resource usage.",
                    },
                },
            )

    # DEBUG: Log incoming request details
    request_hash = hashlib.md5(
        f"{request.model or request.agent_slug}:{len(request.messages)}".encode()
    ).hexdigest()[:8]
    logger.info(
        f"DEBUG[{request_hash}] complete() called: model={request.model or 'via-agent'}, "
        f"agent_slug={request.agent_slug}, messages={len(request.messages)}, "
        f"project_id={request.project_id}"
    )
    if request.messages:
        first_msg = request.messages[0]
        logger.info(
            f"DEBUG[{request_hash}] First message: role={first_msg.role}, "
            f"content_len={len(first_msg.content)}, preview={first_msg.content[:100]}..."
        )

    # Agent routing state
    resolved_agent = None
    agent_mandate_injection = None
    agent_used: str | None = None
    model_used: str | None = None
    fallback_used = False

    # Check for agent-based routing first (takes priority)
    if request.agent_slug:
        if not db:
            raise HTTPException(
                status_code=400,
                detail="Database connection required for agent routing. agent_slug cannot be used without DB.",
            )
        resolved_agent = await resolve_agent(request.agent_slug, db)
        resolved_model = resolved_agent.model
        provider = resolved_agent.provider
        agent_used = resolved_agent.agent.slug

        # Set agent_slug on request.state for access control middleware logging
        http_request.state.agent_slug = request.agent_slug

        # Inject mandates (and global instructions if configured)
        agent_mandate_injection = await inject_agent_mandates(resolved_agent.agent, db)

        logger.info(
            f"DEBUG[{request_hash}] Agent routing: {request.agent_slug} -> "
            f"{resolved_model} ({provider}), mandates={len(agent_mandate_injection.injected_uuids)}"
        )
    else:
        # Resolve model alias to canonical name
        from app.constants import resolve_model

        # model is guaranteed to be set here (validated above)
        assert request.model is not None
        resolved_model = resolve_model(request.model)
        if resolved_model != request.model:
            logger.info(
                f"DEBUG[{request_hash}] Model resolved: {request.model} -> {resolved_model}"
            )
        provider = get_provider(resolved_model)
    skip_cache = bool(x_skip_cache and x_skip_cache.lower() == "true")

    # Check for @mention routing in the last user message (takes priority over header selection)
    mentioned_model = None
    if request.messages:
        last_user_msg = next((m for m in reversed(request.messages) if m.role == "user"), None)
        if last_user_msg:
            mentioned_model, _ = parse_mention(last_user_msg.content)
            if mentioned_model:
                logger.info(f"DEBUG[{request_hash}] @mention routing: {mentioned_model}")
                resolved_model = mentioned_model
                provider = get_provider(resolved_model)

    # Handle streaming mode
    if request.stream:
        session_id = request.session_id or str(uuid.uuid4())

        # Create session for streaming (mirrors non-streaming path)
        client_id = getattr(http_request.state, "client_id", None)
        request_source = getattr(http_request.state, "request_source", None)
        stream_context_messages: list[Message] = []
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
            logger.info(
                f"DEBUG[{request_hash}] Streaming: session={session_id}, new={is_new_session}"
            )

        # Build message list: context + new messages (mirrors non-streaming path)
        new_messages = [
            Message(role=cast(Literal["user", "assistant", "system"], m.role), content=m.content)
            for m in request.messages
        ]
        messages_for_streaming = (
            stream_context_messages + new_messages if stream_context_messages else new_messages
        )

        # Inject agent system prompt if using agent routing
        if agent_mandate_injection:
            messages_for_streaming = inject_system_prompt_into_messages(
                messages_for_streaming, agent_mandate_injection.system_content
            )
            logger.info(
                f"DEBUG[{request_hash}] Streaming: injected agent system prompt "
                f"(mandates={len(agent_mandate_injection.injected_uuids)})"
            )

        logger.info(
            f"DEBUG[{request_hash}] Starting SSE stream: model={resolved_model}, "
            f"agent={agent_used}, session={session_id}"
        )

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
                **({"X-Agent-Used": agent_used} if agent_used else {}),
                **({"X-Model-Used": model_used or resolved_model} if model_used else {}),
                **({"X-Fallback-Used": "true"} if fallback_used else {}),
            },
        )

    # Handle agentic execution mode (when max_turns > 1 or execute_tools=True)
    if request.max_turns > 1 or request.execute_tools:
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

    # Get or create session if persistence is enabled
    session: DBSession | None = None
    context_messages: list[Message] = []
    session_id = request.session_id or str(uuid.uuid4())

    # Always create sessions - no opt-out
    is_new_session = False
    # Extract client info from request.state (set by AccessControlMiddleware)
    client_id = getattr(http_request.state, "client_id", None)
    request_source = getattr(http_request.state, "request_source", None)
    logger.debug(
        f"DEBUG[{request_hash}] client_id from request.state: {client_id}, "
        f"request_source: {request_source}"
    )
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
        # Publish session_start event for new sessions
        if is_new_session:
            await publish_session_start(session_id, resolved_model, request.project_id)

    # Build full message list: context + new messages
    new_messages = [
        Message(role=cast(Literal["user", "assistant", "system"], m.role), content=m.content)
        for m in request.messages
    ]

    # If we have context, only send the last user message as new
    all_messages = context_messages + new_messages if context_messages else new_messages

    messages_dict = [{"role": m.role, "content": m.content} for m in all_messages]

    # Inject agent system prompt and mandates if agent_slug was provided
    if agent_mandate_injection:
        # Convert dict messages to Message objects for injection, then back
        temp_messages = [
            Message(
                role=cast(Literal["user", "assistant", "system"], m["role"]),
                content=m["content"],
            )
            for m in messages_dict
        ]
        temp_messages = inject_system_prompt_into_messages(
            temp_messages, agent_mandate_injection.system_content
        )
        messages_dict = [{"role": m.role, "content": m.content} for m in temp_messages]
        logger.info(
            f"DEBUG[{request_hash}] Injected agent system prompt "
            f"(mandates={len(agent_mandate_injection.injected_uuids)})"
        )

    # Inject memory context if enabled (using progressive disclosure)
    memory_facts_injected = 0
    loaded_memory_uuids: list[str] = []
    if request.use_memory:
        memory_group = request.memory_group_id
        scope, scope_id = parse_memory_group_id(memory_group)
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
                logger.info(
                    f"DEBUG[{request_hash}] Injected {memory_facts_injected} memory facts (scope={scope.value})"
                )
                # Track loaded memories asynchronously
                await track_loaded_batch(loaded_memory_uuids)
        except Exception as e:
            logger.warning(f"Memory injection failed (continuing without): {e}")

    # Check context window usage before proceeding
    estimated_input_tokens = count_message_tokens(messages_dict)
    context_usage_info: ContextUsageInfo | None = None
    if db and session:
        can_proceed, ctx_usage = await check_context_before_request(
            db, session_id, resolved_model, estimated_input_tokens
        )
        if not can_proceed:
            raise HTTPException(
                status_code=413,
                detail=(
                    f"Context window limit exceeded ({ctx_usage.percent_used:.0%} used). "
                    "Start a new session or reduce conversation history."
                ),
            )
        context_usage_info = ContextUsageInfo(
            used_tokens=ctx_usage.used_tokens,
            limit_tokens=ctx_usage.limit_tokens,
            percent_used=ctx_usage.percent_used,
            remaining_tokens=ctx_usage.remaining_tokens,
            warning=ctx_usage.warning,
        )
        if should_emit_warning(ctx_usage.percent_used):
            logger.warning(f"Session {session_id}: {ctx_usage.warning}")

    # Check response cache first (unless bypassed)
    cache = get_response_cache()
    if not skip_cache:
        cached = await cache.get(
            model=resolved_model,
            messages=cast(list[dict[str, str]], messages_dict),
            temperature=request.temperature,
        )
        if cached:
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

    try:
        # Get adapter
        adapter = get_adapter(provider)

        # Determine thinking level
        thinking_level = request.thinking_level
        if request.auto_thinking and not thinking_level and should_enable_thinking(all_messages):
            # Auto-detect complex requests and enable thinking
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

        # Use agent fallback chain if agent routing is enabled
        if resolved_agent and resolved_agent.agent.fallback_models:
            # Determine effective temperature (agent config takes precedence)
            effective_temperature = resolved_agent.agent.temperature

            fallback_result = await complete_with_fallback(
                messages=messages_for_adapter,
                agent=resolved_agent.agent,
                temperature=effective_temperature,
                tools=tools_api,
            )
            # Build a CompletionResult from the fallback result
            result: CompletionResult = fallback_result.result
            model_used = fallback_result.model_used
            fallback_used = fallback_result.used_fallback
            if fallback_used:
                logger.info(f"DEBUG[{request_hash}] Agent fallback used: {model_used}")
        else:
            # Use complete_internal for simple completions (no tools, no special features)
            if (
                not tools_api
                and not request.enable_programmatic_tools
                and not response_format_dict
                and db
            ):
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
                # Convert internal result to CompletionResult for unified handling
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
                # Track citations from internal result
                loaded_memory_uuids = internal_result.memory_uuids
                # Session was already created by complete_internal
                session_id = internal_result.session_id
            else:
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

        # Validate JSON response against schema if structured output was requested
        if (
            request.response_format
            and request.response_format.type == "json_object"
            and request.response_format.schema_
        ):
            is_valid, validation_error = validate_json_response(
                result.content, request.response_format.schema_
            )
            if not is_valid:
                logger.warning(f"JSON response validation failed: {validation_error}")
                raise HTTPException(
                    status_code=400,
                    detail=f"Model output does not match the provided JSON schema: {validation_error}",
                )

        # Cache the response for future identical requests (but NOT errors)
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
            # Estimate thinking cost (thinking tokens count as input tokens)
            thinking_cost = None
            if result.thinking_tokens:
                cost_estimate = estimate_cost(result.thinking_tokens, 0, resolved_model)
                thinking_cost = cost_estimate.input_cost_usd

            thinking_info = ThinkingInfo(
                content=result.thinking_content,
                tokens=result.thinking_tokens,
                level_used=thinking_level,
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
                # Extract citation prefixes from response
                cited_prefixes = extract_uuid_prefixes(result.content)
                if cited_prefixes:
                    # Resolve prefixes to full UUIDs
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

    except ValueError as e:
        # API key not configured
        logger.error(f"Configuration error: {e}")
        if session_id:
            await publish_error(session_id, "ConfigurationError", str(e))
        raise HTTPException(
            status_code=500,
            detail=f"Configuration error: {e}. Check environment variables (ANTHROPIC_API_KEY, GEMINI_API_KEY).",
        ) from e

    except RateLimitError as e:
        logger.warning(f"Rate limit for {e.provider}")
        if session_id:
            await publish_error(session_id, "RateLimitError", str(e))
        retry_after = str(int(e.retry_after)) if e.retry_after else "60"
        raise HTTPException(
            status_code=429,
            detail=(
                f"Rate limit exceeded for {e.provider}. "
                f"Wait {retry_after}s before retrying. Consider using prompt caching (enable_caching: true)."
            ),
            headers={"Retry-After": retry_after},
        ) from e

    except AuthenticationError as e:
        logger.error(f"Auth error for {e.provider}")
        if session_id:
            await publish_error(session_id, "AuthenticationError", str(e))
        env_var = "ANTHROPIC_API_KEY" if e.provider == "claude" else "GEMINI_API_KEY"
        raise HTTPException(
            status_code=401,
            detail=f"Authentication failed for {e.provider}. Verify {env_var} is set and valid.",
        ) from e

    except ProviderError as e:
        logger.error(f"Provider error: {e}")
        if session_id:
            await publish_error(session_id, "ProviderError", str(e))
        status_code = e.status_code or 500
        detail = str(e)
        if e.retriable:
            detail += " This error may be transient; retry may succeed."
        raise HTTPException(status_code=status_code, detail=detail) from e

    except HTTPException:
        # Let HTTPExceptions pass through (e.g., JSON validation 400 errors)
        raise

    except Exception as e:
        logger.exception(f"Unexpected error in /complete: {e}")
        if session_id:
            await publish_error(session_id, "UnexpectedError", str(e))
        raise HTTPException(
            status_code=500,
            detail="Internal server error. Check logs for details.",
        ) from e


@router.post("/estimate", response_model=EstimateResponse)
async def estimate(request: EstimateRequest) -> EstimateResponse:
    """
    Estimate tokens and cost before making a completion request.

    Returns token counts, estimated cost, and context limit warnings.
    """
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
