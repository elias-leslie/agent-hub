"""Finish reason handling for multi-turn execution."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.adapters.base import Message

from .tool_handlers import AgentProgress
from .turn_processor import create_progress, report_progress

if TYPE_CHECKING:
    from collections.abc import Callable


async def handle_finish_reason(
    finish_reason: str | None,
    turn: int,
    max_turns: int,
    result: Any,
    messages_for_adapter: list[Message],
    progress_log: list[AgentProgress],
    progress_callback: Callable[[AgentProgress], Any] | None,
) -> tuple[bool, str, str | None]:
    """Handle finish reason and determine if loop should continue.

    Returns:
        Tuple of (should_break, execution_status, execution_error)
    """
    if finish_reason == "end_turn":
        progress = create_progress(turn, "complete", "Agent completed task")
        progress_log.append(progress)
        await report_progress(progress, progress_callback)
        return True, "success", None

    elif finish_reason == "tool_use":
        tool_calls_count = len(result.tool_calls or [])
        progress = create_progress(
            turn,
            "tool_use_requested",
            f"Model requested {tool_calls_count} tool(s) - requires execute_tools=True",
            tool_calls=[{"name": tc.name, "input": tc.input} for tc in (result.tool_calls or [])],
        )
        progress_log.append(progress)
        await report_progress(progress, progress_callback)
        return True, "success", None

    elif finish_reason == "max_tokens":
        return True, "error", "Response truncated due to max_tokens"

    else:
        # Unknown finish reason or None - continue if more turns available
        if turn == max_turns:
            return True, "max_turns", f"Reached maximum turns ({max_turns})"
        else:
            messages_for_adapter.extend(
                [
                    Message(role="assistant", content=result.content),
                    Message(role="user", content="Please continue."),
                ]
            )
            return False, "success", None
