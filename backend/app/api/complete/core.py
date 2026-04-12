"""Core completion logic for the completion API."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ._core_helpers import check_memory_and_cache, execute_and_build_result
from .schemas import MessageInput
from .session_manager import get_or_create_session  # Re-export for backwards compat
from .session_setup import setup_completion_session
from .streaming import stream_completion  # Re-export for backwards compat
from .tool_handlers import AgentProgress
from .types import CompletionInternalResult

logger = logging.getLogger(__name__)


@dataclass
class _CompletionCtx:
    """Groups completion call context to reduce argument passing."""

    db: AsyncSession
    session: Any
    session_id: str
    is_new_session: bool
    messages_dict: list[dict[str, Any]]
    user_messages_for_db: list[MessageInput]
    model: str
    temperature: float
    provider: str
    project_id: str
    tools: list[dict[str, Any]] | None = None
    working_dir: str | None = None
    use_memory: bool = False
    memory_group_id: str | None = None
    task_type: str | None = None
    phase: str | None = None
    memory_config: dict[str, Any] | None = None
    current_branch: str | None = None
    agent_slug: str | None = None
    skip_cache: bool = False
    progress_callback: Callable[[AgentProgress], Any] | None = None
    max_turns: int = 1
    execute_tools: bool = False
    enable_programmatic_tools: bool = False
    defer_tool_loading: bool = False
    enable_caching: bool = True
    cache_ttl: str = "ephemeral"
    thinking_level: str | None = None
    container_id: str | None = None
    response_format: dict[str, Any] | None = None


def _build_ctx(
    db: AsyncSession, session: Any, session_id: str, is_new: bool,
    messages_dict: list[dict[str, Any]], user_messages_for_db: list[MessageInput],
    model: str, temperature: float, provider: str, project_id: str,
    tools: list[dict[str, Any]] | None, working_dir: str | None,
    use_memory: bool,
    memory_group_id: str | None, task_type: str | None, phase: str | None,
    memory_config: dict[str, Any] | None, current_branch: str | None,
    agent_slug: str | None, skip_cache: bool,
    progress_callback: Callable[[AgentProgress], Any] | None,
    max_turns: int, execute_tools: bool, enable_programmatic_tools: bool,
    defer_tool_loading: bool,
    enable_caching: bool, cache_ttl: str, thinking_level: str | None,
    container_id: str | None, response_format: dict[str, Any] | None,
) -> _CompletionCtx:
    """Construct a _CompletionCtx from individual parameters."""
    return _CompletionCtx(
        db=db, session=session, session_id=session_id, is_new_session=is_new,
        messages_dict=messages_dict, user_messages_for_db=user_messages_for_db,
        model=model, temperature=temperature, provider=provider, project_id=project_id,
        tools=tools, working_dir=working_dir,
        use_memory=use_memory, memory_group_id=memory_group_id,
        task_type=task_type, phase=phase, memory_config=memory_config,
        current_branch=current_branch, agent_slug=agent_slug,
        skip_cache=skip_cache, progress_callback=progress_callback,
        max_turns=max_turns, execute_tools=execute_tools,
        enable_programmatic_tools=enable_programmatic_tools,
        defer_tool_loading=defer_tool_loading,
        enable_caching=enable_caching, cache_ttl=cache_ttl,
        thinking_level=thinking_level, container_id=container_id,
        response_format=response_format,
    )


def _ensure_user_messages(
    messages: list[dict[str, Any]], user_messages_for_db: list[MessageInput] | None,
) -> list[MessageInput]:
    """Return user_messages_for_db, defaulting from messages if None."""
    if user_messages_for_db is not None:
        return user_messages_for_db
    return [MessageInput(role=m["role"], content=m["content"]) for m in messages if "role" in m and "content" in m]


async def _run_after_session(ctx: _CompletionCtx) -> CompletionInternalResult:
    """Inject memory, check cache, then execute completion and return result."""
    msgs, loaded_uuids, cached = await check_memory_and_cache(
        messages_dict=ctx.messages_dict, model=ctx.model,
        temperature=ctx.temperature, use_memory=ctx.use_memory,
        memory_group_id=ctx.memory_group_id, task_type=ctx.task_type,
        phase=ctx.phase, memory_config=ctx.memory_config,
        current_branch=ctx.current_branch, agent_slug=ctx.agent_slug,
        skip_cache=ctx.skip_cache, db=ctx.db, session=ctx.session,
        session_id=ctx.session_id, user_messages_for_db=ctx.user_messages_for_db,
        is_new_session=ctx.is_new_session,
    )
    if cached is not None:
        return cached
    return await execute_and_build_result(
        provider=ctx.provider, messages_dict=msgs,
        user_messages_for_db=ctx.user_messages_for_db, model=ctx.model,
        temperature=ctx.temperature, tools=ctx.tools,
        working_dir=ctx.working_dir,
        db=ctx.db, session=ctx.session, session_id=ctx.session_id,
        is_new_session=ctx.is_new_session, loaded_memory_uuids=loaded_uuids,
        memory_group_id=ctx.memory_group_id, skip_cache=ctx.skip_cache,
        progress_callback=ctx.progress_callback, max_turns=ctx.max_turns,
        project_id=ctx.project_id, execute_tools=ctx.execute_tools,
        enable_programmatic_tools=ctx.enable_programmatic_tools,
        defer_tool_loading=ctx.defer_tool_loading,
        enable_caching=ctx.enable_caching, cache_ttl=ctx.cache_ttl,
        thinking_level=ctx.thinking_level, container_id=ctx.container_id,
        response_format=ctx.response_format, agent_slug=ctx.agent_slug,
        task_type=ctx.task_type,
    )


async def complete_internal(
    messages: list[dict[str, Any]], model: str, provider: str,
    temperature: float, project_id: str, db: AsyncSession,
    session_id: str | None = None, external_id: str | None = None,
    client_id: str | None = None, request_source: str | None = None,
    parent_session_id: str | None = None,
    agent_slug: str | None = None, use_memory: bool = False,
    memory_group_id: str | None = None, enable_caching: bool = True,
    cache_ttl: str = "ephemeral", thinking_level: str | None = None,
    tools: list[dict[str, Any]] | None = None,
    enable_programmatic_tools: bool = False,
    defer_tool_loading: bool = False,
    container_id: str | None = None,
    response_format: dict[str, Any] | None = None,
    skip_cache: bool = False,
    user_messages_for_db: list[MessageInput] | None = None,
    max_turns: int = 1, execute_tools: bool = False,
    working_dir: str | None = None,
    progress_callback: Callable[[AgentProgress], Any] | None = None,
    trace_id: str | None = None,
    task_type: str | None = None, phase: str | None = None,
    memory_config: dict[str, Any] | None = None,
    current_branch: str | None = None,
    requested_model: str | None = None,
    requested_provider: str | None = None,
) -> CompletionInternalResult:
    """Core completion logic: session setup, memory, caching, tool/multi-turn execution."""
    user_messages_for_db = _ensure_user_messages(messages, user_messages_for_db)
    session, session_id, is_new, messages_dict = await setup_completion_session(
        db, session_id, project_id, provider, model,
        external_id, client_id, request_source, agent_slug, current_branch, working_dir,
        parent_session_id, messages,
        trace_id=trace_id,
        requested_provider=requested_provider or provider, requested_model=requested_model or model,
    )
    ctx = _build_ctx(
        db=db, session=session, session_id=session_id, is_new=is_new,
        messages_dict=messages_dict, user_messages_for_db=user_messages_for_db,
        model=model, temperature=temperature, provider=provider, project_id=project_id,
        tools=tools, working_dir=working_dir,
        use_memory=use_memory, memory_group_id=memory_group_id,
        task_type=task_type, phase=phase, memory_config=memory_config,
        current_branch=current_branch, agent_slug=agent_slug, skip_cache=skip_cache,
        progress_callback=progress_callback, max_turns=max_turns, execute_tools=execute_tools,
        enable_programmatic_tools=enable_programmatic_tools, defer_tool_loading=defer_tool_loading,
        enable_caching=enable_caching, cache_ttl=cache_ttl, thinking_level=thinking_level,
        container_id=container_id, response_format=response_format,
    )
    return await _run_after_session(ctx)


# Re-export stream_completion for backwards compatibility
__all__ = [
    "AgentProgress",
    "CompletionInternalResult",
    "complete_internal",
    "get_or_create_session",
    "stream_completion",
]
