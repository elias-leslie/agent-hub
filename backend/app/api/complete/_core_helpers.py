"""Internal helpers for core completion orchestration."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.response_cache import get_response_cache

from .cache_handler import handle_cached_response
from .helpers import get_adapter
from .memory_handler import inject_memory_context
from .multi_turn_executor import execute_multi_turn
from .result_builder import build_completion_result
from .result_finalizer import finalize_completion_result
from .schemas import MessageInput
from .tool_handlers import AgentProgress
from .tool_provisioner import provision_standard_tools
from .tool_router import route_tool_execution
from .types import CompletionInternalResult

logger = logging.getLogger(__name__)


@dataclass
class _ExecContext:
    """Shared execution context to avoid long argument lists in private helpers."""

    provider: str
    messages_dict: list[dict[str, Any]]
    user_messages_for_db: list[MessageInput]
    model: str
    temperature: float
    db: AsyncSession
    session: Any
    session_id: str
    is_new_session: bool
    loaded_memory_uuids: list[str]
    memory_group_id: str | None
    skip_cache: bool
    progress_callback: Callable[[AgentProgress], Any] | None
    max_turns: int
    project_id: str
    tools: list[dict[str, Any]] | None = None
    tool_catalog: list[dict[str, Any]] | None = None
    working_dir: str | None = None
    permission_config: dict[str, Any] | None = None
    enable_programmatic_tools: bool = False
    defer_tool_loading: bool = False
    enable_caching: bool = True
    cache_ttl: str = "ephemeral"
    thinking_level: str | None = None
    container_id: str | None = None
    response_format: dict[str, Any] | None = None
    agent_slug: str | None = None


async def check_memory_and_cache(
    *,
    messages_dict: list[dict[str, Any]],
    model: str,
    temperature: float,
    use_memory: bool,
    memory_group_id: str | None,
    task_type: str | None,
    phase: str | None,
    memory_config: dict[str, Any] | None,
    current_branch: str | None,
    agent_slug: str | None,
    skip_cache: bool,
    db: AsyncSession,
    session: Any,
    session_id: str,
    user_messages_for_db: list[MessageInput],
    is_new_session: bool,
) -> tuple[list[dict[str, Any]], list[str], CompletionInternalResult | None]:
    """Inject memory and check cache. Returns (messages, memory_uuids, cached_result_or_None)."""
    loaded_memory_uuids: list[str] = []
    if use_memory:
        messages_dict, loaded_memory_uuids, _ = await inject_memory_context(
            messages_dict, db, session_id, memory_group_id, task_type, phase,
            memory_config, current_branch=current_branch, agent_id=agent_slug,
        )

    cache = get_response_cache()
    if not skip_cache:
        cached = await cache.get(model=model, messages=messages_dict, temperature=temperature)
        if cached:
            cache_result = await handle_cached_response(
                cached, db, session, session_id, model, user_messages_for_db,
                loaded_memory_uuids, is_new_session, agent_id=agent_slug,
            )
            return messages_dict, loaded_memory_uuids, CompletionInternalResult(**cache_result)

    return messages_dict, loaded_memory_uuids, None


async def _route_to_tool_executor(ctx: _ExecContext) -> CompletionInternalResult:
    """Execute via the tool router and return the result."""
    # Claude SDK manages turns internally; other providers need at least 2 turns
    # (one for the tool call, one after tool results).
    effective_max_turns = ctx.max_turns if ctx.provider == "claude" else max(ctx.max_turns, 5)
    tool_result_dict = await route_tool_execution(
        provider=ctx.provider, messages_dict=ctx.messages_dict,
        user_messages_for_db=ctx.user_messages_for_db, model=ctx.model,
        temperature=ctx.temperature, tools=ctx.tools, tool_catalog=ctx.tool_catalog,
        working_dir=ctx.working_dir,
        permission_config=ctx.permission_config, db=ctx.db, session=ctx.session,
        session_id=ctx.session_id, is_new_session=ctx.is_new_session,
        loaded_memory_uuids=ctx.loaded_memory_uuids, memory_group_id=ctx.memory_group_id,
        skip_cache=ctx.skip_cache, progress_callback=ctx.progress_callback,
        max_turns=effective_max_turns, project_id=ctx.project_id,
    )
    return CompletionInternalResult(**tool_result_dict)


async def _run_multi_turn(ctx: _ExecContext) -> dict[str, Any]:
    """Invoke execute_multi_turn and return the raw result dict."""
    cache = get_response_cache()
    return await execute_multi_turn(
        adapter=get_adapter(ctx.provider), messages_dict=ctx.messages_dict,
        model=ctx.model, provider=ctx.provider, temperature=ctx.temperature,
        max_turns=ctx.max_turns, enable_caching=ctx.enable_caching,
        cache_ttl=ctx.cache_ttl, thinking_level=ctx.thinking_level,
        tools=ctx.tools, enable_programmatic_tools=ctx.enable_programmatic_tools,
        container_id=ctx.container_id, response_format=ctx.response_format,
        working_dir=ctx.working_dir, db=ctx.db, session_id=ctx.session_id,
        user_messages_for_db=ctx.user_messages_for_db, skip_cache=ctx.skip_cache,
        cache=cache, loaded_memory_uuids=ctx.loaded_memory_uuids,
        memory_group_id=ctx.memory_group_id, progress_callback=ctx.progress_callback,
        agent_slug=ctx.agent_slug,
    )


async def _finalize_and_build(
    ctx: _ExecContext, exec_result: dict[str, Any],
) -> CompletionInternalResult:
    """Finalize the session record and build the CompletionInternalResult."""
    final_result = exec_result["final_result"]
    effective_model = getattr(final_result, "model_used", None) or ctx.model
    await finalize_completion_result(
        ctx.db, ctx.session, ctx.session_id, ctx.model, effective_model,
        exec_result["total_input_tokens"], exec_result["total_output_tokens"],
        ctx.is_new_session, final_result,
        project_id=ctx.project_id,
        fallback_used=bool(getattr(final_result, "fallback_used", False)),
        fallback_reason=getattr(final_result, "fallback_reason", None),
    )
    result_dict = build_completion_result(
        final_content=exec_result["final_content"], model=ctx.model, provider=ctx.provider,
        total_input_tokens=exec_result["total_input_tokens"],
        total_output_tokens=exec_result["total_output_tokens"],
        final_finish_reason=exec_result["final_finish_reason"],
        final_session_id=ctx.session_id, loaded_memory_uuids=ctx.loaded_memory_uuids,
        cited_uuids_list=exec_result["cited_uuids_list"],
        total_thinking_tokens=exec_result["total_thinking_tokens"],
        tool_calls_count=exec_result["tool_calls_count"],
        execution_status=exec_result["execution_status"],
        execution_error=exec_result["execution_error"],
        current_container_id=exec_result["current_container_id"],
        progress_log=exec_result["progress_log"],
        final_result=final_result,
    )
    return CompletionInternalResult(**result_dict)


async def execute_and_build_result(
    *,
    provider: str, model: str, temperature: float, project_id: str,
    messages_dict: list[dict[str, Any]], user_messages_for_db: list[MessageInput],
    tools: list[dict[str, Any]] | None, working_dir: str | None,
    permission_config: dict[str, Any] | None,
    db: AsyncSession, session: Any, session_id: str, is_new_session: bool,
    loaded_memory_uuids: list[str], memory_group_id: str | None, skip_cache: bool,
    progress_callback: Callable[[AgentProgress], Any] | None, max_turns: int,
    execute_tools: bool, enable_programmatic_tools: bool,
    defer_tool_loading: bool,
    enable_caching: bool, cache_ttl: str, thinking_level: str | None,
    container_id: str | None, response_format: dict[str, Any] | None,
    agent_slug: str | None,
) -> CompletionInternalResult:
    """Route to tool execution or multi-turn, then finalize and return result."""
    from .tool_router import supports_tools

    provisioned = provision_standard_tools(
        execute_tools,
        tools,
        agent_slug=agent_slug,
        project_id=project_id,
        defer_tool_loading=defer_tool_loading,
    )
    ctx = _ExecContext(
        provider=provider, messages_dict=messages_dict,
        user_messages_for_db=user_messages_for_db, model=model,
        temperature=temperature, tools=provisioned.loaded_tools,
        tool_catalog=provisioned.catalog_tools, working_dir=working_dir,
        permission_config=permission_config, db=db, session=session,
        session_id=session_id, is_new_session=is_new_session,
        loaded_memory_uuids=loaded_memory_uuids, memory_group_id=memory_group_id,
        skip_cache=skip_cache, progress_callback=progress_callback,
        max_turns=max_turns, project_id=project_id,
        enable_programmatic_tools=enable_programmatic_tools,
        defer_tool_loading=defer_tool_loading,
        enable_caching=enable_caching, cache_ttl=cache_ttl,
        thinking_level=thinking_level, container_id=container_id,
        response_format=response_format, agent_slug=agent_slug,
    )

    should_execute_tools = (execute_tools or enable_programmatic_tools) and bool(provisioned.loaded_tools)
    if should_execute_tools and supports_tools(provider, model):
        return await _route_to_tool_executor(ctx)

    exec_result = await _run_multi_turn(ctx)
    return await _finalize_and_build(ctx, exec_result)
