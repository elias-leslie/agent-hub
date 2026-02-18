"""Tool execution handlers for Claude and Gemini providers."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from app.models import Session as DBSession

from .tool_event_storage import store_user_messages
from .tool_handler_utils import (
    _init_execution_state,
    _run_claude_tool_loop,
    _run_gemini_tool_loop,
)
from .tool_models import AgentProgress, ToolExecutionResult
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
    state = _init_execution_state(session, messages)
    tracker = ProgressTracker(progress_callback)

    await store_user_messages(db, session_id, messages_for_db, agent_id=state.agent_slug)

    try:
        await _run_claude_tool_loop(
            adapter, state, model, tools, working_dir, permission_config, session_id, db, tracker,
        )
    except Exception as e:
        logger.exception(f"Claude complete_with_tools error: {e}")
        return build_error_result(e, model, provider, session_id, loaded_memory_uuids)

    return await finalize_claude_response(
        db, session, session_id, is_new_session, model, provider,
        state.content_parts, state.thinking_parts, loaded_memory_uuids, memory_group_id,
        state.turn, state.tool_calls_count, tracker,
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
    state = _init_execution_state(session, messages)
    tracker = ProgressTracker(progress_callback)

    await store_user_messages(db, session_id, messages_for_db, agent_id=state.agent_slug)

    try:
        error_result = await _run_gemini_tool_loop(
            adapter, state, model, provider, tools, working_dir, max_turns,
            permission_config, session_id, loaded_memory_uuids, db, tracker, project_id,
        )
        if error_result is not None:
            return error_result
        await db.commit()
    except Exception as e:
        logger.exception(f"Gemini complete_with_tools error: {e}")
        return build_error_result(e, model, provider, session_id, loaded_memory_uuids)

    return await finalize_gemini_response(
        db, session, session_id, is_new_session, model, provider,
        state.content_parts, loaded_memory_uuids, memory_group_id,
        state.turn, state.tool_calls_count, tracker,
    )
