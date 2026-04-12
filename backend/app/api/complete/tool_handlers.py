"""Unified tool execution handler for all providers."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from app.models import Session as DBSession
from app.services.session_health import health_detail_for_error, update_session_health
from app.services.session_live_activity import mark_session_completed

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


async def _store_partial_response_best_effort(
    db: AsyncSession,
    session_id: str,
    session: DBSession,
    state: _ExecutionState,
    model: str,
    error_detail: str | None = None,
) -> None:
    """Attempt to persist partial output even when the surrounding task is cancelling."""
    try:
        await _store_partial_response(
            db,
            session_id,
            session,
            state,
            model,
            error_detail=error_detail,
        )
    except asyncio.CancelledError:
        logger.warning("Partial response storage cancelled for session %s", session_id)
        await _rollback_after_cancellation(db)


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
        mark_session_completed(
            session,
            summary="Execution interrupted",
            termination_reason=error_detail,
        )
        await store_assistant_response(
            db, session_id, content, model, estimated_tokens,
            agent_id=state.agent_slug,
        )
        await db.commit()
    except Exception:
        logger.warning("Failed to store partial response for session %s", session_id)
        try:
            mark_session_completed(
                session,
                summary="Execution interrupted",
                termination_reason=error_detail,
            )
            await db.commit()
        except Exception:
            logger.debug("Failed to mark session completed after cancellation", exc_info=True)


async def _rollback_after_cancellation(db: AsyncSession) -> None:
    """Best-effort rollback for cancellation paths that must avoid extra awaits."""
    try:
        await db.rollback()
    except Exception:
        logger.warning("Rollback failed during cancelled tool execution", exc_info=True)

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
    db: AsyncSession,
    session: DBSession,
    session_id: str,
    is_new_session: bool,
    loaded_memory_uuids: list[str],
    memory_group_id: str | None,
    progress_callback: Callable[[AgentProgress], Any] | None,
    max_turns: int = 1,
    project_id: str | None = None,
) -> ToolExecutionResult:
    """Execute completion with tool support for any provider.

    Handles any tool-capable provider through a unified pipeline.
    """
    state = _init_execution_state(session, messages)
    from app.services.activity_topics import default_progress_topic

    tracker = ProgressTracker(
        progress_callback,
        default_topic=default_progress_topic(
            external_id=state.external_id,
            session_id=session_id,
            agent_slug=state.agent_slug,
        ),
    )
    await store_user_messages(db, session_id, messages_for_db, agent_id=state.agent_slug)

    try:
        error_result = await _run_tool_loop(
            adapter, state, provider, model, tools, tool_catalog, working_dir,
            session_id, loaded_memory_uuids, db, tracker, max_turns, project_id,
        )
        if error_result is not None:
            await _store_partial_response(
                db,
                session_id,
                session,
                state,
                model,
                error_detail=error_result.error,
            )
            return error_result

        await db.commit()
        return await finalize_response(
            db, session, session_id, is_new_session, model, provider,
            state.content_parts, state.thinking_parts, loaded_memory_uuids,
            memory_group_id, state.turn, state.tool_calls_count, state.terminal_finish_reason, tracker,
            adapter=adapter,
            base_messages=state.messages_for_adapter,
            temperature=temperature,
            working_dir=working_dir,
            tool_result_summaries=state.tool_result_summaries,
        )
    except asyncio.CancelledError as e:
        logger.exception("%s tool execution cancelled: %s", provider, e)
        error_detail = str(e) or "Completion cancelled unexpectedly."
        await _store_partial_response_best_effort(
            db,
            session_id,
            session,
            state,
            model,
            error_detail=error_detail,
        )
        return build_error_result(
            Exception(error_detail),
            model,
            provider,
            session_id,
            loaded_memory_uuids,
            turns=state.turn,
            tool_calls_count=state.tool_calls_count,
        )
    except Exception as e:
        logger.exception("%s tool execution error: %s", provider, e)
        await update_session_health(
            db,
            session_id,
            health_detail_for_error(e),
            commit=True,
        )
        await _store_partial_response(db, session_id, session, state, model, error_detail=str(e))
        return build_error_result(
            e, model, provider, session_id, loaded_memory_uuids,
            turns=state.turn, tool_calls_count=state.tool_calls_count,
        )
