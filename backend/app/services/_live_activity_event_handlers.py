"""Internal event handler functions for live activity updates."""

from __future__ import annotations

from app.services._live_activity_helpers import (
    LiveActivity,
    activity_topic,
    append_touched_file,
    tool_phase,
)


def mark_non_terminal_state(
    live_activity: LiveActivity,
    *,
    phase: str,
    summary: str,
    now_iso: str,
) -> None:
    live_activity["phase"] = phase
    live_activity["status"] = "active"
    live_activity["summary"] = summary
    live_activity["termination_reason"] = None
    live_activity["stall_reason"] = None
    live_activity["last_model_activity_at"] = now_iso


def handle_tool_use_event(
    live_activity: LiveActivity,
    tool_name: str | None,
    tool_input: LiveActivity | None,
    now_iso: str,
    *,
    base_path: str | None = None,
) -> None:
    phase, summary, path, command = tool_phase(tool_name, tool_input, base_path=base_path)
    topic = activity_topic(tool_name, tool_input, base_path=base_path)
    mark_non_terminal_state(live_activity, phase=phase, summary=summary, now_iso=now_iso)
    live_activity["current_tool_name"] = tool_name
    live_activity["last_tool_name"] = tool_name
    if topic:
        live_activity["current_topic"] = topic
        live_activity["last_topic"] = topic
    live_activity["last_tool_started_at"] = now_iso
    live_activity["outstanding_tool_calls"] = max(
        int(live_activity.get("outstanding_tool_calls") or 0) + 1, 1,
    )
    live_activity["tool_calls_count"] = int(live_activity.get("tool_calls_count") or 0) + 1
    if phase == "reading_file":
        live_activity["last_read_path"] = path
    elif phase == "writing_file":
        live_activity["last_write_path"] = path
        append_touched_file(live_activity, path)
    if not command:
        return
    live_activity["last_command"] = command
    if phase == "running_validation":
        live_activity["last_validation_command"] = command


def handle_tool_result_event(
    live_activity: LiveActivity,
    tool_name: str | None,
    tool_output: LiveActivity | None,
    now_iso: str,
) -> None:
    is_error = bool(tool_output.get("is_error")) if isinstance(tool_output, dict) else False
    resolved_tool = tool_name or live_activity.get("last_tool_name") or "unknown"
    live_activity["phase"] = "waiting_for_model"
    live_activity["status"] = "active"
    live_activity["summary"] = (
        f"Tool failed: {resolved_tool}" if is_error
        else f"Waiting for model after {resolved_tool}"
    )
    live_activity["current_tool_name"] = None
    live_activity["last_tool_name"] = tool_name or live_activity.get("last_tool_name")
    live_activity["last_tool_finished_at"] = now_iso
    live_activity["last_tool_error"] = is_error
    if live_activity.get("last_topic") and not live_activity.get("current_topic"):
        live_activity["current_topic"] = live_activity.get("last_topic")
    live_activity["outstanding_tool_calls"] = max(
        int(live_activity.get("outstanding_tool_calls") or 0) - 1, 0,
    )
    live_activity["stall_reason"] = None
    live_activity["termination_reason"] = None
    if not isinstance(tool_output, dict):
        return
    if is_error and tool_output.get("content"):
        live_activity["last_tool_error_excerpt"] = str(tool_output.get("content") or "").strip()[:300]
    exit_code = tool_output.get("exit_code")
    if isinstance(exit_code, int):
        live_activity["last_command_exit_code"] = exit_code


def handle_assistant_message_event(
    live_activity: LiveActivity,
    content: str | None,
    now_iso: str,
) -> None:
    summary = (
        f"Assistant responded: {content.strip()[:100]}"
        if isinstance(content, str) and content.strip()
        else "Finalizing response"
    )
    mark_non_terminal_state(live_activity, phase="finalizing", summary=summary, now_iso=now_iso)
    live_activity["current_tool_name"] = None
    live_activity["outstanding_tool_calls"] = 0


def handle_error_event(
    live_activity: LiveActivity,
    content: str | None,
    now_iso: str,
) -> None:
    live_activity["phase"] = "error"
    live_activity["status"] = "error"
    live_activity["summary"] = f"Execution error: {(content or 'unknown error')[:120]}"
    live_activity["termination_reason"] = content
    live_activity["current_tool_name"] = None
    live_activity["current_topic"] = None
    live_activity["outstanding_tool_calls"] = 0
    live_activity["last_model_activity_at"] = now_iso
