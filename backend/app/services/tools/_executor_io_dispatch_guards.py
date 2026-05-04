"""Dispatch guard helpers for DirectToolExecutor task actions."""

from __future__ import annotations

import json
import logging
import shlex
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from app.services.ownership_lanes import (
    STALE_WORKSTREAM_IDLE_MINUTES,
    idle_minutes_from_timestamps,
)
from app.services.tools._executor_io_cleanup import (
    _cleanup_dispatch_block_reason,
    _cleanup_finalize_warning,
)
from app.services.tools._tool_constants import st_cmd as _st_cmd

logger = logging.getLogger(__name__)

_CANONICAL_TASK_ID_PREFIX = "task-"
_STATUS_RUNNING = "running"
_STATUS_ACTIVE = "active"
_PERMISSION_TIER_OFF = "off"
_PERMISSION_MODE_AUTO = "auto-exec"
_PERMISSION_MODE_MANUAL = "manual"


def _running_task_warning(running: list[dict[str, str]], project_id: str | None) -> str | None:
    """Return warning text for already-running tasks."""
    if not running:
        return None
    project_label = f" in {project_id}" if project_id else ""
    ids = ", ".join(task.get("id", "?") for task in running[:5])
    return (
        f"WARNING: {len(running)} task(s) already running{project_label}: {ids}. "
        "Risk of merge conflicts."
    )


async def _build_dispatch_warning(
    bash_fn: Callable[..., Awaitable[str]],
    project_id: str | None,
    cleanup_status: str | None = None,
) -> str:
    """Return warning string if tasks are already running, else empty string."""
    try:
        warnings: list[str] = []
        running_json = await bash_fn(_st_cmd(f"list --status {_STATUS_RUNNING} --json", project_id))
        running: list[dict[str, str]] = json.loads(running_json) if running_json.strip() else []
        if running_warning := _running_task_warning(running, project_id):
            warnings.append(running_warning)
        if project_id:
            current_cleanup_status = cleanup_status or await bash_fn(_st_cmd("cleanup status", project_id))
            if finalize_warning := _cleanup_finalize_warning(current_cleanup_status):
                warnings.append(finalize_warning)
        return "\n\n".join(warnings) + ("\n\n" if warnings else "")
    except Exception:
        return ""


def _active_session_block_message(
    task_id: str,
    active_sessions: list[object],
    freshest_idle: float,
    task_detail: str,
) -> str:
    """Return block message for already-active same-task session."""
    count = len(active_sessions)
    if freshest_idle < STALE_WORKSTREAM_IDLE_MINUTES:
        return (
            f"Dispatch blocked for {task_id}: same task already has {count} "
            f"active session(s){task_detail} with fresh progress ({freshest_idle}m idle). "
            "Wait or monitor the current lane instead of redispatching."
        )
    return (
        f"Dispatch blocked for {task_id}: same task still has {count} "
        f"stale active session(s){task_detail} ({freshest_idle}m idle). "
        "Inspect or reconcile the current lane before dispatching again."
    )


def _running_task_block_message(task_id: str, task_detail: str, has_recent_activity: bool) -> str:
    """Return block message for running task with or without recent activity."""
    if has_recent_activity:
        return (
            f"Dispatch blocked for {task_id}: task is already running and shows recent "
            "autonomous activity. Wait or inspect the current lane instead of redispatching."
        )
    return (
        f"Dispatch blocked for {task_id}: task is already running{task_detail} without fresh "
        "session evidence. Inspect or reconcile the current lane before dispatching again."
    )


async def _active_session_idle_minutes(active_sessions: list[object]) -> float:
    """Return freshest idle minutes across active sessions."""
    now = datetime.now(UTC)
    return min(
        idle_minutes_from_timestamps(
            created_at=getattr(session, "created_at", None),
            updated_at=getattr(session, "updated_at", None),
            workstream_updated_at=getattr(session, "workstream_updated_at", None),
            now=now,
        )
        for session in active_sessions
    )


async def _live_dispatch_block_reason(
    bash_fn: Callable[..., Awaitable[str]],
    task_id: str,
    project_id: str | None,
) -> str | None:
    """Return blocking reason when same-task live state says wait or reconcile."""
    if not project_id or not task_id.startswith(_CANONICAL_TASK_ID_PREFIX):
        return None

    from ._executor_io_lanes import (
        _get_task_status,
        _has_recent_execution_activity,
        _load_task_lane_sessions,
    )

    task_status = await _get_task_status(bash_fn, task_id, project_id)
    sessions = await _load_task_lane_sessions(task_id)
    active_sessions = [session for session in sessions if getattr(session, "status", None) == _STATUS_ACTIVE]
    task_detail = f" (task={task_status})" if task_status else ""

    if active_sessions:
        freshest_idle = await _active_session_idle_minutes(active_sessions)
        return _active_session_block_message(task_id, active_sessions, freshest_idle, task_detail)
    if task_status == _STATUS_RUNNING:
        has_recent = await _has_recent_execution_activity(bash_fn, task_id, project_id)
        return _running_task_block_message(task_id, task_detail, has_recent)
    return None


def _permission_access_label(permission: Any) -> str:
    """Return permission label used in dispatch-block message."""
    mode = _PERMISSION_MODE_AUTO if permission.auto_exec_enabled else _PERMISSION_MODE_MANUAL
    return f"{permission.permission_tier}/{mode}"


def _permission_detail(permission: Any) -> str:
    """Return reason detail for blocked execution permission."""
    if permission.permission_tier == _PERMISSION_TIER_OFF:
        return "project access is off"
    if not permission.auto_exec_enabled:
        return "project is observe-only for autonomous execution"
    if not permission.in_time_window:
        return "project is outside its execution window"
    return f"execution permission check returned {permission.reason}"


async def _dispatch_permission_block_reason(project_id: str | None) -> str | None:
    """Return blocking reason when project access disallows autonomous dispatch."""
    if not project_id:
        return None

    from app.db import async_session
    from app.services.tools import _executor_io_tasks as task_helpers

    async with async_session() as db:
        permission = await task_helpers.check_execution_permission(db, project_id)

    valid_payload = all(
        (
            isinstance(permission.allowed, bool),
            isinstance(permission.permission_tier, str),
            isinstance(permission.auto_exec_enabled, bool),
            isinstance(permission.in_time_window, bool),
        )
    )
    if not valid_payload:
        logger.debug(
            "Skipping dispatch permission gate for %s due to invalid permission payload: %r",
            project_id,
            permission,
        )
        return None
    if permission.allowed:
        return None

    return (
        f"Dispatch blocked: project {project_id} is {_permission_access_label(permission)}; "
        f"{_permission_detail(permission)}. "
        "Read/manual projects are observe-only during heartbeat unless access changes."
    )


async def _handle_dispatch(
    bash_fn: Callable[..., Awaitable[str]],
    task_id: str,
    project_id: str | None,
) -> str:
    """Dispatch task via autocode, prefixed with any running-task warning."""
    from app.services.tools import _executor_io_tasks as task_helpers

    if permission_block := await _dispatch_permission_block_reason(project_id):
        return permission_block
    cleanup_block, cleanup_status = await _cleanup_dispatch_block_reason(
        bash_fn,
        project_id,
        use_live_ownership=False,
    )
    if cleanup_block:
        return cleanup_block
    if live_block := await task_helpers._live_dispatch_block_reason(bash_fn, task_id, project_id):
        return live_block
    warning = await task_helpers._build_dispatch_warning(bash_fn, project_id, cleanup_status=cleanup_status)
    result = await bash_fn(_st_cmd(f"autocode {shlex.quote(task_id)}", project_id))
    return warning + result


__all__ = [
    "_build_dispatch_warning",
    "_handle_dispatch",
    "_live_dispatch_block_reason",
]
