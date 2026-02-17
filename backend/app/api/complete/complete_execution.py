"""Completion execution logic."""

from __future__ import annotations

from typing import Any, Literal, cast

from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.base import CompletionResult, Message
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
