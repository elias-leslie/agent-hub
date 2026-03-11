"""Shared utilities and helper functions for tool execution handlers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from app.adapters.base import Message
from app.models import Session as DBSession

from .tool_event_processor import process_tool_event
from .tool_models import ToolExecutionResult
from .tool_progress import ProgressTracker
from .tool_result_builder import build_error_result
from .tool_stream_builder import build_event_stream

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

__all__ = ["_ExecutionState", "_init_execution_state", "_run_tool_loop"]


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


async def _run_tool_loop(
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
    tracker: ProgressTracker,
    max_turns: int = 1,
    project_id: str | None = None,
) -> ToolExecutionResult | None:
    """Unified tool loop for all providers.

    Streams events from the adapter's complete_with_tools(), converting
    provider-specific events to ToolEvent format, then processing each
    through the unified tool_event_processor.

    Returns an error result on failure, else None (results in state).
    """
    event_stream = build_event_stream(
        adapter=adapter,
        messages=state.messages_for_adapter,
        provider=provider,
        model=model,
        tools=tools,
        tool_catalog=tool_catalog,
        working_dir=working_dir,
        permission_config=permission_config,
        max_turns=max_turns,
        project_id=project_id,
        session_id=session_id,
        agent_slug=state.agent_slug,
    )

    # Mapping of tool_use_id → tool_name, shared across all events in the loop
    tool_use_id_to_name: dict[str, str] = {}

    terminal_error_message: str | None = None

    try:
        async for event, _session_id in event_stream:
            state.turn, tools_delta, error_message = await process_tool_event(
                event, state.turn, session_id, db, state.content_parts,
                state.thinking_parts, tracker, model_used=model, agent_id=state.agent_slug,
                tool_use_id_to_name=tool_use_id_to_name,
            )
            state.tool_calls_count += tools_delta

            if error_message and terminal_error_message is None:
                # Record the terminal error, but keep draining the provider stream so
                # SDK-backed generators can unwind cleanly on their own task boundary.
                terminal_error_message = error_message
    finally:
        if hasattr(event_stream, "aclose"):
            await event_stream.aclose()

    if terminal_error_message:
        return build_error_result(
            Exception(terminal_error_message), model, provider, session_id, loaded_memory_uuids,
            turns=state.turn, tool_calls_count=state.tool_calls_count,
        )

    return None
