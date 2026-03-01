"""Completion execution logic."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Literal, cast

from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.base import CompletionResult, Message, ProviderError
from app.api.complete.core import complete_internal
from app.api.complete.execution import (
    execute_with_fallback,
    execute_without_db,
    get_thinking_level,
    prepare_response_format,
    prepare_tools,
)
from app.api.complete.schemas import CompletionRequest
from app.services.agent_routing_models import ResolvedAgent

logger = logging.getLogger(__name__)


def _build_messages_for_adapter(messages_dict: list[dict[str, Any]]) -> list[Message]:
    """Convert raw message dicts to Message adapter objects."""
    return [
        Message(role=cast(Literal["user", "assistant", "system"], m["role"]), content=m["content"])
        for m in messages_dict
    ]


def _build_completion_result(internal_result: Any) -> CompletionResult:
    """Convert an internal complete_internal result to a CompletionResult."""
    return CompletionResult(
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


def _resolve_permission_config(
    request: CompletionRequest,
    resolved_agent: ResolvedAgent | None,
) -> Any:
    """Resolve permission_config from request or agent fallback."""
    if request.permission_config:
        return request.permission_config.model_dump()
    return resolved_agent.agent.tool_permissions if resolved_agent else None


async def _call_complete_internal(
    request: CompletionRequest,
    resolved_model: str,
    provider: str,
    resolved_agent: ResolvedAgent | None,
    messages_dict: list[dict[str, Any]],
    db: AsyncSession,
    session_id: str | None,
    client_id: str | None,
    request_source: str | None,
    thinking_level: str | None,
    tools_api: list[Any] | None,
    response_format_dict: dict[str, Any] | None,
    skip_cache: bool,
) -> Any:
    """Invoke complete_internal with all resolved parameters."""
    return await complete_internal(
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
        permission_config=_resolve_permission_config(request, resolved_agent),
        trace_id=request.trace_id,
        task_type=request.task_type,
        phase=request.phase,
        timeout_seconds=request.timeout_seconds,
    )


async def _execute_via_db(
    request: CompletionRequest,
    resolved_model: str,
    provider: str,
    resolved_agent: ResolvedAgent | None,
    messages_dict: list[dict[str, Any]],
    is_agentic: bool,
    db: AsyncSession,
    session_id: str | None,
    client_id: str | None,
    request_source: str | None,
    thinking_level: str | None,
    tools_api: list[Any] | None,
    response_format_dict: dict[str, Any] | None,
    skip_cache: bool,
) -> tuple[CompletionResult, str, bool, list[str], str | None] | Any:
    """Execute via complete_internal (DB path)."""
    internal_result = await _call_complete_internal(
        request=request,
        resolved_model=resolved_model,
        provider=provider,
        resolved_agent=resolved_agent,
        messages_dict=messages_dict,
        db=db,
        session_id=session_id,
        client_id=client_id,
        request_source=request_source,
        thinking_level=thinking_level,
        tools_api=tools_api,
        response_format_dict=response_format_dict,
        skip_cache=skip_cache,
    )
    if is_agentic:
        return internal_result
    result = _build_completion_result(internal_result)
    return (result, resolved_model, False, internal_result.memory_uuids, internal_result.session_id)


async def _execute_via_db_with_fallback(
    request: CompletionRequest,
    resolved_model: str,
    provider: str,
    resolved_agent: ResolvedAgent,
    messages_dict: list[dict[str, Any]],
    db: AsyncSession,
    session_id: str | None,
    client_id: str | None,
    request_source: str | None,
    thinking_level: str | None,
    tools_api: list[Any] | None,
    response_format_dict: dict[str, Any] | None,
    skip_cache: bool,
) -> Any:
    """Execute agentic DB path with fallback retry on ProviderError.

    Tries the primary model first, then iterates through fallback_models,
    swapping model/provider for each retry while preserving the full
    agentic pipeline (multi-turn, tools, memory).
    """
    from app.adapters.registry import get_provider_for_model

    models_to_try = [resolved_model, *resolved_agent.agent.fallback_models]
    last_error: ProviderError | asyncio.TimeoutError | None = None

    for model_id in models_to_try:
        try:
            fb_provider = get_provider_for_model(model_id) if model_id != resolved_model else provider
            result = await _execute_via_db(
                request=request, resolved_model=model_id, provider=fb_provider,
                resolved_agent=resolved_agent, messages_dict=messages_dict,
                is_agentic=True, db=db, session_id=session_id,
                client_id=client_id, request_source=request_source,
                thinking_level=thinking_level, tools_api=tools_api,
                response_format_dict=response_format_dict, skip_cache=skip_cache,
            )
            if model_id != resolved_model:
                logger.info("Agentic fallback succeeded: %s → %s", resolved_model, model_id)
                if not isinstance(result, tuple) and hasattr(result, "fallback_used"):
                    result.fallback_used = True
                    result.model_used = model_id
            return result
        except (TimeoutError, ProviderError) as e:
            last_error = e
            logger.warning("Agentic execution failed for %s: %s — trying next fallback", model_id, e)
            continue

    raise last_error  # type: ignore[misc]


async def execute_completion(
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
    thinking_level = get_thinking_level(request, all_messages, resolved_agent)
    tools_api = prepare_tools(request)
    response_format_dict = prepare_response_format(request)
    messages_for_adapter = _build_messages_for_adapter(messages_dict)

    if resolved_agent and resolved_agent.agent.fallback_models and not is_agentic:
        result, model_used, fallback_used = await execute_with_fallback(
            messages_for_adapter, resolved_agent, tools_api, thinking_level
        )
        return (result, model_used, fallback_used, [], session_id)

    if db:
        if is_agentic and resolved_agent and resolved_agent.agent.fallback_models:
            return await _execute_via_db_with_fallback(
                request=request, resolved_model=resolved_model, provider=provider,
                resolved_agent=resolved_agent, messages_dict=messages_dict,
                db=db, session_id=session_id,
                client_id=client_id, request_source=request_source,
                thinking_level=thinking_level, tools_api=tools_api,
                response_format_dict=response_format_dict, skip_cache=skip_cache,
            )
        return await _execute_via_db(
            request=request, resolved_model=resolved_model, provider=provider,
            resolved_agent=resolved_agent, messages_dict=messages_dict,
            is_agentic=is_agentic, db=db, session_id=session_id,
            client_id=client_id, request_source=request_source,
            thinking_level=thinking_level, tools_api=tools_api,
            response_format_dict=response_format_dict, skip_cache=skip_cache,
        )

    result, model_used = await execute_without_db(
        messages_for_adapter, resolved_model, provider, request,
        thinking_level, tools_api, response_format_dict,
    )
    return (result, model_used, False, [], session_id)
