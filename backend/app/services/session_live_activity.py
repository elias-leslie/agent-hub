"""Structured live execution activity for session observability."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.models import Session

_ACTIVE_PHASES = {
    "created",
    "injecting_memory",
    "waiting_for_model",
    "planning",
    "running_tool",
    "reading_file",
    "writing_file",
    "running_validation",
    "finalizing",
}
_QUIET_AFTER_SECONDS = 60
_STALL_AFTER_SECONDS = 30 * 60
_NO_ACTIVITY_STALL_AFTER_SECONDS = 90 * 60
_DEAD_CANDIDATE_AFTER_SECONDS = 30 * 60
_REAPABLE_AFTER_SECONDS = 6 * 60 * 60
_TOUCHED_FILES_LIMIT = 10
_RECENT_PATHS_LIMIT = 20
_NON_REAPABLE_PHASES = {
    "injecting_memory",
    "planning",
    "running_tool",
    "reading_file",
    "writing_file",
    "running_validation",
    "finalizing",
}
_DETACHED_AGENT_HUB_RESTART_TOKENS = (
    "rebuild.sh --detach agent-hub",
    "restart.sh --detach agent-hub",
)


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _metadata_dict(session: Session) -> dict[str, Any]:
    raw_metadata = getattr(session, "provider_metadata", None)
    metadata = raw_metadata if isinstance(raw_metadata, dict) else None
    if metadata is None:
        metadata = {}
    return dict(metadata)


def _live_activity(metadata: dict[str, Any]) -> dict[str, Any]:
    live_activity = metadata.get("live_activity")
    if isinstance(live_activity, dict):
        return dict(live_activity)
    return {}


def _activity_age_seconds(value: Any) -> int | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        last_dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if last_dt.tzinfo is None:
        last_dt = last_dt.replace(tzinfo=UTC)
    return max(int((datetime.now(UTC) - last_dt).total_seconds()), 0)


def _path_from_tool_input(tool_input: dict[str, Any] | None) -> str | None:
    if not isinstance(tool_input, dict):
        return None
    for key in ("file_path", "path", "target_file"):
        value = tool_input.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _command_from_tool_input(tool_input: dict[str, Any] | None) -> str | None:
    if not isinstance(tool_input, dict):
        return None
    value = tool_input.get("command")
    return value if isinstance(value, str) and value else None


def _is_detached_agent_hub_restart_command(command: Any) -> bool:
    if not isinstance(command, str):
        return False
    normalized = " ".join(command.lower().split())
    return any(token in normalized for token in _DETACHED_AGENT_HUB_RESTART_TOKENS)


def _detached_agent_hub_restart_stale(
    response: dict[str, Any],
    quiet_for: int | None,
    *,
    has_owner_lane: bool,
) -> bool:
    return (
        not has_owner_lane
        and quiet_for is not None
        and quiet_for >= _DEAD_CANDIDATE_AFTER_SECONDS
        and int(response.get("outstanding_tool_calls") or 0) == 0
        and _is_detached_agent_hub_restart_command(response.get("last_command"))
    )


def _tool_phase(tool_name: str | None, tool_input: dict[str, Any] | None) -> tuple[str, str]:
    normalized = (tool_name or "").lower()
    command = _command_from_tool_input(tool_input)

    if "read" in normalized:
        path = _path_from_tool_input(tool_input)
        return "reading_file", f"Reading {path or 'file'}"

    if "write" in normalized or "edit" in normalized:
        path = _path_from_tool_input(tool_input)
        return "writing_file", f"Writing {path or 'file'}"

    if command:
        validation_tokens = ("dt ", "pytest", "ruff", "tsc", "biome", "sqlfluff", "squawk")
        if any(token in command for token in validation_tokens):
            return "running_validation", f"Running validation: {command[:100]}"
        return "running_tool", f"Running command: {command[:100]}"

    return "running_tool", f"Running tool: {tool_name or 'unknown'}"


def _append_touched_file(live_activity: dict[str, Any], path: str | None) -> None:
    if not path:
        return
    touched = live_activity.get("files_touched")
    if not isinstance(touched, list):
        touched = []
    if path in touched:
        touched = [p for p in touched if p != path]
    touched.append(path)
    live_activity["files_touched"] = touched[-_TOUCHED_FILES_LIMIT:]


def _append_recent_paths(
    live_activity: dict[str, Any],
    key: str,
    paths: list[str] | None,
) -> None:
    recent = live_activity.get(key)
    if not isinstance(recent, list):
        recent = []
    for path in paths or []:
        if path in recent:
            recent = [existing for existing in recent if existing != path]
        recent.append(path)
    live_activity[key] = recent[-_RECENT_PATHS_LIMIT:]


def _mark_non_terminal_state(
    live_activity: dict[str, Any],
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


def _summary_looks_active(summary: Any) -> bool:
    if not isinstance(summary, str):
        return True
    return summary.startswith(
        (
            "Waiting for model",
            "Tool failed:",
            "Running ",
            "Reading ",
            "Writing ",
            "Injecting memory",
            "Model planning",
        )
    )


def _synthetic_live_activity(session: Session) -> dict[str, Any] | None:
    metadata = _metadata_dict(session)
    raw = _live_activity(metadata)
    if raw:
        return raw
    if session.status != "active":
        return None
    last_updated = session.updated_at or getattr(session, "last_activity_at", None) or session.created_at
    last_updated_iso = last_updated.isoformat() if last_updated is not None else None
    return {
        "phase": "unknown",
        "status": "active",
        "summary": "No structured activity recorded",
        "last_event_type": None,
        "last_event_at": last_updated_iso,
        "last_model_activity_at": last_updated_iso,
        "outstanding_tool_calls": 0,
        "tool_calls_count": 0,
        "files_touched": [],
        "last_heartbeat_at": None,
    }


def _collect_anti_reap_signals(
    response: dict[str, Any],
    phase: str,
    quiet_for: int | None,
    *,
    has_owner_lane: bool,
    has_specialist_lane: bool,
) -> list[str]:
    signals: list[str] = []
    detached_rebuild_stale = _detached_agent_hub_restart_stale(
        response,
        quiet_for,
        has_owner_lane=has_owner_lane,
    )
    if has_owner_lane:
        signals.append("owner_lane")
    if has_specialist_lane and not detached_rebuild_stale:
        signals.append("specialist_lane")
    if int(response.get("outstanding_tool_calls") or 0) > 0:
        signals.append("outstanding_tool_calls")
    if phase in _NON_REAPABLE_PHASES:
        signals.append(f"phase_{phase}")
    if response.get("last_write_path") and quiet_for is not None and quiet_for < _REAPABLE_AFTER_SECONDS:
        signals.append("recent_write_activity")
    return signals


def _collect_dead_signals(
    response: dict[str, Any],
    phase: str,
    quiet_for: int | None,
    last_heartbeat_age: int | None,
) -> list[str]:
    signals: list[str] = []
    last_event_type = str(response.get("last_event_type") or "")
    if quiet_for is not None and quiet_for >= _DEAD_CANDIDATE_AFTER_SECONDS:
        signals.append("no_model_activity_30m")
    if phase == "unknown" and quiet_for is not None and quiet_for >= _NO_ACTIVITY_STALL_AFTER_SECONDS:
        signals.append("no_structured_activity")
    if last_event_type == "heartbeat" and quiet_for is not None and quiet_for >= _DEAD_CANDIDATE_AFTER_SECONDS:
        signals.append("heartbeat_only")
    if response.get("termination_reason"):
        signals.append("termination_signal")
    if _is_detached_agent_hub_restart_command(response.get("last_command")):
        signals.append("detached_control_plane_rebuild")
    if last_heartbeat_age is None and quiet_for is not None and quiet_for >= _REAPABLE_AFTER_SECONDS:
        signals.append("heartbeat_missing")
    elif last_heartbeat_age is not None and last_heartbeat_age >= _REAPABLE_AFTER_SECONDS:
        signals.append("heartbeat_absent_6h")
    return signals


_STRONG_DEAD_SIGNALS = {
    "no_structured_activity", "heartbeat_only", "heartbeat_missing",
    "heartbeat_absent_6h", "termination_signal", "detached_control_plane_rebuild",
}


def _apply_lifecycle_state(
    session: Session,
    response: dict[str, Any],
    *,
    has_owner_lane: bool,
    has_specialist_lane: bool,
) -> None:
    quiet_for_seconds = response.get("quiet_for_seconds")
    quiet_for = quiet_for_seconds if isinstance(quiet_for_seconds, int) else None
    phase = str(response.get("phase") or "unknown")
    last_heartbeat_age = _activity_age_seconds(response.get("last_heartbeat_at"))

    anti_reap_signals = _collect_anti_reap_signals(
        response, phase, quiet_for,
        has_owner_lane=has_owner_lane, has_specialist_lane=has_specialist_lane,
    )
    detached_rebuild_stale = _detached_agent_hub_restart_stale(
        response,
        quiet_for,
        has_owner_lane=has_owner_lane,
    )
    dead_signals: list[str] = []
    state = str(response.get("health") or response.get("status") or "idle")

    if session.status == "active":
        dead_signals = _collect_dead_signals(response, phase, quiet_for, last_heartbeat_age)
        if dead_signals:
            state = "dead_candidate"
        if (
            detached_rebuild_stale
            and state == "dead_candidate"
            and not anti_reap_signals
            and "detached_control_plane_rebuild" in dead_signals
        ):
            state = "reapable"
        if (
            quiet_for is not None
            and quiet_for >= _REAPABLE_AFTER_SECONDS
            and state == "dead_candidate"
            and not anti_reap_signals
            and any(s in _STRONG_DEAD_SIGNALS for s in dead_signals)
        ):
            state = "reapable"

    reason_codes = [*dead_signals, *anti_reap_signals] or [f"health_{state}"]
    response.update({
        "lifecycle_state": state,
        "lifecycle_reason_codes": reason_codes,
        "dead_signals": dead_signals,
        "anti_reap_signals": anti_reap_signals,
        "has_owner_lane": has_owner_lane,
        "has_specialist_lane": has_specialist_lane,
        "reapable": state == "reapable",
        "reapable_reason": "+".join([*dead_signals, "no_lane"]) if state == "reapable" else None,
    })


def _handle_tool_use_event(
    live_activity: dict[str, Any],
    tool_name: str | None,
    tool_input: dict[str, Any] | None,
    now_iso: str,
) -> None:
    phase, summary = _tool_phase(tool_name, tool_input)
    _mark_non_terminal_state(live_activity, phase=phase, summary=summary, now_iso=now_iso)
    live_activity["current_tool_name"] = tool_name
    live_activity["last_tool_name"] = tool_name
    live_activity["last_tool_started_at"] = now_iso
    live_activity["outstanding_tool_calls"] = max(
        int(live_activity.get("outstanding_tool_calls") or 0) + 1, 1,
    )
    live_activity["tool_calls_count"] = int(live_activity.get("tool_calls_count") or 0) + 1
    path = _path_from_tool_input(tool_input)
    command = _command_from_tool_input(tool_input)
    if phase == "reading_file":
        live_activity["last_read_path"] = path
    elif phase == "writing_file":
        live_activity["last_write_path"] = path
        _append_touched_file(live_activity, path)
    if command:
        live_activity["last_command"] = command
        if phase == "running_validation":
            live_activity["last_validation_command"] = command


def _handle_tool_result_event(
    live_activity: dict[str, Any],
    tool_name: str | None,
    tool_output: dict[str, Any] | None,
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
    live_activity["outstanding_tool_calls"] = max(
        int(live_activity.get("outstanding_tool_calls") or 0) - 1, 0,
    )
    live_activity["stall_reason"] = None
    live_activity["termination_reason"] = None
    if isinstance(tool_output, dict):
        exit_code = tool_output.get("exit_code")
        if isinstance(exit_code, int):
            live_activity["last_command_exit_code"] = exit_code


def _handle_assistant_message_event(
    live_activity: dict[str, Any],
    content: str | None,
    now_iso: str,
) -> None:
    summary = "Finalizing response"
    if isinstance(content, str) and content.strip():
        summary = f"Assistant responded: {content.strip()[:100]}"
    _mark_non_terminal_state(live_activity, phase="finalizing", summary=summary, now_iso=now_iso)
    live_activity["current_tool_name"] = None
    live_activity["outstanding_tool_calls"] = 0


def _handle_error_event(
    live_activity: dict[str, Any],
    content: str | None,
    now_iso: str,
) -> None:
    live_activity["phase"] = "error"
    live_activity["status"] = "error"
    live_activity["summary"] = f"Execution error: {(content or 'unknown error')[:120]}"
    live_activity["termination_reason"] = content
    live_activity["current_tool_name"] = None
    live_activity["outstanding_tool_calls"] = 0
    live_activity["last_model_activity_at"] = now_iso


def update_live_activity_for_event(
    session: Session,
    *,
    event_type: str,
    tool_name: str | None = None,
    tool_input: dict[str, Any] | None = None,
    tool_output: dict[str, Any] | None = None,
    content: str | None = None,
    model_used: str | None = None,
) -> None:
    """Update provider_metadata.live_activity from a stored session event."""
    metadata = _metadata_dict(session)
    live_activity = _live_activity(metadata)
    now_iso = _now_iso()

    live_activity["last_event_type"] = event_type
    live_activity["last_event_at"] = now_iso
    if model_used:
        live_activity["model_used"] = model_used

    if event_type == "memory_inject":
        _mark_non_terminal_state(live_activity, phase="injecting_memory", summary="Injecting memory context", now_iso=now_iso)
    elif event_type == "thinking":
        _mark_non_terminal_state(live_activity, phase="planning", summary="Model planning", now_iso=now_iso)
    elif event_type == "tool_use":
        _handle_tool_use_event(live_activity, tool_name, tool_input, now_iso)
    elif event_type == "tool_result":
        _handle_tool_result_event(live_activity, tool_name, tool_output, now_iso)
    elif event_type == "assistant_message":
        _handle_assistant_message_event(live_activity, content, now_iso)
    elif event_type == "error":
        _handle_error_event(live_activity, content, now_iso)

    metadata["live_activity"] = live_activity
    session.provider_metadata = metadata


def mark_session_execution_start(session: Session, summary: str = "Waiting for model response") -> None:
    """Mark a session as actively executing before the provider responds."""
    metadata = _metadata_dict(session)
    live_activity = _live_activity(metadata)
    now_iso = _now_iso()
    live_activity.update(
        {
            "phase": "waiting_for_model",
            "status": "active",
            "summary": summary,
            "last_event_type": "session_start",
            "last_event_at": now_iso,
            "last_model_activity_at": now_iso,
            "termination_reason": None,
            "stall_reason": None,
            "outstanding_tool_calls": int(live_activity.get("outstanding_tool_calls") or 0),
            "tool_calls_count": int(live_activity.get("tool_calls_count") or 0),
        }
    )
    metadata["live_activity"] = live_activity
    session.provider_metadata = metadata


def mark_session_terminal_state(
    session: Session,
    *,
    phase: str,
    status: str,
    summary: str,
    termination_reason: str | None,
) -> None:
    """Persist terminal execution state on the session metadata."""
    metadata = _metadata_dict(session)
    live_activity = _live_activity(metadata)
    now_iso = _now_iso()
    live_activity.update(
        {
            "phase": phase,
            "status": status,
            "summary": summary,
            "termination_reason": termination_reason,
            "stall_reason": None,
            "current_tool_name": None,
            "outstanding_tool_calls": 0,
            "last_event_at": now_iso,
            "last_model_activity_at": now_iso,
        }
    )
    metadata["live_activity"] = live_activity
    session.provider_metadata = metadata


def mark_session_completed(
    session: Session,
    *,
    summary: str,
    termination_reason: str | None,
) -> None:
    """Synchronize completed status with terminal live activity metadata."""
    session.status = "completed"
    session.health_detail = "completed"
    mark_session_terminal_state(
        session,
        phase="completed",
        status="completed",
        summary=summary,
        termination_reason=termination_reason,
    )


def apply_live_activity_heartbeat(
    session: Session,
    *,
    heartbeat_at: str,
    phase: str | None = None,
    status: str | None = None,
    summary: str | None = None,
    current_tool_name: str | None = None,
    current_command: str | None = None,
    last_event_type: str | None = None,
    active_read_paths: list[str] | None = None,
    active_write_paths: list[str] | None = None,
) -> None:
    """Update live activity directly from an external session heartbeat."""
    metadata = _metadata_dict(session)
    live_activity = _live_activity(metadata)

    live_activity["last_heartbeat_at"] = heartbeat_at
    live_activity["last_event_at"] = heartbeat_at
    live_activity["last_model_activity_at"] = heartbeat_at
    live_activity["termination_reason"] = None
    live_activity["status"] = status or str(live_activity.get("status") or "active")
    live_activity["phase"] = phase or str(live_activity.get("phase") or "waiting_for_model")
    if summary is not None:
        live_activity["summary"] = summary
    if current_tool_name is not None:
        live_activity["current_tool_name"] = current_tool_name
        live_activity["last_tool_name"] = current_tool_name
    if current_command is not None:
        live_activity["current_command"] = current_command
        live_activity["last_command"] = current_command
    if last_event_type is not None:
        live_activity["last_event_type"] = last_event_type
    if active_read_paths:
        live_activity["last_read_path"] = active_read_paths[-1]
        _append_recent_paths(live_activity, "recent_read_paths", active_read_paths)
    if active_write_paths:
        live_activity["last_write_path"] = active_write_paths[-1]
        _append_recent_paths(live_activity, "recent_write_paths", active_write_paths)
        for path in active_write_paths:
            _append_touched_file(live_activity, path)

    metadata["live_activity"] = live_activity
    session.provider_metadata = metadata


def _classify_active_health(
    response: dict[str, Any],
    phase: str,
    quiet_for_seconds: int | None,
) -> tuple[str, bool, str | None]:
    """Return (health, stalled, stall_reason) for an active session."""
    if phase in _ACTIVE_PHASES:
        if quiet_for_seconds is not None and quiet_for_seconds >= _STALL_AFTER_SECONDS:
            return "stalled", True, f"No model activity for {quiet_for_seconds}s while phase={phase}"
        if quiet_for_seconds is not None and quiet_for_seconds >= _QUIET_AFTER_SECONDS:
            return "quiet", False, None
        return "active", False, None

    if phase == "unknown":
        if quiet_for_seconds is not None and quiet_for_seconds >= _NO_ACTIVITY_STALL_AFTER_SECONDS:
            return "stalled", True, f"No structured activity for {quiet_for_seconds}s"
        if quiet_for_seconds is not None and quiet_for_seconds >= _QUIET_AFTER_SECONDS:
            return "quiet", False, None
        return "active", False, None

    return "active", False, None


def _apply_terminal_overrides(
    response: dict[str, Any],
    session: Session,
    phase: str,
    status: str,
) -> str:
    """Apply completed/failed overrides, return health string."""
    if session.status == "completed":
        response["status"] = "completed"
        if phase in _ACTIVE_PHASES:
            response["phase"] = "completed"
        if status != "completed" and _summary_looks_active(response.get("summary")):
            response["summary"] = "Session completed"
        return "completed"
    if session.status == "failed":
        response["status"] = "failed"
        if phase in _ACTIVE_PHASES:
            response["phase"] = "failed"
        if status not in {"failed", "error"} and _summary_looks_active(response.get("summary")):
            response["summary"] = "Session failed"
        return "failed"
    return "idle"


def build_live_activity_response(
    session: Session,
    *,
    has_owner_lane: bool = False,
    has_specialist_lane: bool = False,
) -> dict[str, Any] | None:
    """Build API-ready live activity payload with dynamic quiet/stall classification."""
    raw = _synthetic_live_activity(session)
    if not raw:
        return None

    response = dict(raw)
    phase = str(response.get("phase") or "created")
    status = str(response.get("status") or ("active" if session.status == "active" else session.status))
    response["phase"] = phase
    response["status"] = status
    quiet_for_seconds = _activity_age_seconds(
        response.get("last_model_activity_at") or response.get("last_event_at"),
    )
    response["quiet_for_seconds"] = quiet_for_seconds

    if session.status == "active":
        health, stalled, stall_reason = _classify_active_health(response, phase, quiet_for_seconds)
    elif status == "error":
        health, stalled, stall_reason = "error", False, None
    else:
        health = _apply_terminal_overrides(response, session, phase, status)
        stalled, stall_reason = False, None

    response["health"] = health
    response["stalled"] = stalled
    response["stall_reason"] = stall_reason or response.get("stall_reason")
    response["files_touched"] = response.get("files_touched") or []
    response["last_heartbeat_at"] = response.get("last_heartbeat_at")
    _apply_lifecycle_state(
        session, response,
        has_owner_lane=has_owner_lane, has_specialist_lane=has_specialist_lane,
    )
    return response
