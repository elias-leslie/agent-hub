"""Completion orchestration logic."""

from __future__ import annotations

import hashlib
import logging
from typing import TYPE_CHECKING, Any, Literal, cast

from fastapi import HTTPException
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.base import CompletionResult, Message
from app.api.complete.async_dispatch import dispatch_async_completion
from app.api.complete.core import complete_internal
from app.api.complete.error_handlers import handle_completion_error
from app.api.complete.execution import (
    build_agentic_response,
    execute_with_fallback,
    execute_without_db,
    get_thinking_level,
    prepare_response_format,
    prepare_tools,
)
from app.api.complete.handlers import (
    handle_cached_response,
    process_completion_result,
)
from app.api.complete.helpers import validate_json_response
from app.api.complete.request_setup import (
    build_message_list,
    check_cache,
    check_context_limits,
    inject_memory,
    setup_session,
)
from app.api.complete.resolution import (
    apply_mention_override,
    inject_agent_system_prompt,
    resolve_agent_and_model,
)
from app.api.complete.schemas import CompletionRequest, CompletionResponse
from app.api.complete.streaming_handlers import handle_streaming_request
from app.api.complete.validation import validate_agent_slug, validate_project_access
from app.services.agent_routing_models import ResolvedAgent

if TYPE_CHECKING:
    from fastapi import Request

logger = logging.getLogger(__name__)


async def orchestrate_completion(
    request: CompletionRequest,
    http_request: Request,
    skip_cache: bool,
    db: AsyncSession | None,
) -> CompletionResponse | StreamingResponse | JSONResponse:
    """Orchestrate a completion request through the entire pipeline.

    Args:
        request: The completion request
        http_request: The FastAPI request object
        skip_cache: Whether to skip response caching
        db: Database session

    Returns:
        Completion response, streaming response, or JSON response
    """
    # Validate request
    await validate_agent_slug(request, db)
    client = getattr(http_request.state, "client", None)
    validate_project_access(request, client)

    # DEBUG logging
    request_hash = hashlib.md5(
        f"{request.model or request.agent_slug}:{len(request.messages)}".encode()
    ).hexdigest()[:8]
    logger.info(
        f"DEBUG[{request_hash}] complete() called: model={request.model or 'via-agent'}, "
        f"agent_slug={request.agent_slug}, messages={len(request.messages)}"
    )

    # Validate async+stream early (contradictory options)
    if request.async_execution and request.stream:
        raise HTTPException(
            status_code=400,
            detail="Cannot combine async_execution with stream mode.",
        )

    # Resolve agent and model
    resolved_model, provider, resolved_agent, agent_mandate_injection, agent_used = (
        await resolve_agent_and_model(request, db, request_hash)
    )
    http_request.state.agent_slug = request.agent_slug
    model_used: str | None = None
    fallback_used = False

    # Apply @mention override
    resolved_model, provider = apply_mention_override(request, resolved_model)

    # Handle streaming mode
    if request.stream:
        return await handle_streaming_request(
            request=request,
            resolved_model=resolved_model,
            provider=provider,
            resolved_agent=resolved_agent,
            agent_mandate_injection=agent_mandate_injection,
            agent_used=agent_used,
            model_used=model_used,
            fallback_used=fallback_used,
            db=db,
            client_id=getattr(http_request.state, "client_id", None),
            request_source=getattr(http_request.state, "request_source", None),
        )

    # Handle agentic execution mode
    is_agentic = request.max_turns > 1 or request.execute_tools
    if is_agentic:
        logger.info(
            f"DEBUG[{request_hash}] Agentic mode: max_turns={request.max_turns}, "
            f"execute_tools={request.execute_tools}, working_dir={request.working_dir}"
        )

    # Setup session and build message list
    client_id = getattr(http_request.state, "client_id", None)
    request_source = getattr(http_request.state, "request_source", None)
    session_id, session, context_messages, is_new_session = await setup_session(
        request, provider, resolved_model, db, client_id, request_source
    )
    all_messages, messages_dict = build_message_list(request, context_messages)

    # Inject agent system prompt
    messages_dict = inject_agent_system_prompt(messages_dict, agent_mandate_injection)

    # Inject memory context
    messages_dict, memory_facts_injected, loaded_memory_uuids = await inject_memory(
        request, messages_dict, session_id, resolved_agent, db
    )

    # Check context window usage
    context_usage_info = await check_context_limits(
        db, session, session_id, resolved_model, messages_dict
    )

    # Check response cache
    cached = await check_cache(skip_cache, resolved_model, messages_dict, request.temperature)
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

    # Async dispatch: enqueue to Hatchet worker for parallel execution
    if is_agentic and request.async_execution:
        return await dispatch_async_completion(
            request=request,
            messages_dict=messages_dict,
            resolved_model=resolved_model,
            provider=provider,
            session_id=session_id,
            resolved_agent=resolved_agent,
            all_messages=all_messages,
            skip_cache=skip_cache,
            client_id=client_id,
            request_source=request_source,
        )

    try:
        result = await _execute_completion(
            request=request,
            resolved_model=resolved_model,
            provider=provider,
            resolved_agent=resolved_agent,
            messages_dict=messages_dict,
            all_messages=all_messages,
            is_agentic=is_agentic,
            db=db,
            session_id=session_id,
            client_id=client_id,
            request_source=request_source,
            skip_cache=skip_cache,
        )

        # For agentic mode, return agentic response format
        if is_agentic and hasattr(result, "turns"):
            return build_agentic_response(
                result, context_usage_info, get_thinking_level(request, all_messages),
                agent_used, fallback_used, request.trace_id,
            )

        # Extract data from result tuple or object
        if isinstance(result, tuple):
            completion_result, model_used_result, fallback_used_result, loaded_uuids, session_id_result = result
            model_used = model_used_result
            fallback_used = fallback_used_result
            loaded_memory_uuids = loaded_uuids
            session_id = session_id_result
        else:
            completion_result = result
            model_used = resolved_model

        # Validate JSON schema if requested
        if request.response_format and request.response_format.type == "json_object" and request.response_format.schema_:
            is_valid, validation_error = validate_json_response(
                completion_result.content, request.response_format.schema_
            )
            if not is_valid:
                raise HTTPException(
                    status_code=400,
                    detail=f"Model output does not match JSON schema: {validation_error}",
                )

        # Process and return result
        return await process_completion_result(
            completion_result,
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
            external_id=request.external_id,
        )

    except Exception as e:
        await handle_completion_error(e, session_id)


async def _execute_completion(
    request: CompletionRequest,
    resolved_model: str,
    provider: str,
    resolved_agent: ResolvedAgent | None,
    messages_dict: list[dict[str, Any]],
    all_messages: list[Any],
    is_agentic: bool,
    db: AsyncSession | None,
    session_id: str | None,
    client_id: str | None,
    request_source: str | None,
    skip_cache: bool,
) -> tuple[CompletionResult, str, bool, list[str], str | None] | Any:
    """Execute the completion request.

    Returns either a tuple (result, model_used, fallback_used, loaded_uuids, session_id)
    or an internal result object for agentic mode.
    """
    thinking_level = get_thinking_level(request, all_messages)
    tools_api = prepare_tools(request)
    response_format_dict = prepare_response_format(request)

    messages_for_adapter = [
        Message(role=cast(Literal["user", "assistant", "system"], m["role"]), content=m["content"])
        for m in messages_dict
    ]

    # Execute with fallback chain
    if resolved_agent and resolved_agent.agent.fallback_models and not is_agentic:
        result, model_used, fallback_used = await execute_with_fallback(
            messages_for_adapter, resolved_agent, tools_api
        )
        return (result, model_used, fallback_used, [], session_id)

    # Execute via complete_internal (DB path)
    if db:
        internal_result = await complete_internal(
            messages=messages_dict,
            model=resolved_model,
            provider=provider,
            temperature=request.temperature,
            project_id=request.project_id,
            db=db,
            session_id=session_id,
            external_id=request.external_id,
            client_id=client_id,
            request_source=request_source,
            agent_slug=request.agent_slug,
            use_memory=False,
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
            max_turns=request.max_turns,
            execute_tools=request.execute_tools,
            working_dir=request.working_dir,
            permission_config=request.permission_config.model_dump()
            if request.permission_config
            else (resolved_agent.agent.tool_permissions if resolved_agent else None),
            trace_id=request.trace_id,
            task_type=request.task_type,
            phase=request.phase,
        )

        # For agentic mode, return internal result directly
        if is_agentic:
            return internal_result

        # Convert to CompletionResult for single-turn
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
        return (result, resolved_model, False, internal_result.memory_uuids, internal_result.session_id)

    # Execute without DB
    result, model_used = await execute_without_db(
        messages_for_adapter, resolved_model, provider, request,
        thinking_level, tools_api, response_format_dict,
    )
    return (result, model_used, False, [], session_id)
