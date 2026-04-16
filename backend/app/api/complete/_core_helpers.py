"""Internal helpers for core completion orchestration."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.response_cache import get_response_cache

from .agent_loop import AgentLoopRequest, execute_agent_loop
from .cache_handler import handle_cached_response
from .memory_handler import inject_memory_context
from .precision_search_guidance import maybe_inject_claude_tool_alias_guidance
from .schemas import MessageInput
from .tool_handlers import AgentProgress
from .tool_provisioner import provision_standard_tools
from .types import CompletionInternalResult

logger = logging.getLogger(__name__)


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

async def execute_and_build_result(
    *,
    provider: str, model: str, temperature: float, project_id: str,
    messages_dict: list[dict[str, Any]], user_messages_for_db: list[MessageInput],
    tools: list[dict[str, Any]] | None, working_dir: str | None,
    db: AsyncSession, session: Any, session_id: str, is_new_session: bool,
    loaded_memory_uuids: list[str], memory_group_id: str | None, skip_cache: bool,
    progress_callback: Callable[[AgentProgress], Any] | None, max_turns: int,
    execute_tools: bool, enable_programmatic_tools: bool,
    defer_tool_loading: bool,
    enable_caching: bool, cache_ttl: str, thinking_level: str | None,
    container_id: str | None, response_format: dict[str, Any] | None,
    agent_slug: str | None, task_type: str | None,
) -> CompletionInternalResult:
    """Route to tool execution or multi-turn, then finalize and return result."""
    visible_tool_names = None
    if project_id:
        from app.services.project_permission_service import get_visible_tools_for_project

        visible_tool_names = await get_visible_tools_for_project(project_id, db)

    provisioned = provision_standard_tools(
        execute_tools,
        tools,
        agent_slug=agent_slug,
        project_id=project_id,
        defer_tool_loading=defer_tool_loading,
        visible_tool_names=visible_tool_names,
    )
    from .tool_router import supports_tools

    should_execute_tools = (execute_tools or enable_programmatic_tools) and bool(provisioned.loaded_tools)
    messages_with_guidance = messages_dict
    if should_execute_tools and supports_tools(provider, model):
        messages_with_guidance, alias_guidance_injected = (
            maybe_inject_claude_tool_alias_guidance(
                messages_with_guidance,
                provisioned.loaded_tools,
                provider=provider,
            )
        )
        if alias_guidance_injected:
            logger.info(
                "Injected Claude MCP alias guidance for session=%s project=%s agent=%s",
                session_id,
                project_id,
                agent_slug,
            )
    ctx = AgentLoopRequest(
        provider=provider, messages_dict=messages_with_guidance,
        user_messages_for_db=user_messages_for_db, model=model,
        temperature=temperature, tools=provisioned.loaded_tools,
        tool_catalog=provisioned.catalog_tools, working_dir=working_dir,
        db=db, session=session,
        session_id=session_id, is_new_session=is_new_session,
        loaded_memory_uuids=loaded_memory_uuids, memory_group_id=memory_group_id,
        skip_cache=skip_cache, progress_callback=progress_callback,
        max_turns=max_turns, project_id=project_id,
        enable_programmatic_tools=enable_programmatic_tools,
        defer_tool_loading=defer_tool_loading,
        enable_caching=enable_caching, cache_ttl=cache_ttl,
        thinking_level=thinking_level, container_id=container_id,
        response_format=response_format, agent_slug=agent_slug, task_type=task_type,
    )
    return await execute_agent_loop(ctx, should_execute_tools=should_execute_tools and supports_tools(provider, model))
