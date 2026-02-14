"""Tool execution routing for completion API."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from app.services.event_storage import store_tool_result_event, store_tool_use_event

from .schemas import MessageInput
from .tool_handlers import AgentProgress, _complete_with_claude_tools, _complete_with_gemini_tools

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
    working_dir: str | None,
    permission_config: dict[str, Any] | None,
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
    """Route tool execution to appropriate provider handler.

    Args:
        provider: Provider name (claude/gemini)
        messages_dict: Conversation messages
        user_messages_for_db: Original user messages to save
        model: Model identifier
        temperature: Sampling temperature
        tools: Tool definitions
        working_dir: Working directory for tool execution
        permission_config: Permission configuration
        db: Database session
        session: DB session object
        session_id: Session ID
        is_new_session: Whether this is a new session
        loaded_memory_uuids: Memory UUIDs that were loaded
        memory_group_id: Memory group for isolation
        skip_cache: Skip response cache
        progress_callback: Progress callback function
        max_turns: Maximum turns for multi-turn execution
        project_id: Project ID (required for Gemini)

    Returns:
        Dict with tool execution result attributes
    """
    if provider == "claude":
        from app.adapters.claude import ClaudeAdapter

        agent_slug = getattr(session, "agent_slug", None)

        async def tool_result_callback(
            tool_name: str, tool_input: dict[str, Any], tool_output: str,
            duration_ms: int | None = None,
        ) -> None:
            await store_tool_use_event(
                db,
                session_id,
                tool_name=tool_name,
                tool_input=tool_input if isinstance(tool_input, dict) else {"value": tool_input},
                model_used=model,
                agent_id=agent_slug,
                agent_name=agent_slug,
            )
            await store_tool_result_event(
                db,
                session_id,
                tool_name=tool_name,
                tool_output={"content": tool_output[:2000] if tool_output else ""},
                duration_ms=duration_ms,
                model_used=model,
                agent_id=agent_slug,
                agent_name=agent_slug,
            )
            await db.commit()

        claude_adapter = ClaudeAdapter(after_tool_callback=tool_result_callback)

        tool_result = await _complete_with_claude_tools(
            adapter=claude_adapter,
            messages=messages_dict,
            messages_for_db=user_messages_for_db,
            model=model,
            provider=provider,
            temperature=temperature,
            tools=tools,
            working_dir=working_dir,
            permission_config=permission_config,
            db=db,
            session=session,
            session_id=session_id,
            is_new_session=is_new_session,
            loaded_memory_uuids=loaded_memory_uuids,
            memory_group_id=memory_group_id,
            skip_cache=skip_cache,
            progress_callback=progress_callback,
        )
        return tool_result.__dict__

    elif provider == "gemini":
        from app.adapters.gemini import GeminiAdapter

        gemini_adapter = GeminiAdapter()

        tool_result = await _complete_with_gemini_tools(
            adapter=gemini_adapter,
            messages=messages_dict,
            messages_for_db=user_messages_for_db,
            model=model,
            provider=provider,
            temperature=temperature,
            tools=tools,
            working_dir=working_dir,
            max_turns=max_turns,
            permission_config=permission_config,
            db=db,
            session=session,
            session_id=session_id,
            is_new_session=is_new_session,
            loaded_memory_uuids=loaded_memory_uuids,
            memory_group_id=memory_group_id,
            skip_cache=skip_cache,
            progress_callback=progress_callback,
            project_id=project_id,
        )
        return tool_result.__dict__

    else:
        raise ValueError(f"Tool execution not supported for provider: {provider}")
