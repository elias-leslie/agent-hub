"""Shared utilities and helper functions for tool execution handlers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from app.adapters.base import Message
from app.models import Session as DBSession

from .tool_claude_processor import process_claude_message
from .tool_gemini_processor import process_gemini_event
from .tool_models import ToolExecutionResult
from .tool_progress import ProgressTracker
from .tool_result_builder import build_error_result

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

__all__ = ["_ExecutionState", "_init_execution_state", "_run_claude_tool_loop", "_run_gemini_tool_loop"]


@dataclass
class _ExecutionState:
    """Shared mutable state for a tool execution run."""

    agent_slug: str | None
    messages_for_adapter: list[Message]
    content_parts: list[str] = field(default_factory=list)
    thinking_parts: list[str] = field(default_factory=list)
    tool_calls_count: int = 0
    turn: int = 0


def _init_execution_state(
    session: DBSession,
    messages: list[dict[str, Any]],
) -> _ExecutionState:
    """Build shared execution state from session and raw messages."""
    agent_slug = getattr(session, "agent_slug", None)
    messages_for_adapter = [Message(role=m["role"], content=m["content"]) for m in messages]
    return _ExecutionState(agent_slug=agent_slug, messages_for_adapter=messages_for_adapter)


async def _run_claude_tool_loop(
    adapter: Any,
    state: _ExecutionState,
    model: str,
    tools: list[dict[str, Any]] | None,
    working_dir: str | None,
    permission_config: dict[str, Any] | None,
    session_id: str,
    db: AsyncSession,
    tracker: ProgressTracker,
) -> None:
    """Stream Claude tool events and accumulate results into *state*."""
    async for msg, _sess_id in adapter.complete_with_tools(
        messages=state.messages_for_adapter,
        model=model,
        tools=tools or [],
        working_dir=working_dir,
        permission_config=permission_config,
    ):
        state.turn, tools_delta = await process_claude_message(
            msg, state.turn, session_id, db, state.content_parts, state.thinking_parts, tracker,
            model_used=model, agent_id=state.agent_slug,
        )
        state.tool_calls_count += tools_delta


async def _run_gemini_tool_loop(
    adapter: Any,
    state: _ExecutionState,
    model: str,
    provider: str,
    tools: list[dict[str, Any]] | None,
    working_dir: str | None,
    max_turns: int,
    permission_config: dict[str, Any] | None,
    session_id: str,
    loaded_memory_uuids: list[str],
    db: AsyncSession,
    tracker: ProgressTracker,
    project_id: str | None,
) -> ToolExecutionResult | None:
    """Stream Gemini tool events; returns an error result on failure, else None."""
    async for event, _gemini_session_id in adapter.complete_with_tools(
        messages=state.messages_for_adapter,
        model=model,
        tools=tools or [],
        working_dir=working_dir,
        max_turns=max_turns,
        permission_config=permission_config,
        project_id=project_id,
    ):
        state.turn, tools_delta, error_message = await process_gemini_event(
            event, state.turn, session_id, db, state.content_parts, tracker,
            model_used=model, agent_id=state.agent_slug,
        )
        state.tool_calls_count += tools_delta

        if error_message:
            return build_error_result(
                Exception(error_message), model, provider, session_id, loaded_memory_uuids
            )
    return None
