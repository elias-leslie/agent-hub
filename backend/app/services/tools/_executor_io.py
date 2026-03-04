"""I/O and orchestration tool implementations for DirectToolExecutor.

Handles push notifications and task orchestration via CLI.
"""

from __future__ import annotations

import json
import logging
import shlex
import tempfile
from collections.abc import Awaitable, Callable

logger = logging.getLogger(__name__)


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


def _st_cmd(subcommand: str, project_id: str | None = None) -> str:
    """Build st CLI command with -P flag in correct position (before subcommand).

    Click/Typer requires parent options BEFORE the subcommand name.
    Wrong: st create "title" -P monkey-fight  (Error: No such option)
    Right: st -P monkey-fight create "title"
    """
    if project_id:
        return f"st -P {shlex.quote(project_id)} {subcommand}"
    return f"st {subcommand}"


def _build_plan_json(
    title: str,
    objective: str | None,
    description: str | None,
    spirit_anti: str | None,
    done_when: list[str] | None,
    labels: str | None,
    complexity: str | None,
    subtasks: list[dict[str, object]] | None = None,
) -> str:
    """Write a plan JSON to a temp file and return its path."""
    plan: dict[str, object] = {
        "title": title,
        "objective": objective or title,
        "complexity": complexity or "STANDARD",
        "autonomous": True,
    }
    if description:
        plan["description"] = description
    if spirit_anti:
        plan["spirit_anti"] = spirit_anti
    if done_when:
        plan["done_when"] = done_when
    if labels:
        plan["labels"] = labels.split(",")
    if subtasks:
        plan["subtasks"] = subtasks

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, prefix="st-plan-"
    ) as f:
        json.dump(plan, f)
        return f.name


async def _handle_create(
    bash_fn: Callable[..., Awaitable[str]],
    title: str,
    description: str | None,
    priority: int,
    task_type: str,
    labels: str | None,
    project_id: str | None,
    objective: str | None,
    spirit_anti: str | None,
    done_when: list[str] | None,
    complexity: str | None,
    subtasks: list[dict[str, object]] | None = None,
) -> str:
    """Handle task creation — plan-based or basic."""
    if objective or done_when or subtasks:
        tmpfile = _build_plan_json(
            title, objective, description, spirit_anti, done_when, labels, complexity,
            subtasks=subtasks,
        )
        cmd = _st_cmd(f"create --plan {shlex.quote(tmpfile)}", project_id)
        logger.info("manage_tasks create via plan: %s", cmd)
        return await bash_fn(cmd)

    sub = f"create {shlex.quote(title)} -t {shlex.quote(task_type)} -p {priority}"
    if description:
        sub += f" -d {shlex.quote(description)}"
    if labels:
        sub += f" -l {shlex.quote(labels)}"
    cmd = _st_cmd(sub, project_id)
    logger.info("manage_tasks create: %s", cmd)
    return await bash_fn(cmd)


async def _build_dispatch_warning(
    bash_fn: Callable[..., Awaitable[str]],
    project_id: str | None,
) -> str:
    """Return a warning string if tasks are already running, else empty string."""
    try:
        running_json = await bash_fn(
            _st_cmd("list --status running --json", project_id)
        )
        running: list[dict[str, str]] = (
            json.loads(running_json) if running_json.strip() else []
        )
        if not running:
            return ""
        ids = ", ".join(t.get("id", "?") for t in running[:5])
        project_label = f" in {project_id}" if project_id else ""
        return (
            f"WARNING: {len(running)} task(s) already running"
            f"{project_label}: {ids}. "
            "Risk of merge conflicts.\n\n"
        )
    except Exception:
        return ""  # Never block dispatch on warning failure


async def _handle_dispatch(
    bash_fn: Callable[..., Awaitable[str]],
    task_id: str,
    project_id: str | None,
) -> str:
    """Dispatch a task via autocode, prefixed with any running-task warning."""
    warning = await _build_dispatch_warning(bash_fn, project_id)
    result = await bash_fn(_st_cmd(f"autocode {shlex.quote(task_id)}", project_id))
    return warning + result


async def manage_tasks(
    bash_fn: Callable[..., Awaitable[str]],
    action: str,
    task_id: str | None = None,
    title: str | None = None,
    description: str | None = None,
    priority: int = 2,
    task_type: str = "task",
    labels: str | None = None,
    project_id: str | None = None,
    objective: str | None = None,
    spirit_anti: str | None = None,
    done_when: list[str] | None = None,
    complexity: str | None = None,
    subtasks: list[dict[str, object]] | None = None,
) -> str:
    """Quick task operations via st CLI."""
    if action == "list_ready":
        return await bash_fn(_st_cmd("ready", project_id))

    if action == "list_active":
        return await bash_fn(_st_cmd("list --status running,queue --json", project_id))

    if action == "get_context":
        if not task_id:
            return "Error: task_id required for get_context"
        return await bash_fn(_st_cmd(f"context {shlex.quote(task_id)}", project_id))

    if action == "create":
        if not title:
            return "Error: title required for create"
        return await _handle_create(
            bash_fn, title, description, priority, task_type,
            labels, project_id, objective, spirit_anti, done_when, complexity,
            subtasks=subtasks,
        )

    if action == "dispatch":
        if not task_id:
            return "Error: task_id required for dispatch"
        return await _handle_dispatch(bash_fn, task_id, project_id)

    return f"Error: Unknown action '{action}'. Use list_ready/get_context/create/dispatch."
