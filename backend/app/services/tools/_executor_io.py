"""I/O and orchestration tool implementations for DirectToolExecutor.

Handles push notifications and task orchestration via CLI.
"""

from __future__ import annotations

import logging
import shlex
from collections.abc import Awaitable, Callable

from app.services.task_overview_summary import build_actionable_ready_summary

from ._executor_io_lanes import (
    _handle_lane_action,
    _handle_simple_task_action,
    _load_task_lane_sessions,
    _st_cmd,
)
from ._executor_io_tasks import (
    _handle_cleanup_all_safe,
    _handle_cleanup_checkpoints,
    _handle_cleanup_salvage_orphan,
    _handle_cleanup_status,
    _handle_create,
    _handle_dispatch,
    _handle_resolve_conflict,
)

logger = logging.getLogger(__name__)

_SIMPLE_TASK_ACTIONS = frozenset({"done", "abandon", "cancel"})
_UNKNOWN_ACTIONS = (
    "overview/get_context/create/dispatch/cleanup_status/cleanup_checkpoints/"
    "salvage_orphan/cleanup_all_safe/resolve_conflict/"
    "reconcile/retire_lane/done/abandon/cancel"
)


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


async def _handle_overview(bash_fn: Callable[..., Awaitable[str]]) -> str:
    """Return ready summary plus actionable summary when available."""
    overview = await bash_fn("st ready-all")
    actionable = build_actionable_ready_summary(overview)
    return f"{overview}\n\n{actionable}" if actionable else overview


async def _handle_get_context(
    bash_fn: Callable[..., Awaitable[str]],
    action: str,
    task_id: str | None,
    project_id: str | None,
) -> str:
    """Return task context or missing-task error."""
    if not task_id:
        return f"Error: task_id required for {action}"
    return await bash_fn(_st_cmd(f"context {shlex.quote(task_id)}", project_id))


async def _handle_create_action(
    bash_fn: Callable[..., Awaitable[str]],
    title: str | None,
    description: str | None,
    priority: int,
    task_type: str,
    labels: str | None,
    project_id: str | None,
    done_when: list[str] | None,
    complexity: str | None,
    objective: str | None,
    constraints: list[str] | None,
    spirit_anti: str | None,
    testing_strategy: str | None,
    context: dict[str, object] | None,
    subtasks: list[dict[str, object]] | None,
) -> str:
    """Create task while preserving existing plan payload behavior."""
    if not title:
        return "Error: title required for create"
    return await _handle_create(
        bash_fn,
        title,
        description,
        priority,
        task_type,
        labels,
        project_id,
        done_when,
        complexity,
        objective=objective,
        constraints=constraints,
        spirit_anti=spirit_anti,
        testing_strategy=testing_strategy,
        context=context,
        subtasks=subtasks,
    )


async def _handle_project_action(
    bash_fn: Callable[..., Awaitable[str]],
    action: str,
    project_id: str | None,
    task_id: str | None,
) -> str | None:
    """Handle project-scoped cleanup and sync actions."""
    if action == "cleanup_status":
        return await _handle_cleanup_status(bash_fn, project_id)
    if action == "cleanup_checkpoints":
        return await _handle_cleanup_checkpoints(bash_fn, project_id)
    if action == "salvage_orphan":
        return await _handle_cleanup_salvage_orphan(bash_fn, task_id, project_id)
    if action == "cleanup_all_safe":
        return await _handle_cleanup_all_safe(bash_fn)
    if action == "resolve_conflict":
        return await _handle_resolve_conflict(bash_fn, task_id, project_id)
    return None


async def _handle_task_action(
    bash_fn: Callable[..., Awaitable[str]],
    action: str,
    task_id: str | None,
    project_id: str | None,
) -> str | None:
    """Handle task and lane actions needing existing task semantics."""
    if action == "dispatch":
        return (
            f"Error: task_id required for {action}"
            if not task_id
            else await _handle_dispatch(bash_fn, task_id, project_id)
        )
    if action in {"reconcile", "retire_lane"}:
        return await _handle_lane_action(bash_fn, action, task_id, project_id)
    if action in _SIMPLE_TASK_ACTIONS:
        return await _handle_simple_task_action(bash_fn, action, task_id, project_id)
    return None


def _unknown_action_message(action: str) -> str:
    """Return stable unknown-action error text."""
    return f"Error: Unknown action '{action}'. Use {_UNKNOWN_ACTIONS}."


async def manage_tasks(
    bash_fn: Callable[..., Awaitable[str]], action: str,
    task_id: str | None = None, title: str | None = None,
    description: str | None = None, priority: int = 2, task_type: str = "task",
    labels: str | None = None, project_id: str | None = None,
    done_when: list[str] | None = None, complexity: str | None = None,
    objective: str | None = None, constraints: list[str] | None = None,
    spirit_anti: str | None = None, testing_strategy: str | None = None,
    context: dict[str, object] | None = None,
    subtasks: list[dict[str, object]] | None = None,
) -> str:
    """Quick task operations via st CLI."""
    if action == "overview":
        return await _handle_overview(bash_fn)
    if action == "get_context":
        return await _handle_get_context(bash_fn, action, task_id, project_id)
    if action == "create":
        return await _handle_create_action(
            bash_fn,
            title,
            description,
            priority,
            task_type,
            labels,
            project_id,
            done_when,
            complexity,
            objective,
            constraints,
            spirit_anti,
            testing_strategy,
            context,
            subtasks,
        )

    project_result = await _handle_project_action(bash_fn, action, project_id, task_id)
    if project_result is not None:
        return project_result

    task_result = await _handle_task_action(bash_fn, action, task_id, project_id)
    if task_result is not None:
        return task_result
    return _unknown_action_message(action)


__all__ = ["_load_task_lane_sessions", "manage_tasks", "send_push"]
