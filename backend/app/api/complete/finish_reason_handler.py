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
    messages_dict: list[dict[str, Any]],
    progress_log: list[AgentProgress],
    progress_callback: Callable[[AgentProgress], Any] | None,
    state: dict[str, Any],
    agent_slug: str | None,
    task_type: str | None,
    hard_cap: int | None = None,
) -> tuple[bool, str, str | None]:
    """Handle finish reason and determine if loop should continue.

    Returns:
        Tuple of (should_break, execution_status, execution_error)
    """
    cap = hard_cap or max_turns

    if (
        finish_reason == "end_turn"
        and agent_slug == "persona"
        and task_type in {"heartbeat", "wake"}
        and not state.get("closeout_audit_used")
        and turn < max_turns
    ):
        progress = create_progress(
            turn,
            "closeout_audit",
            "Triggered one-shot final completion audit before ending session",
        )
        progress_log.append(progress)
        await report_progress(progress, progress_callback)
        _append_message(messages_for_adapter, messages_dict, "assistant", result.content)
        _append_message(messages_for_adapter, messages_dict, "user", _CLOSEOUT_AUDIT_MSG)
        state["closeout_audit_used"] = True
        return False, "success", None

    if finish_reason == "end_turn":
        if (
            not (result.content or "").strip()
            and not state.get("empty_closeout_used")
            and turn < cap
        ):
            progress = create_progress(
                turn,
                "empty_closeout_retry",
                "Agent ended without a user-facing response; requesting one final closeout turn",
            )
            progress_log.append(progress)
            await report_progress(progress, progress_callback)
            _append_message(messages_for_adapter, messages_dict, "assistant", result.content)
            _append_message(messages_for_adapter, messages_dict, "user", _EMPTY_FINAL_RESPONSE_MSG)
            state["empty_closeout_used"] = True
            return False, "success", None

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
        if turn == cap:
            return True, "max_turns", f"Reached maximum turns ({cap})"
        else:
            _append_message(messages_for_adapter, messages_dict, "assistant", result.content)
            _append_message(messages_for_adapter, messages_dict, "user", "Please continue.")
            return False, "success", None


_CLOSEOUT_AUDIT_MSG = (
    "<system-closeout-audit>"
    "Run a final completion audit before ending. "
    "Check only these questions: "
    "(1) Is any unresolved canonical gate still visible (cleanup, workspace inspection, stale/recent-progress session state)? "
    "(2) Is there one concrete next action you already know and have not taken? "
    "(3) Would continuing now create real forward progress rather than commentary? "
    "If all answers indicate completion, end now. "
    "If one answer shows unfinished concrete work, do that work now. "
    "Do not start speculative new work. Do not loop on this audit."
    "</system-closeout-audit>"
)

_EMPTY_FINAL_RESPONSE_MSG = (
    "<system-final-response>"
    "You have finished tool work but have not produced a final user-facing response. "
    "Write the final response now. "
    "If no changes were needed, say so plainly. "
    "If changes were made, summarize the exact changes and evidence. "
    "Do not call more tools unless a missing fact blocks the response."
    "</system-final-response>"
)


def _append_message(
    messages_for_adapter: list[Message],
    messages_dict: list[dict[str, Any]],
    role: str,
    content: str | None,
) -> None:
    text = content or ""
    messages_for_adapter.append(Message(role=role, content=text))
    messages_dict.append({"role": role, "content": text})
