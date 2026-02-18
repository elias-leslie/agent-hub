"""Completion orchestration logic."""

from __future__ import annotations

import hashlib
import logging
import time
from typing import TYPE_CHECKING, Any

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
from app.api.complete.schemas import CompletionRequest, CompletionResponse, ContextUsageInfo
from app.api.complete.streaming_handlers import handle_streaming_request
from app.api.complete.validation import validate_agent_slug, validate_project_access
from app.services.preferences import get_global_tier_preference, resolve_tier_preference

if TYPE_CHECKING:
    from fastapi import Request

    from app.models import Session as DBSession
    from app.services.agent_routing import MandateInjection as AgentMandateInjection
    from app.services.agent_routing import ResolvedAgent

logger = logging.getLogger(__name__)


def _log_and_hash_request(request: CompletionRequest) -> str:
    """Create request hash and log start."""
    rh = hashlib.md5(
        f"{request.model or request.agent_slug}:{len(request.messages)}".encode()
    ).hexdigest()[:8]
    logger.debug(
        f"DEBUG[{rh}] complete() called: model={request.model or 'via-agent'}, "
        f"agent_slug={request.agent_slug}, messages={len(request.messages)}"
    )
    return rh


async def _validate_and_resolve(
    request: CompletionRequest, http_request: Request, db: AsyncSession | None
) -> tuple[str, str | None, str | None, str, str, ResolvedAgent | None, AgentMandateInjection | None, str | None]:
    """Validate request and resolve model/agent; return resolution tuple."""
    await validate_agent_slug(request, db)
    validate_project_access(request, getattr(http_request.state, "allowed_projects", None))
    if request.async_execution and request.stream:
        raise HTTPException(status_code=400, detail="Cannot combine async_execution with stream mode.")
    rh = _log_and_hash_request(request)
    client_id = getattr(http_request.state, "client_id", None)
    request_source = getattr(http_request.state, "request_source", None)
    global_pref = await get_global_tier_preference(db) if db else None
    tier_pref = resolve_tier_preference(request.tier_preference, global_pref)
    logger.debug(f"DEBUG[{rh}] Using tier preference: {tier_pref.value}")
    resolved_model, provider, resolved_agent, agent_mandate_injection, agent_used = (
        await resolve_agent_and_model(request, db, rh)
    )
    http_request.state.agent_slug = request.agent_slug
    resolved_model, provider = apply_mention_override(request, resolved_model)
    return rh, client_id, request_source, resolved_model, provider, resolved_agent, agent_mandate_injection, agent_used


async def _build_session_and_messages(
    request: CompletionRequest,
    provider: str,
    resolved_model: str,
    resolved_agent: ResolvedAgent | None,
    mandate: AgentMandateInjection | None,
    db: AsyncSession | None,
    client_id: str | None,
    source: str | None,
    skip_cache: bool,
) -> tuple[bool, str, DBSession | None, bool, list[Any], list[Any], int, list[str], ContextUsageInfo | None, Any]:
    """Set up session, build messages, inject memory, check cache."""
    is_agentic = request.max_turns > 1 or request.execute_tools
    session_id, session, ctx_msgs, is_new_session = await setup_session(
        request, provider, resolved_model, db, client_id, source
    )
    all_messages, messages_dict = build_message_list(request, ctx_msgs)
    messages_dict = inject_agent_system_prompt(messages_dict, mandate)
    messages_dict, memory_facts_injected, loaded_memory_uuids = await inject_memory(
        request, messages_dict, session_id, resolved_agent, db
    )
    context_usage_info = await check_context_limits(db, session, session_id, resolved_model, messages_dict)
    cached = await check_cache(skip_cache, resolved_model, messages_dict, request.temperature)
    return is_agentic, session_id, session, is_new_session, all_messages, messages_dict, memory_facts_injected, loaded_memory_uuids, context_usage_info, cached


async def _process_result(
    request: CompletionRequest, result: Any, resolved_model: str, session_id: str,
    db: AsyncSession | None, session: DBSession | None, skip_cache: bool,
    messages_dict: list[Any], ctx_info: ContextUsageInfo | None, memory_facts: int,
    loaded_uuids_in: list[str], agent_used: str | None, is_new_session: bool, duration_ms: int,
) -> CompletionResponse | JSONResponse:
    """Unpack result, validate JSON schema, and finalize response."""
    if isinstance(result, tuple):
        cr, model_used, fallback_used, loaded_uuids, sid = result
    else:
        cr, model_used, fallback_used = result, resolved_model, False
        loaded_uuids, sid = loaded_uuids_in, session_id
    rf = request.response_format
    if rf and rf.type == "json_object" and rf.schema_:
        is_valid, err = validate_json_response(cr.content, rf.schema_)
        if not is_valid:
            raise HTTPException(status_code=400, detail=f"Model output does not match JSON schema: {err}")
    return await process_completion_result(
        cr, request, resolved_model, sid, db, session, skip_cache, messages_dict,
        ctx_info, memory_facts, loaded_uuids, agent_used,
        model_used, fallback_used, is_new_session=is_new_session,
        external_id=request.external_id, duration_ms=duration_ms,
    )


async def _execute_and_respond(
    request: CompletionRequest, resolved_model: str, provider: str,
    resolved_agent: ResolvedAgent | None, messages_dict: list[Any], all_messages: list[Any],
    is_agentic: bool, db: AsyncSession | None, session: DBSession | None, session_id: str,
    client_id: str | None, source: str | None, skip_cache: bool,
    ctx_info: ContextUsageInfo | None, memory_facts: int, loaded_uuids_in: list[str],
    agent_used: str | None, is_new_session: bool,
) -> CompletionResponse | JSONResponse:
    """Execute completion and build response."""
    try:
        t0 = time.monotonic()
        result = await execute_completion(
            request=request, resolved_model=resolved_model, provider=provider,
            resolved_agent=resolved_agent, messages_dict=messages_dict,
            all_messages=all_messages, is_agentic=is_agentic, db=db,
            session_id=session_id, client_id=client_id,
            request_source=source, skip_cache=skip_cache,
        )
        duration_ms = int((time.monotonic() - t0) * 1000)
        if is_agentic and hasattr(result, "turns"):
            return build_agentic_response(
                result, ctx_info, get_thinking_level(request, all_messages),
                agent_used, False, request.trace_id,
            )
        return await _process_result(
            request, result, resolved_model, session_id, db, session, skip_cache,
            messages_dict, ctx_info, memory_facts, loaded_uuids_in, agent_used, is_new_session, duration_ms,
        )
    except Exception as e:
        await handle_completion_error(
            e, session_id, db=db, agent_id=request.agent_slug, model_used=resolved_model,
        )
        raise  # handle_completion_error is NoReturn but ty needs explicit raise


async def orchestrate_completion(
    request: CompletionRequest,
    http_request: Request,
    skip_cache: bool,
    db: AsyncSession | None,
) -> CompletionResponse | StreamingResponse | JSONResponse:
    """Orchestrate a completion request through the entire pipeline."""
    rh, client_id, source, resolved_model, provider, resolved_agent, mandate, agent_used = (
        await _validate_and_resolve(request, http_request, db)
    )
    if request.stream:
        return await handle_streaming_request(
            request=request, resolved_model=resolved_model, provider=provider,
            resolved_agent=resolved_agent, agent_mandate_injection=mandate,
            agent_used=agent_used, model_used=None, fallback_used=False, db=db,
            client_id=client_id, request_source=source,
        )
    is_agentic, session_id, session, is_new_session, all_messages, messages_dict, memory_facts, loaded_uuids, ctx_info, cached = (
        await _build_session_and_messages(request, provider, resolved_model, resolved_agent, mandate, db, client_id, source, skip_cache)
    )
    if cached:
        return await handle_cached_response(
            cached, db, session, session_id, request, resolved_model,
            ctx_info, memory_facts, is_new_session=is_new_session,
        )
    if is_agentic and request.async_execution:
        return await dispatch_async_completion(
            request=request, messages_dict=messages_dict, resolved_model=resolved_model,
            provider=provider, session_id=session_id, resolved_agent=resolved_agent,
            all_messages=all_messages, skip_cache=skip_cache,
            client_id=client_id, request_source=source,
        )
    if is_agentic:
        logger.debug(
            f"DEBUG[{rh}] Agentic mode: max_turns={request.max_turns}, "
            f"execute_tools={request.execute_tools}, working_dir={request.working_dir}"
        )
    return await _execute_and_respond(
        request, resolved_model, provider, resolved_agent, messages_dict, all_messages,
        is_agentic, db, session, session_id, client_id, source, skip_cache,
        ctx_info, memory_facts, loaded_uuids, agent_used, is_new_session,
    )
