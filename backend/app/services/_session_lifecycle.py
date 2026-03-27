"""Lifecycle state and health classification for session live activity."""

from __future__ import annotations

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
_NON_REAPABLE_PHASES = {
    "injecting_memory",
    "planning",
    "running_tool",
    "reading_file",
    "writing_file",
    "running_validation",
}
_DETACHED_AGENT_HUB_RESTART_TOKENS = (
    "rebuild.sh --detach agent-hub",
    "restart.sh --detach agent-hub",
)
_STRONG_DEAD_SIGNALS = {
    "no_structured_activity", "heartbeat_only", "heartbeat_missing",
    "heartbeat_absent_6h", "termination_signal", "detached_control_plane_rebuild",
}
_NON_ACTIONABLE_LIFECYCLE_STATES = {
    "dead_candidate",
    "reapable",
    "completed",
    "failed",
    "error",
    "idle",
}
_ACTIVE_SUMMARY_PREFIXES = (
    "Waiting for model",
    "Tool failed:",
    "Running ",
    "Reading ",
    "Writing ",
    "Injecting memory",
    "Model planning",
)


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
    """Apply completed/failed overrides to response, return health string."""
    if session.status == "completed":
        response["status"] = "completed"
        if str(response.get("phase") or "") in _ACTIVE_PHASES:
            response["phase"] = "completed"
        if status != "completed":
            summary = response.get("summary")
            if not isinstance(summary, str) or summary.startswith(_ACTIVE_SUMMARY_PREFIXES):
                response["summary"] = "Session completed"
        return "completed"
    if session.status == "failed":
        response["status"] = "failed"
        if str(response.get("phase") or "") in _ACTIVE_PHASES:
            response["phase"] = "failed"
        if status not in {"failed", "error"}:
            summary = response.get("summary")
            if not isinstance(summary, str) or summary.startswith(_ACTIVE_SUMMARY_PREFIXES):
                response["summary"] = "Session failed"
        return "failed"
    return "idle"


def _compute_anti_reap_signals(
    response: dict[str, Any],
    has_owner_lane: bool,
    has_specialist_lane: bool,
    detached_rebuild_stale: bool,
    phase: str,
    quiet_for: int | None,
) -> list[str]:
    signals: list[str] = []
    if has_owner_lane:
        signals.append("owner_lane")
    if has_specialist_lane and not detached_rebuild_stale:
        signals.append("specialist_lane")
    if int(response.get("outstanding_tool_calls") or 0) > 0:
        signals.append("outstanding_tool_calls")
    if phase in _NON_REAPABLE_PHASES and (quiet_for is None or quiet_for < _REAPABLE_AFTER_SECONDS):
        signals.append(f"phase_{phase}")
    if response.get("last_write_path") and quiet_for is not None and quiet_for < _REAPABLE_AFTER_SECONDS:
        signals.append("recent_write_activity")
    return signals


def _should_reap(
    dead_signals: list[str],
    anti_reap_signals: list[str],
    quiet_for: int | None,
    detached_rebuild_stale: bool,
) -> bool:
    if not dead_signals or anti_reap_signals:
        return False
    if detached_rebuild_stale and "detached_control_plane_rebuild" in dead_signals:
        return True
    return (
        quiet_for is not None
        and quiet_for >= _REAPABLE_AFTER_SECONDS
        and any(s in _STRONG_DEAD_SIGNALS for s in dead_signals)
    )


def _compute_dead_signals_and_state(
    session: Session,
    response: dict[str, Any],
    quiet_for: int | None,
    phase: str,
    last_heartbeat_age: int | None,
    is_restart_cmd: bool,
    detached_rebuild_stale: bool,
    anti_reap_signals: list[str],
) -> tuple[list[str], str]:
    dead_signals: list[str] = []
    state = str(response.get("health") or response.get("status") or "idle")

    if session.status != "active":
        return dead_signals, state

    last_event_type = str(response.get("last_event_type") or "")
    if quiet_for is not None and quiet_for >= _DEAD_CANDIDATE_AFTER_SECONDS:
        dead_signals.append("no_model_activity_30m")
    if phase == "unknown" and quiet_for is not None and quiet_for >= _NO_ACTIVITY_STALL_AFTER_SECONDS:
        dead_signals.append("no_structured_activity")
    if last_event_type == "heartbeat" and quiet_for is not None and quiet_for >= _DEAD_CANDIDATE_AFTER_SECONDS:
        dead_signals.append("heartbeat_only")
    if response.get("termination_reason"):
        dead_signals.append("termination_signal")
    if is_restart_cmd:
        dead_signals.append("detached_control_plane_rebuild")
    if last_heartbeat_age is None and quiet_for is not None and quiet_for >= _REAPABLE_AFTER_SECONDS:
        dead_signals.append("heartbeat_missing")
    elif last_heartbeat_age is not None and last_heartbeat_age >= _REAPABLE_AFTER_SECONDS:
        dead_signals.append("heartbeat_absent_6h")

    if dead_signals:
        state = "dead_candidate"
    if _should_reap(dead_signals, anti_reap_signals, quiet_for, detached_rebuild_stale):
        state = "reapable"

    return dead_signals, state


def _apply_lifecycle_state(
    session: Session,
    response: dict[str, Any],
    *,
    has_owner_lane: bool,
    has_specialist_lane: bool,
    last_heartbeat_age: int | None,
) -> None:
    quiet_for_seconds = response.get("quiet_for_seconds")
    quiet_for = quiet_for_seconds if isinstance(quiet_for_seconds, int) else None
    phase = str(response.get("phase") or "unknown")

    cmd = response.get("last_command")
    is_restart_cmd = isinstance(cmd, str) and any(
        token in " ".join(cmd.lower().split()) for token in _DETACHED_AGENT_HUB_RESTART_TOKENS
    )
    detached_rebuild_stale = (
        not has_owner_lane
        and quiet_for is not None
        and quiet_for >= _DEAD_CANDIDATE_AFTER_SECONDS
        and int(response.get("outstanding_tool_calls") or 0) == 0
        and is_restart_cmd
    )

    anti_reap_signals = _compute_anti_reap_signals(
        response, has_owner_lane, has_specialist_lane, detached_rebuild_stale, phase, quiet_for,
    )
    dead_signals, state = _compute_dead_signals_and_state(
        session, response, quiet_for, phase, last_heartbeat_age,
        is_restart_cmd, detached_rebuild_stale, anti_reap_signals,
    )
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
