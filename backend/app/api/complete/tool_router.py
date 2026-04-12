"""Tool execution routing for completion API."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from app.adapters.registry import (
    get_adapter,
    supports_tools,
)

from .schemas import MessageInput
from .tool_handlers import AgentProgress, _complete_with_tools

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.models import Session as DBSession

logger = logging.getLogger(__name__)


async def route_tool_execution(
    provider: str,
    messages_dict: list[dict[str, Any]],
    user_messages_for_db: list[MessageInput] | None,
    model: str,
    temperature: float,
    tools: list[dict[str, Any]],
    tool_catalog: list[dict[str, Any]] | None,
    working_dir: str | None,
    db: AsyncSession,
    session: DBSession,
    session_id: str,
    is_new_session: bool,
    loaded_memory_uuids: list[str],
    memory_group_id: str | None,
    skip_cache: bool,
    progress_callback: Callable[[AgentProgress], Any] | None,
    max_turns: int = 1,
    project_id: str | None = None,
) -> dict[str, Any]:
    """Route tool execution to the unified handler for any supported provider.

    Args:
        provider: Provider name for any tool-capable provider
        messages_dict: Conversation messages
        user_messages_for_db: Original user messages to save
        model: Model identifier
        temperature: Sampling temperature
        tools: Tool definitions
        working_dir: Working directory for tool execution
        db: Database session
        session: DB session object
        session_id: Session ID
        is_new_session: Whether this is a new session
        loaded_memory_uuids: Memory UUIDs that were loaded
        memory_group_id: Memory group for isolation
        progress_callback: Progress callback function
        max_turns: Maximum turns for multi-turn execution
        project_id: Project ID

    Returns:
        Dict with tool execution result attributes
    """
    if not supports_tools(provider, model):
        raise ValueError(f"Tool execution not supported for provider: {provider}, model: {model}")

    adapter = get_adapter(provider)

    tool_result = await _complete_with_tools(
        adapter=adapter,
        messages=messages_dict,
        messages_for_db=user_messages_for_db,
        model=model,
        provider=provider,
        temperature=temperature,
        tools=tools,
        tool_catalog=tool_catalog,
        working_dir=working_dir,
        db=db,
        session=session,
        session_id=session_id,
        is_new_session=is_new_session,
        loaded_memory_uuids=loaded_memory_uuids,
        memory_group_id=memory_group_id,
        progress_callback=progress_callback,
        max_turns=max_turns,
        project_id=project_id,
    )
    return tool_result.__dict__
