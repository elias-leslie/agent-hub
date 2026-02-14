"""Completion orchestration logic."""

from __future__ import annotations

import hashlib
import logging
import time
from typing import TYPE_CHECKING

from fastapi import HTTPException
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.complete.async_dispatch import dispatch_async_completion
from app.api.complete.complete_execution import execute_completion
from app.api.complete.error_handlers import handle_completion_error
from app.api.complete.execution import build_agentic_response, get_thinking_level
from app.api.complete.handlers import handle_cached_response, process_completion_result
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
from app.services.preferences import get_global_tier_preference, resolve_tier_preference

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
    allowed_projects = getattr(http_request.state, "allowed_projects", None)
    validate_project_access(request, allowed_projects)

    if request.async_execution and request.stream:
        raise HTTPException(status_code=400, detail="Cannot combine async_execution with stream mode.")

    # Initialize context
    request_hash = _log_and_hash_request(request)
    client_id = getattr(http_request.state, "client_id", None)
    request_source = getattr(http_request.state, "request_source", None)

    # Resolve tier preference (request > global > default)
    global_preference = await get_global_tier_preference(db) if db else None
    tier_preference = resolve_tier_preference(request.tier_preference, global_preference)
    logger.info(f"DEBUG[{request_hash}] Using tier preference: {tier_preference.value}")

    # Resolve agent and model
    resolved_model, provider, resolved_agent, agent_mandate_injection, agent_used = (
        await resolve_agent_and_model(request, db, request_hash)
    )
    http_request.state.agent_slug = request.agent_slug
    resolved_model, provider = apply_mention_override(request, resolved_model)

    # Handle streaming mode
    if request.stream:
        return await handle_streaming_request(
            request=request, resolved_model=resolved_model, provider=provider,
            resolved_agent=resolved_agent, agent_mandate_injection=agent_mandate_injection,
            agent_used=agent_used, model_used=None, fallback_used=False, db=db,
            client_id=client_id, request_source=request_source,
        )

    # Setup session and messages
    is_agentic = request.max_turns > 1 or request.execute_tools
    if is_agentic:
        logger.info(
            f"DEBUG[{request_hash}] Agentic mode: max_turns={request.max_turns}, "
            f"execute_tools={request.execute_tools}, working_dir={request.working_dir}"
        )

    session_id, session, context_messages, is_new_session = await setup_session(
        request, provider, resolved_model, db, client_id, request_source
    )
    all_messages, messages_dict = build_message_list(request, context_messages)
    messages_dict = inject_agent_system_prompt(messages_dict, agent_mandate_injection)

    # Inject memory and check context
    messages_dict, memory_facts_injected, loaded_memory_uuids = await inject_memory(
        request, messages_dict, session_id, resolved_agent, db
    )
    context_usage_info = await check_context_limits(
        db, session, session_id, resolved_model, messages_dict
    )

    # Check cache
    cached = await check_cache(skip_cache, resolved_model, messages_dict, request.temperature)
    if cached:
        return await handle_cached_response(
            cached, db, session, session_id, request, resolved_model,
            context_usage_info, memory_facts_injected, is_new_session=is_new_session,
        )

    # Handle async dispatch
    if is_agentic and request.async_execution:
        return await dispatch_async_completion(
            request=request, messages_dict=messages_dict, resolved_model=resolved_model,
            provider=provider, session_id=session_id, resolved_agent=resolved_agent,
            all_messages=all_messages, skip_cache=skip_cache,
            client_id=client_id, request_source=request_source,
        )

    # Execute completion
    try:
        completion_start = time.monotonic()
        result = await execute_completion(
            request=request, resolved_model=resolved_model, provider=provider,
            resolved_agent=resolved_agent, messages_dict=messages_dict,
            all_messages=all_messages, is_agentic=is_agentic, db=db,
            session_id=session_id, client_id=client_id,
            request_source=request_source, skip_cache=skip_cache,
        )
        completion_duration_ms = int((time.monotonic() - completion_start) * 1000)

        # Handle agentic response
        if is_agentic and hasattr(result, "turns"):
            return build_agentic_response(
                result, context_usage_info, get_thinking_level(request, all_messages),
                agent_used, False, request.trace_id,
            )

        # Extract result data
        if isinstance(result, tuple):
            completion_result, model_used, fallback_used, loaded_uuids, session_id_result = result
        else:
            completion_result, model_used, fallback_used = result, resolved_model, False
            loaded_uuids, session_id_result = loaded_memory_uuids, session_id

        # Validate JSON schema if required
        if request.response_format and request.response_format.type == "json_object" and request.response_format.schema_:
            is_valid, validation_error = validate_json_response(
                completion_result.content, request.response_format.schema_
            )
            if not is_valid:
                raise HTTPException(
                    status_code=400,
                    detail=f"Model output does not match JSON schema: {validation_error}",
                )

        # Process and return
        return await process_completion_result(
            completion_result, request, resolved_model, session_id_result, db, session,
            skip_cache, messages_dict, context_usage_info, memory_facts_injected,
            loaded_uuids, agent_used, model_used, fallback_used,
            is_new_session=is_new_session, external_id=request.external_id,
            duration_ms=completion_duration_ms,
        )

    except Exception as e:
        await handle_completion_error(
            e, session_id, db=db,
            agent_id=request.agent_slug, model_used=resolved_model,
        )


def _log_and_hash_request(request: CompletionRequest) -> str:
    """Create request hash and log start."""
    request_hash = hashlib.md5(
        f"{request.model or request.agent_slug}:{len(request.messages)}".encode()
    ).hexdigest()[:8]
    logger.info(
        f"DEBUG[{request_hash}] complete() called: model={request.model or 'via-agent'}, "
        f"agent_slug={request.agent_slug}, messages={len(request.messages)}"
    )
    return request_hash
