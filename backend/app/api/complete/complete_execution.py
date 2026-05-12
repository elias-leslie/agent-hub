"""Completion execution logic."""

from __future__ import annotations

import asyncio
import logging
from typing import Literal, cast

from sqlalchemy.ext.asyncio import AsyncSession

from app.api.complete.core import complete_internal
from app.api.complete.execution import (
    execute_with_fallback,
    execute_without_db,
    get_thinking_level,
    prepare_response_format,
    prepare_tools,
)
from app.api.complete.schemas import CompletionRequest
from app.api.complete.types import CompletionInternalResult
from app.services.agent_routing_models import ResolvedAgent
from app.services.llm_errors import ProviderError
from app.services.llm_messages import CompletionResult, Message

logger = logging.getLogger(__name__)

_NonAgenticResult = tuple[CompletionResult, str, bool, list[str], str | None, str | None]
_ToolsAPI = list[dict[str, object]] | None
_FmtDict = dict[str, object] | None
_MsgsDict = list[dict[str, object]]


def _fallbacks_enabled(req: CompletionRequest, agent: ResolvedAgent | None) -> bool:
    """Return whether agent fallback/escalation chain should be used for this request."""
    return bool(agent and agent.agent.fallback_models and not req.disable_agent_fallbacks)


def _to_messages(msgs: _MsgsDict) -> list[Message]:
    """Convert raw message dicts to Message objects."""
    return [Message(role=cast(Literal["user", "assistant", "system"], m["role"]), content=m["content"]) for m in msgs]


def _to_result(r: CompletionInternalResult, model: str, sid: str | None) -> _NonAgenticResult:
    """Wrap CompletionInternalResult as a non-agentic result tuple."""
    cr = CompletionResult(
        content=r.content, model=r.model, provider=r.provider,
        input_tokens=r.input_tokens, output_tokens=r.output_tokens,
        finish_reason=r.finish_reason, cache_metrics=r.cache_metrics,
        thinking_content=r.thinking_content, thinking_tokens=r.thinking_tokens,
        tool_calls=r.tool_calls, container=r.container,
    )
    return (cr, model, False, r.memory_uuids, r.session_id, r.fallback_reason)


def _agentic_timeout_seconds(agent: ResolvedAgent | None) -> float | None:
    """Return the per-turn timeout for agentic model calls.

    Returns None unless the agent row explicitly sets timeout_seconds.
    Open-ended agent turns are unbounded by default.
    """
    if agent is None:
        return None
    configured = getattr(agent.agent, "timeout_seconds", None)
    return float(configured) if configured is not None else None


async def _run_internal_with_timeout(
    req: CompletionRequest, model: str, provider: str, agent: ResolvedAgent | None,
    msgs: _MsgsDict, db: AsyncSession, sid: str | None, client_id: str | None,
    source: str | None, thinking: str | None, tools: _ToolsAPI, fmt: _FmtDict,
    skip_cache: bool, is_agentic: bool,
) -> CompletionInternalResult | _NonAgenticResult:
    """Run internal completion with the configured agentic model-turn timeout."""
    coro = _run_internal(
        req, model, provider, agent, msgs, db, sid, client_id, source,
        thinking, tools, fmt, skip_cache, is_agentic,
    )
    if not is_agentic:
        return await coro
    timeout = _agentic_timeout_seconds(agent)
    if timeout is None:
        return await coro
    try:
        return await asyncio.wait_for(coro, timeout=timeout)
    except TimeoutError as exc:
        raise TimeoutError(f"Agentic model turn timed out after {timeout:g}s") from exc


async def _run_internal(
    req: CompletionRequest, model: str, provider: str, agent: ResolvedAgent | None,
    msgs: _MsgsDict, db: AsyncSession, sid: str | None, client_id: str | None,
    source: str | None, thinking: str | None, tools: _ToolsAPI, fmt: _FmtDict,
    skip_cache: bool, is_agentic: bool,
) -> CompletionInternalResult | _NonAgenticResult:
    """Call complete_internal and return typed agentic result or non-agentic tuple."""
    internal = await complete_internal(
        messages=msgs, model=model, provider=provider, temperature=req.temperature,
        project_id=req.project_id, db=db, session_id=sid, external_id=req.external_id,
        client_id=client_id, request_source=source, parent_session_id=req.parent_session_id,
        agent_slug=req.agent_slug,
        use_memory=req.use_memory, memory_group_id=req.memory_group_id, enable_caching=req.enable_caching,
        cache_ttl=req.cache_ttl, thinking_level=thinking, tools=tools,
        enable_programmatic_tools=req.enable_programmatic_tools, container_id=req.container_id,
        response_format=fmt, skip_cache=skip_cache, user_messages_for_db=req.messages,
        max_turns=req.max_turns, execute_tools=req.execute_tools, working_dir=req.working_dir,
        trace_id=req.trace_id, task_type=req.task_type, phase=req.phase,
    )
    return internal if is_agentic else _to_result(internal, model, sid)


async def _run_with_agentic_fallback(
    req: CompletionRequest, primary_model: str, provider: str, agent: ResolvedAgent,
    msgs: _MsgsDict, db: AsyncSession, sid: str | None, client_id: str | None,
    source: str | None, thinking: str | None, tools: _ToolsAPI, fmt: _FmtDict,
    skip_cache: bool,
) -> CompletionInternalResult:
    """Try primary model then fallback_models for agentic DB execution."""
    from app.routing.registry import get_provider_for_model

    primary_error: ProviderError | asyncio.TimeoutError | None = None
    for model_id in [primary_model, *agent.agent.fallback_models]:
        try:
            fb_provider = get_provider_for_model(model_id) if model_id != primary_model else provider
            raw = await _run_internal_with_timeout(
                req, model_id, fb_provider, agent, msgs, db, sid, client_id, source,
                thinking, tools, fmt, skip_cache, True,
            )
            assert isinstance(raw, CompletionInternalResult)
            raw.requested_model = primary_model
            raw.requested_provider = provider
            if model_id != primary_model:
                logger.info("Agentic fallback succeeded: %s → %s", primary_model, model_id)
                raw.fallback_used = True
                raw.model_used = model_id
                raw.fallback_reason = f"{type(primary_error).__name__}: {primary_error}" if primary_error else None
            return raw
        except (TimeoutError, ProviderError) as e:
            if model_id == primary_model:
                primary_error = e
            logger.warning("Agentic execution failed for %s: %s — trying next fallback", model_id, e)

    if primary_error is None:
        raise RuntimeError("No models attempted in fallback chain")
    raise primary_error


async def _dispatch_db(
    req: CompletionRequest, model: str, provider: str, agent: ResolvedAgent | None,
    msgs: _MsgsDict, db: AsyncSession, is_agentic: bool, sid: str | None,
    client_id: str | None, source: str | None, thinking: str | None,
    tools: _ToolsAPI, fmt: _FmtDict, skip_cache: bool,
) -> CompletionInternalResult | _NonAgenticResult:
    """Route DB execution to fallback-aware or standard handler."""
    if is_agentic and _fallbacks_enabled(req, agent):
        return await _run_with_agentic_fallback(req, model, provider, agent, msgs, db, sid, client_id, source, thinking, tools, fmt, skip_cache)
    return await _run_internal_with_timeout(
        req, model, provider, agent, msgs, db, sid, client_id, source,
        thinking, tools, fmt, skip_cache, is_agentic,
    )


async def execute_completion(
    request: CompletionRequest,
    resolved_model: str,
    provider: str,
    resolved_agent: ResolvedAgent | None,
    messages_dict: _MsgsDict,
    all_messages: list[Message],
    is_agentic: bool,
    db: AsyncSession | None,
    session_id: str | None,
    client_id: str | None,
    request_source: str | None,
    skip_cache: bool,
) -> CompletionInternalResult | _NonAgenticResult:
    """Execute the completion request.

    Returns a CompletionInternalResult for agentic mode, or a
    (result, model_used, fallback_used, loaded_uuids, session_id) tuple otherwise.
    """
    thinking = get_thinking_level(request, all_messages, resolved_agent)
    tools = prepare_tools(request)
    fmt = prepare_response_format(request)
    if _fallbacks_enabled(request, resolved_agent) and not is_agentic:
        result, model_used, fallback_used = await execute_with_fallback(
            _to_messages(messages_dict), resolved_agent, tools, thinking,
            resolved_model=resolved_model,
            prompt_cache_key=session_id,
        )
        return (
            result,
            model_used,
            fallback_used,
            [],
            session_id,
            getattr(result, "fallback_reason", None),
        )
    if db is not None:
        if not is_agentic:
            result, model_used = await execute_without_db(
                _to_messages(messages_dict),
                resolved_model,
                provider,
                request,
                thinking,
                tools,
                fmt,
                session_id=session_id,
            )
            return (result, model_used, False, [], session_id, None)
        return await _dispatch_db(request, resolved_model, provider, resolved_agent, messages_dict, db, is_agentic, session_id, client_id, request_source, thinking, tools, fmt, skip_cache)
    result, model_used = await execute_without_db(
        _to_messages(messages_dict),
        resolved_model,
        provider,
        request,
        thinking,
        tools,
        fmt,
        session_id=session_id,
    )
    return (result, model_used, False, [], session_id, None)
