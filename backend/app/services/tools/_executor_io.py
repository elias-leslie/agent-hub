"""I/O and orchestration tool implementations for DirectToolExecutor.

Handles push notifications and task orchestration via CLI.
"""

from __future__ import annotations

import logging
import shlex
from collections.abc import Awaitable, Callable

from app.services.task_overview_summary import build_actionable_ready_summary

from ._executor_io_lanes import (
    _load_task_lane_sessions,
    _reconcile_task_lane,
    _retire_task_lane,
    _st_cmd,
)
from ._executor_io_tasks import (
    _handle_cleanup_all_safe,
    _handle_cleanup_salvage_orphan,
    _handle_cleanup_status,
    _handle_cleanup_worktrees,
    _handle_create,
    _handle_dispatch,
    _handle_finalize_merge,
    _handle_resolve_conflict,
    _handle_smart_sync,
)

logger = logging.getLogger(__name__)

_SIMPLE_TASK_ACTIONS = frozenset({"done", "abandon", "cancel"})


async def send_push(
    title: str,
    body: str,
    url: str | None = None,
    severity: str = "info",
    tag: str | None = None,
) -> str:
    """Send a push notification to all subscribed devices."""
    try:
        from app.db import async_session
        from app.services.push_service import send_push as _send_push

        payload: dict[str, str | None] = {"title": title, "body": body}
        if url:
            payload["url"] = url
        if severity:
            payload["severity"] = severity
        if tag:
            payload["tag"] = tag

        async with async_session() as db:
            sent = await _send_push(db, payload=payload)

        return f"Push notification sent to {sent} device(s): {title}"
    except Exception as e:
        logger.exception("send_push failed")
        return f"Error sending push notification: {e}"


def _require_task_id(action: str, task_id: str | None) -> str | None:
    """Return an error string if task_id is missing, else None."""
    if not task_id:
        return f"Error: task_id required for {action}"
    return None


async def manage_tasks(
    bash_fn: Callable[..., Awaitable[str]], action: str,
    task_id: str | None = None, title: str | None = None,
    description: str | None = None, priority: int = 2, task_type: str = "task",
    labels: str | None = None, project_id: str | None = None,
    objective: str | None = None, spirit_anti: str | None = None,
    done_when: list[str] | None = None, complexity: str | None = None,
    subtasks: list[dict[str, object]] | None = None,
) -> str:
    """Quick task operations via st CLI."""
    if action == "overview":
        overview = await bash_fn("st ready-all")
        actionable = build_actionable_ready_summary(overview)
        return f"{overview}\n\n{actionable}" if actionable else overview
    if action == "get_context":
        err = _require_task_id(action, task_id)
        return err if err else await bash_fn(_st_cmd(f"context {shlex.quote(task_id)}", project_id))  # type: ignore[arg-type]
    if action == "create":
        if not title:
            return "Error: title required for create"
        return await _handle_create(
            bash_fn, title, description, priority, task_type,
            labels, project_id, objective, spirit_anti, done_when, complexity,
            subtasks=subtasks,
        )
    if action == "dispatch":
        err = _require_task_id(action, task_id)
        return err if err else await _handle_dispatch(bash_fn, task_id, project_id)  # type: ignore[arg-type]
    if action == "cleanup_status":
        return await _handle_cleanup_status(bash_fn, project_id)
    if action == "cleanup_worktrees":
        return await _handle_cleanup_worktrees(bash_fn, project_id)
    if action == "salvage_orphan":
        return await _handle_cleanup_salvage_orphan(bash_fn, task_id, project_id)
    if action == "cleanup_all_safe":
        return await _handle_cleanup_all_safe(bash_fn)
    if action == "smart_sync":
        return await _handle_smart_sync(bash_fn, project_id)
    if action == "finalize_merge":
        return await _handle_finalize_merge(bash_fn, task_id, project_id)
    if action == "resolve_conflict":
        return await _handle_resolve_conflict(bash_fn, task_id, project_id)
    if action in {"reconcile", "retire_lane"}:
        err = _require_task_id(action, task_id)
        if err: return err  # noqa: E701
        handler = _reconcile_task_lane if action == "reconcile" else _retire_task_lane
        return await handler(bash_fn, task_id, project_id)  # type: ignore[arg-type]
    if action in _SIMPLE_TASK_ACTIONS:
        err = _require_task_id(action, task_id)
        return err if err else await bash_fn(_st_cmd(f"{action} {shlex.quote(task_id)}", project_id))  # type: ignore[arg-type]
    return (
        f"Error: Unknown action '{action}'. "
        "Use overview/get_context/create/dispatch/cleanup_status/cleanup_worktrees/salvage_orphan/cleanup_all_safe/"
        "smart_sync/finalize_merge/resolve_conflict/reconcile/retire_lane/done/abandon/cancel."
    )


__all__ = ["_load_task_lane_sessions", "manage_tasks", "send_push"]
