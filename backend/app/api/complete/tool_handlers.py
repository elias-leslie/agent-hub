"""Unified tool execution handler for all providers."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from app.models import Session as DBSession

from .tool_event_storage import store_assistant_response, store_user_messages
from .tool_handler_utils import _ExecutionState, _init_execution_state, _run_tool_loop
from .tool_models import AgentProgress, ToolExecutionResult
from .tool_progress import ProgressTracker
from .tool_response_finalizer import finalize_response
from .tool_result_builder import build_error_result

__all__ = ["AgentProgress", "ToolExecutionResult", "_complete_with_tools"]

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from .schemas import MessageInput

logger = logging.getLogger(__name__)


async def _store_partial_response(
    db: AsyncSession,
    session_id: str,
    session: DBSession,
    state: _ExecutionState,
    model: str,
    error_detail: str | None = None,
) -> None:
    """Store whatever content was accumulated before an error, for traceability.

    Also marks the session as completed so it doesn't remain stuck in 'active' status.
    Thinking events are already stored during the event loop, so only the
    assistant_message needs saving here.
    """
    try:
        # Clear any dirty transaction state from the error that triggered this
        await db.rollback()

        content = "".join(state.content_parts)
        if not content:
            if error_detail:
                content = f"Session interrupted: {error_detail}"
            else:
                content = "Session interrupted before response"
        estimated_tokens = len(content) // 4
        session.status = "completed"
        await store_assistant_response(
            db, session_id, content, model, estimated_tokens,
            agent_id=state.agent_slug,
        )
        await db.commit()
    except Exception:
        logger.warning("Failed to store partial response for session %s", session_id)
        try:
            session.status = "completed"
            await db.commit()
        except Exception:
            pass


async def _execute_and_handle_errors(
    adapter: Any,
    state: _ExecutionState,
    provider: str,
    model: str,
    tools: list[dict[str, Any]] | None,
    tool_catalog: list[dict[str, Any]] | None,
    working_dir: str | None,
    permission_config: dict[str, Any] | None,
    session_id: str,
    loaded_memory_uuids: list[str],
    db: AsyncSession,
    session: DBSession,
    tracker: ProgressTracker,
    max_turns: int,
    project_id: str | None,
) -> ToolExecutionResult | None:
    """Run the tool loop and handle errors. Returns an error result or None on success."""
    try:
        error_result = await _run_tool_loop(
            adapter, state, provider, model, tools, tool_catalog, working_dir, permission_config,
            session_id, loaded_memory_uuids, db, tracker, max_turns, project_id,
        )
        if error_result is not None:
            await _store_partial_response(db, session_id, session, state, model, error_detail=error_result.error)
            return error_result
        await db.commit()
        return None
    except Exception as e:
        logger.exception(f"{provider} complete_with_tools error: {e}")
        await _store_partial_response(db, session_id, session, state, model, error_detail=str(e))
        return build_error_result(
            e, model, provider, session_id, loaded_memory_uuids,
            turns=state.turn, tool_calls_count=state.tool_calls_count,
        )


async def _complete_with_tools(
    adapter: Any,
    messages: list[dict[str, Any]],
    messages_for_db: list[MessageInput] | None,
    model: str,
    provider: str,
    temperature: float,
    tools: list[dict[str, Any]] | None,
    tool_catalog: list[dict[str, Any]] | None,
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
) -> ToolExecutionResult:
    """Execute completion with tool support for any provider.

    Handles Claude, Gemini, CloudCode, and all OpenAI-compatible providers
    through a unified pipeline.
    """
    state = _init_execution_state(session, messages)
    tracker = ProgressTracker(progress_callback)
    await store_user_messages(db, session_id, messages_for_db, agent_id=state.agent_slug)

    error_result = await _execute_and_handle_errors(
        adapter, state, provider, model, tools, tool_catalog, working_dir, permission_config,
        session_id, loaded_memory_uuids, db, session, tracker, max_turns, project_id,
    )
    if error_result is not None:
        return error_result

    return await finalize_response(
        db, session, session_id, is_new_session, model, provider,
        state.content_parts, state.thinking_parts, loaded_memory_uuids,
        memory_group_id, state.turn, state.tool_calls_count, tracker,
    )
