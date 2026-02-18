"""Core completion logic for the completion API."""

from __future__ import annotations

import logging
from collections.abc import Callable
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


async def complete_internal(
    messages: list[dict[str, Any]],
    model: str,
    provider: str,
    temperature: float,
    project_id: str,
    db: AsyncSession,
    session_id: str | None = None,
    external_id: str | None = None,
    client_id: str | None = None,
    request_source: str | None = None,
    agent_slug: str | None = None,
    use_memory: bool = False,
    memory_group_id: str | None = None,
    enable_caching: bool = True,
    cache_ttl: str = "ephemeral",
    thinking_level: str | None = None,
    tools: list[dict[str, Any]] | None = None,
    enable_programmatic_tools: bool = False,
    container_id: str | None = None,
    response_format: dict[str, Any] | None = None,
    skip_cache: bool = False,
    user_messages_for_db: list[MessageInput] | None = None,
    max_turns: int = 1,
    execute_tools: bool = False,
    working_dir: str | None = None,
    permission_config: dict[str, Any] | None = None,
    progress_callback: Callable[[AgentProgress], Any] | None = None,
    trace_id: str | None = None,
    task_type: str | None = None,
    phase: str | None = None,
    memory_config: dict[str, Any] | None = None,
    current_branch: str | None = None,
) -> CompletionInternalResult:
    """Core completion logic.

    Handles session setup, memory injection, caching, tool/multi-turn execution.
    """
    if user_messages_for_db is None:
        user_messages_for_db = [
            MessageInput(role=m["role"], content=m["content"])
            for m in messages if "role" in m and "content" in m
        ]

    session, final_session_id, is_new_session, messages_dict = await setup_completion_session(
        db, session_id, project_id, provider, model,
        external_id, client_id, request_source, agent_slug, messages,
    )

    messages_dict, loaded_memory_uuids, cached_result = await check_memory_and_cache(
        messages_dict=messages_dict, model=model, temperature=temperature,
        use_memory=use_memory, memory_group_id=memory_group_id,
        task_type=task_type, phase=phase, memory_config=memory_config,
        current_branch=current_branch, agent_slug=agent_slug,
        skip_cache=skip_cache, db=db, session=session,
        session_id=final_session_id, user_messages_for_db=user_messages_for_db,
        is_new_session=is_new_session,
    )
    if cached_result is not None:
        return cached_result

    return await execute_and_build_result(
        provider=provider, messages_dict=messages_dict,
        user_messages_for_db=user_messages_for_db, model=model,
        temperature=temperature, tools=tools, working_dir=working_dir,
        permission_config=permission_config, db=db, session=session,
        session_id=final_session_id, is_new_session=is_new_session,
        loaded_memory_uuids=loaded_memory_uuids, memory_group_id=memory_group_id,
        skip_cache=skip_cache, progress_callback=progress_callback,
        max_turns=max_turns, project_id=project_id, execute_tools=execute_tools,
        enable_programmatic_tools=enable_programmatic_tools,
        enable_caching=enable_caching, cache_ttl=cache_ttl,
        thinking_level=thinking_level, container_id=container_id,
        response_format=response_format, agent_slug=agent_slug,
    )


# Re-export stream_completion for backwards compatibility
__all__ = [
    "AgentProgress",
    "CompletionInternalResult",
    "complete_internal",
    "get_or_create_session",
    "stream_completion",
]
