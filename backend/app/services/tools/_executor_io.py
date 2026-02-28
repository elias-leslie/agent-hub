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


def _build_project_flag(project_id: str | None) -> str:
    """Build -P flag for st commands."""
    if not project_id:
        return ""
    return f" -P {shlex.quote(project_id)}"


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
) -> str:
    """Quick task operations via st CLI."""
    pflag = _build_project_flag(project_id)

    if action == "list_ready":
        return await bash_fn(f"st ready{pflag}")

    if action == "get_context":
        if not task_id:
            return "Error: task_id required for get_context"
        return await bash_fn(f"st context {shlex.quote(task_id)}{pflag}")

    if action == "create":
        if not title:
            return "Error: title required for create"

        # If spirit fields present, build a plan JSON and use --plan
        if objective or done_when:
            plan = {
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

            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".json", delete=False, prefix="st-plan-"
            ) as f:
                json.dump(plan, f)
                tmpfile = f.name

            cmd = f"st create --plan {shlex.quote(tmpfile)}{pflag}"
            logger.info("manage_tasks create via plan: %s", cmd)
            return await bash_fn(cmd)

        # Basic creation
        cmd = f"st create {shlex.quote(title)} -t {shlex.quote(task_type)} -p {priority}"
        if description:
            cmd += f" -d {shlex.quote(description)}"
        if labels:
            cmd += f" -l {shlex.quote(labels)}"
        cmd += pflag
        logger.info("manage_tasks create: %s", cmd)
        return await bash_fn(cmd)

    if action == "dispatch":
        if not task_id:
            return "Error: task_id required for dispatch"
        return await bash_fn(f"st autocode {shlex.quote(task_id)}{pflag}")

    return f"Error: Unknown action '{action}'. Use list_ready/get_context/create/dispatch."
