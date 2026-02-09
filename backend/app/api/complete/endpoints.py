"""Completion API endpoint."""

from __future__ import annotations

import hashlib
import logging
from typing import TYPE_CHECKING, Annotated, Literal, cast

from fastapi import APIRouter, Depends, Header, HTTPException, Request
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
from app.api.complete.schemas import (
    CompletionRequest,
    CompletionResponse,
    EstimateRequest,
    EstimateResponse,
)
from app.api.complete.streaming_handlers import handle_streaming_request
from app.api.complete.validation import validate_agent_slug, validate_project_access
from app.db import get_db
from app.services.agent_routing import inject_agent_mandates, resolve_agent  # noqa: F401
from app.services.event_storage import store_memory_inject_event  # noqa: F401
from app.services.events import publish_session_start  # noqa: F401
from app.services.response_cache import get_response_cache  # noqa: F401
from app.services.token_counter import estimate_request

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
) -> CompletionResponse | StreamingResponse | JSONResponse:
    """Generate a completion for the given messages.

    Routes to appropriate provider (Claude or Gemini) based on model name.
    Optionally persists messages to database for session continuity.

    Headers:
        X-Skip-Cache: Set to "true" to bypass response cache
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

    # Resolve agent and model
    resolved_model, provider, resolved_agent, agent_mandate_injection, agent_used = (
        await resolve_agent_and_model(request, db, request_hash)
    )
    http_request.state.agent_slug = request.agent_slug
    model_used: str | None = None
    fallback_used = False

    # Apply @mention override
    resolved_model, provider = apply_mention_override(request, resolved_model)

    skip_cache = bool(x_skip_cache and x_skip_cache.lower() == "true")

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
        # Prepare execution parameters
        thinking_level = get_thinking_level(request, all_messages)
        tools_api = prepare_tools(request)
        response_format_dict = prepare_response_format(request)
        messages_for_adapter = [
            Message(role=cast(Literal["user", "assistant", "system"], m["role"]), content=m["content"])
            for m in messages_dict
        ]

        # Execute completion with fallback chain or via complete_internal
        if resolved_agent and resolved_agent.agent.fallback_models and not is_agentic:
            result, model_used, fallback_used = await execute_with_fallback(
                messages_for_adapter, resolved_agent, tools_api
            )
        elif db:
            internal_result = await complete_internal(
                messages=messages_dict, model=resolved_model, provider=provider,
                temperature=request.temperature, project_id=request.project_id, db=db,
                session_id=session_id, external_id=request.external_id, client_id=client_id,
                request_source=request_source, agent_slug=request.agent_slug, use_memory=False,
                memory_group_id=request.memory_group_id, enable_caching=request.enable_caching,
                cache_ttl=request.cache_ttl, thinking_level=thinking_level, tools=tools_api,
                enable_programmatic_tools=request.enable_programmatic_tools,
                container_id=request.container_id, response_format=response_format_dict,
                skip_cache=skip_cache, user_messages_for_db=request.messages,
                max_turns=request.max_turns, execute_tools=request.execute_tools,
                working_dir=request.working_dir,
                permission_config=request.permission_config.model_dump()
                if request.permission_config
                else (resolved_agent.agent.tool_permissions if resolved_agent else None),
                trace_id=request.trace_id, task_type=request.task_type, phase=request.phase,
            )

            # For multi-turn execution, return agentic response format
            if is_agentic:
                return build_agentic_response(
                    internal_result, context_usage_info, thinking_level,
                    agent_used, fallback_used, request.trace_id,
                )

            # Single-turn response - convert internal result
            result = CompletionResult(
                content=internal_result.content, model=internal_result.model,
                provider=internal_result.provider, input_tokens=internal_result.input_tokens,
                output_tokens=internal_result.output_tokens, finish_reason=internal_result.finish_reason,
                cache_metrics=internal_result.cache_metrics, thinking_content=internal_result.thinking_content,
                thinking_tokens=internal_result.thinking_tokens, tool_calls=internal_result.tool_calls,
                container=internal_result.container,
            )
            model_used = resolved_model
            loaded_memory_uuids = internal_result.memory_uuids
            session_id = internal_result.session_id
        else:
            result, model_used = await execute_without_db(
                messages_for_adapter, resolved_model, provider, request,
                thinking_level, tools_api, response_format_dict,
            )

        # Validate JSON schema if requested
        if request.response_format and request.response_format.type == "json_object" and request.response_format.schema_:
            is_valid, validation_error = validate_json_response(result.content, request.response_format.schema_)
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
            external_id=request.external_id,
        )

    except Exception as e:
        await handle_completion_error(e, session_id)


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
