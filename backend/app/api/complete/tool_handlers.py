"""Tool execution handlers for Claude and Gemini providers."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from app.adapters.base import Message
from app.models import Session as DBSession

from .tool_claude_processor import process_claude_message
from .tool_event_storage import store_user_messages
from .tool_gemini_processor import process_gemini_event
from .tool_models import AgentProgress, ToolExecutionResult
from .tool_permission_parser import parse_claude_permissions
from .tool_progress import ProgressTracker
from .tool_response_finalizer import finalize_claude_response, finalize_gemini_response
from .tool_result_builder import build_error_result

__all__ = ["AgentProgress", "ToolExecutionResult", "_complete_with_claude_tools", "_complete_with_gemini_tools"]

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from .schemas import MessageInput

logger = logging.getLogger(__name__)


async def _complete_with_claude_tools(
    adapter: Any,
    messages: list[dict[str, Any]],
    messages_for_db: list[MessageInput] | None,
    model: str,
    provider: str,
    temperature: float,
    tools: list[dict[str, Any]] | None,
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
) -> ToolExecutionResult:
    """Execute completion using Claude's complete_with_tools() for full observability."""
    messages_for_adapter = [Message(role=m["role"], content=m["content"]) for m in messages]
    content_parts: list[str] = []
    thinking_parts: list[str] = []
    tool_calls_count = 0
    turn = 0
    tracker = ProgressTracker(progress_callback)

    await store_user_messages(db, session_id, messages_for_db)

    yolo_mode, write_enabled = parse_claude_permissions(permission_config)

    try:
        async for msg, _sess_id in adapter.complete_with_tools(
            messages=messages_for_adapter,
            model=model,
            tools=tools or [],
            working_dir=working_dir,
            write_enabled=write_enabled,
            yolo_mode=yolo_mode,
        ):
            turn, tools_delta = await process_claude_message(
                msg, turn, session_id, db, content_parts, thinking_parts, tracker
            )
            tool_calls_count += tools_delta

    except Exception as e:
        logger.exception(f"Claude complete_with_tools error: {e}")
        return build_error_result(e, model, provider, session_id, loaded_memory_uuids)

    return await finalize_claude_response(
        db, session, session_id, is_new_session, model, provider,
        content_parts, thinking_parts, loaded_memory_uuids, memory_group_id,
        turn, tool_calls_count, tracker
    )


async def _complete_with_gemini_tools(
    adapter: Any,
    messages: list[dict[str, Any]],
    messages_for_db: list[MessageInput] | None,
    model: str,
    provider: str,
    temperature: float,
    tools: list[dict[str, Any]] | None,
    working_dir: str | None,
    max_turns: int,
    permission_config: dict[str, Any] | None,
    db: AsyncSession,
    session: DBSession,
    session_id: str,
    is_new_session: bool,
    loaded_memory_uuids: list[str],
    memory_group_id: str | None,
    skip_cache: bool,
    progress_callback: Callable[[AgentProgress], Any] | None,
    project_id: str | None = None,
) -> ToolExecutionResult:
    """Execute completion using Gemini's complete_with_tools() for full observability."""
    messages_for_adapter = [Message(role=m["role"], content=m["content"]) for m in messages]
    content_parts: list[str] = []
    tool_calls_count = 0
    turn = 0
    tracker = ProgressTracker(progress_callback)

    await store_user_messages(db, session_id, messages_for_db)

    try:
        async for event, _gemini_session_id in adapter.complete_with_tools(
            messages=messages_for_adapter,
            model=model,
            tools=tools or [],
            working_dir=working_dir,
            max_turns=max_turns,
            permission_config=permission_config,
            project_id=project_id,
        ):
            turn, tools_delta, error_message = await process_gemini_event(
                event, turn, session_id, db, content_parts, tracker
            )
            tool_calls_count += tools_delta

            if error_message:
                return build_error_result(Exception(error_message), model, provider, session_id, loaded_memory_uuids)

        await db.commit()

    except Exception as e:
        logger.exception(f"Gemini complete_with_tools error: {e}")
        return build_error_result(e, model, provider, session_id, loaded_memory_uuids)

    return await finalize_gemini_response(
        db, session, session_id, is_new_session, model, provider,
        content_parts, loaded_memory_uuids, memory_group_id,
        turn, tool_calls_count, tracker
    )
