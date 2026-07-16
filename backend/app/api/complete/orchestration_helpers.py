"""Sub-orchestration helpers extracted from complete_orchestrator."""

from __future__ import annotations

import asyncio
import time
from contextlib import suppress
from typing import TYPE_CHECKING, Any

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.complete.complete_execution import execute_completion
from app.api.complete.error_handlers import handle_completion_error
from app.api.complete.execution import get_thinking_level
from app.api.complete.handlers import process_completion_result
from app.api.complete.helpers import validate_json_response
from app.api.complete.request_setup import (
    build_message_list,
    check_cache,
    check_context_limits,
    compact_context_if_needed,
    inject_memory,
    setup_session,
)
from app.api.complete.schemas import CompletionRequest, CompletionResponse, ContextUsageInfo
from app.routing.resolution import inject_agent_system_prompt

if TYPE_CHECKING:
    from fastapi import Request
    from fastapi.responses import JSONResponse

    from app.models import Session as DBSession
    from app.services.agent_routing import MandateInjection as AgentMandateInjection
    from app.services.agent_routing import ResolvedAgent

# Type alias for the session-build return value
_SessionResult = tuple[bool, str, "DBSession | None", bool, list[Any], list[Any], int, list[str], ContextUsageInfo | None, Any]


async def build_session_and_messages(
    request: CompletionRequest,
    provider: str,
    resolved_model: str,
    resolved_agent: ResolvedAgent | None,
    mandate: AgentMandateInjection | None,
    db: AsyncSession | None,
    client_id: str | None,
    source: str | None,
    skip_cache: bool,
) -> _SessionResult:
    """Set up session, build messages, inject memory, check cache."""
    is_agentic = request.max_turns > 1 or request.execute_tools
    session_id, session, ctx_msgs, is_new_session = await setup_session(
        request, provider, resolved_model, db, client_id, source
    )
    all_messages, messages_dict = build_message_list(request, ctx_msgs)
    messages_dict, memory_facts_injected, loaded_memory_uuids = await inject_memory(
        request, messages_dict, session_id, resolved_agent, db
    )
    # Canonical operator context precedes agent-specific prompt/persona layers.
    messages_dict = inject_agent_system_prompt(messages_dict, mandate)
    messages_dict, _was_compacted = await compact_context_if_needed(
        db, session_id, resolved_model, messages_dict
    )
    context_usage_info = await check_context_limits(db, session, session_id, resolved_model, messages_dict)
    cached = await check_cache(skip_cache, resolved_model, messages_dict, request.temperature)
    return (
        is_agentic, session_id, session, is_new_session,
        all_messages, messages_dict, memory_facts_injected, loaded_memory_uuids,
        context_usage_info, cached,
    )


async def process_result(
    request: CompletionRequest, result: Any, resolved_model: str, session_id: str,
    db: AsyncSession | None, session: DBSession | None, skip_cache: bool,
    messages_dict: list[Any], ctx_info: ContextUsageInfo | None, memory_facts: int,
    loaded_uuids_in: list[str], agent_used: str | None, is_new_session: bool, duration_ms: int,
    resolved_agent: ResolvedAgent | None,
    effective_thinking_level: str | None = None,
) -> CompletionResponse | JSONResponse:
    """Unpack result, validate JSON schema, and finalize response."""
    if isinstance(result, tuple):
        cr, model_used, fallback_used, loaded_uuids, sid, fallback_reason = result
        if not loaded_uuids:
            loaded_uuids = loaded_uuids_in
    else:
        cr = result
        model_used = getattr(result, "model_used", None) or resolved_model
        fallback_used = bool(getattr(result, "fallback_used", False))
        loaded_uuids = loaded_uuids_in
        sid = session_id
        fallback_reason = getattr(result, "fallback_reason", None)
    rf = request.response_format
    if rf and rf.type == "json_object" and rf.schema_:
        is_valid, err = validate_json_response(cr.content, rf.schema_)
        if not is_valid:
            raise HTTPException(status_code=400, detail=f"Model output does not match JSON schema: {err}")
    response = await process_completion_result(
        cr, request, resolved_model, sid, db, session, skip_cache, messages_dict,
        ctx_info, memory_facts, loaded_uuids, agent_used,
        model_used, fallback_used, fallback_reason, is_new_session=is_new_session,
        external_id=request.external_id, duration_ms=duration_ms,
        effective_thinking_level=effective_thinking_level,
    )
    return response


def _record_fallback_on_request(http_request: Request | None, result: Any) -> None:
    """Attach fallback metadata to http_request.state for middleware logging."""
    if http_request is None:
        return
    if isinstance(result, tuple):
        _cr, model_used, fallback_used, _uuids, _sid, _fallback_reason = result
        if fallback_used:
            http_request.state.used_fallback = True
            http_request.state.fallback_model = model_used
    elif hasattr(result, "model_used") and hasattr(result, "fallback_used"):
        if result.fallback_used:
            http_request.state.used_fallback = True
            http_request.state.fallback_model = result.model_used


async def _rollback_db(db: AsyncSession | None) -> None:
    """Attempt a DB rollback, suppressing any error."""
    if db is not None:
        with suppress(Exception):
            await db.rollback()


async def _run_completion(
    request: CompletionRequest, resolved_model: str, provider: str,
    resolved_agent: ResolvedAgent | None, messages_dict: list[Any], all_messages: list[Any],
    is_agentic: bool, db: AsyncSession | None, session_id: str,
    client_id: str | None, source: str | None, skip_cache: bool,
    ctx_info: ContextUsageInfo | None, memory_facts: int, loaded_uuids_in: list[str],
    agent_used: str | None, is_new_session: bool, session: DBSession | None,
    http_request: Request | None,
) -> tuple[Any, int, str | None]:
    """Execute completion and return (result, duration_ms, effective_thinking_level)."""
    t0 = time.monotonic()
    result = await execute_completion(
        request=request, resolved_model=resolved_model, provider=provider,
        resolved_agent=resolved_agent, messages_dict=messages_dict,
        all_messages=all_messages, is_agentic=is_agentic, db=db,
        session_id=session_id, client_id=client_id,
        request_source=source, skip_cache=skip_cache,
    )
    duration_ms = int((time.monotonic() - t0) * 1000)
    _record_fallback_on_request(http_request, result)
    effective_thinking_level = get_thinking_level(request, all_messages, resolved_agent)
    return result, duration_ms, effective_thinking_level


async def execute_and_respond(
    request: CompletionRequest, resolved_model: str, provider: str,
    resolved_agent: ResolvedAgent | None, messages_dict: list[Any], all_messages: list[Any],
    is_agentic: bool, db: AsyncSession | None, session: DBSession | None, session_id: str,
    client_id: str | None, source: str | None, skip_cache: bool,
    ctx_info: ContextUsageInfo | None, memory_facts: int, loaded_uuids_in: list[str],
    agent_used: str | None, is_new_session: bool,
    http_request: Request | None = None,
) -> CompletionResponse | JSONResponse:
    """Execute completion and build response."""
    try:
        result, duration_ms, effective_thinking_level = await _run_completion(
            request, resolved_model, provider, resolved_agent, messages_dict, all_messages,
            is_agentic, db, session_id, client_id, source, skip_cache,
            ctx_info, memory_facts, loaded_uuids_in, agent_used, is_new_session, session,
            http_request,
        )
        return await process_result(
            request, result, resolved_model, session_id, db, session, skip_cache,
            messages_dict, ctx_info, memory_facts, loaded_uuids_in, agent_used, is_new_session, duration_ms,
            resolved_agent,
            effective_thinking_level=effective_thinking_level,
        )
    except asyncio.CancelledError as e:
        await _rollback_db(db)
        await handle_completion_error(e, session_id, db=db, agent_id=request.agent_slug, model_used=resolved_model)
        raise
    except TimeoutError as e:
        await _rollback_db(db)
        if http_request is not None:
            http_request.state.timed_out = True
        await handle_completion_error(e, session_id, db=db, agent_id=request.agent_slug, model_used=resolved_model)
        raise  # handle_completion_error is NoReturn but ty needs explicit raise
    except Exception as e:
        await _rollback_db(db)
        await handle_completion_error(e, session_id, db=db, agent_id=request.agent_slug, model_used=resolved_model)
        raise  # handle_completion_error is NoReturn but ty needs explicit raise
