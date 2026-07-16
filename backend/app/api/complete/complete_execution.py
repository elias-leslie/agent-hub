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
from app.services.llm_messages import Message
from app.services.model_runtime_health import (
    record_model_runtime_failure,
    record_model_runtime_success,
)

logger = logging.getLogger(__name__)

_NonAgenticResult = tuple[CompletionInternalResult, str, bool, list[str], str | None, str | None]
_ToolsAPI = list[dict[str, object]] | None
_FmtDict = dict[str, object] | None
_MsgsDict = list[dict[str, object]]


# Codex auth death fires on every call once the refresh token is burned, so
# alert at most once per cooldown window instead of per request.
_CODEX_ALERT_COOLDOWN_S = 6 * 3600
_codex_alert_at = 0.0


async def _alert_codex_auth_dead(db: AsyncSession, model_id: str, error: Exception) -> None:
    """Send a one-per-cooldown Telegram alert when the Codex OAuth chain dies.

    Without this, refresh-token death silently degrades every call to fallback
    models (observed 2026-06: five days of MiniMax answering persona chat).
    """
    from app.adapters.codex_auth import CodexAuthError

    if not isinstance(error, CodexAuthError):
        return

    global _codex_alert_at
    import time

    now = time.monotonic()
    if _codex_alert_at and now - _codex_alert_at < _CODEX_ALERT_COOLDOWN_S:
        return
    _codex_alert_at = now

    try:
        from app.services.telegram_delivery import send_configured_report

        await send_configured_report(
            db=db,
            title="Codex OAuth dead — action needed",
            body=(
                f"Codex token refresh is failing ({error}); all {model_id} traffic is "
                "running on fallback models until re-authenticated.\n\n"
                "Fix: Agent Hub → Settings → LLM Providers → Codex → Re-auth.\n"
                "Details: wiki page codex-oauth-token-rotation."
            ),
        )
    except Exception:
        logger.exception("Failed to send Codex auth alert")


def _fallbacks_enabled(req: CompletionRequest, agent: ResolvedAgent | None) -> bool:
    """Return whether agent fallback/escalation chain should be used for this request."""
    return bool(agent and agent.agent.fallback_models and not req.disable_agent_fallbacks)


def _to_messages(msgs: _MsgsDict) -> list[Message]:
    """Convert raw message dicts to Message objects."""
    return [Message(role=cast(Literal["user", "assistant", "system"], m["role"]), content=m["content"]) for m in msgs]


def _to_result(r: CompletionInternalResult, model: str, sid: str | None) -> _NonAgenticResult:
    """Wrap CompletionInternalResult as a non-agentic result tuple."""
    return (r, model, False, r.memory_uuids, r.session_id or sid, r.fallback_reason)


def _terminal_error_from_result(result: CompletionInternalResult) -> RuntimeError | None:
    if result.finish_reason not in {"error", "aborted"}:
        return None
    message = result.message.error_message or f"Provider returned finish_reason={result.finish_reason}"
    return RuntimeError(message)


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
        canonical_context_preinjected=True,
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

    primary_error: ProviderError | RuntimeError | asyncio.TimeoutError | None = None
    for model_id in [primary_model, *agent.agent.fallback_models]:
        try:
            fb_provider = get_provider_for_model(model_id) if model_id != primary_model else provider
            raw = await _run_internal(
                req, model_id, fb_provider, agent, msgs, db, sid, client_id, source,
                thinking, tools, fmt, skip_cache, True,
            )
            assert isinstance(raw, CompletionInternalResult)
            terminal_error = _terminal_error_from_result(raw)
            if terminal_error is not None:
                raise terminal_error
            raw.requested_model = primary_model
            raw.requested_provider = provider
            if model_id != primary_model:
                logger.info("Agentic fallback succeeded: %s → %s", primary_model, model_id)
                raw.fallback_used = True
                raw.model_used = model_id
                raw.fallback_reason = f"{type(primary_error).__name__}: {primary_error}" if primary_error else None
            await record_model_runtime_success(db, model_id=model_id, provider=fb_provider)
            return raw
        except (TimeoutError, ProviderError, RuntimeError) as e:
            await record_model_runtime_failure(db, model_id=model_id, provider=fb_provider, error=e)
            if model_id == primary_model:
                primary_error = e
            logger.warning("Agentic execution failed for %s: %s — trying next fallback", model_id, e)
            await _alert_codex_auth_dead(db, model_id, e)

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
    return await _run_internal(
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
    visible_tool_names = None
    if getattr(request, "execute_tools", False) and request.project_id:
        from app.services.project_permission_service import get_visible_tools_for_project

        visible_tool_names = await get_visible_tools_for_project(request.project_id, db)
    tools = prepare_tools(request, visible_tool_names=visible_tool_names)
    fmt = prepare_response_format(request)
    if _fallbacks_enabled(request, resolved_agent) and not is_agentic:
        result, model_used, fallback_used = await execute_with_fallback(
            _to_messages(messages_dict),
            resolved_agent,
            tools,
            thinking,
            resolved_model=resolved_model,
            prompt_cache_key=session_id,
            db=db,
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
