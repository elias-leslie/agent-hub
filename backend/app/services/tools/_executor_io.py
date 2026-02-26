"""I/O and orchestration tool implementations for DirectToolExecutor.

Handles push notifications and task orchestration via CLI.
"""

from __future__ import annotations

import logging
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


async def manage_tasks(
    bash_fn: Callable[..., Awaitable[str]],
    action: str,
    task_id: str | None = None,
    title: str | None = None,
    description: str | None = None,
    priority: int = 2,
    task_type: str = "task",
    labels: str | None = None,
) -> str:
    """Quick task operations via st CLI."""
    if action == "list_ready":
        return await bash_fn("st ready")

    if action == "get_context":
        if not task_id:
            return "Error: task_id required for get_context"
        return await bash_fn(f"st context {task_id}")

    if action == "create":
        if not title:
            return "Error: title required for create"
        cmd = f"st create '{title}' -t {task_type} -p {priority}"
        if description:
            cmd += f" -d '{description}'"
        if labels:
            cmd += f" -l '{labels}'"
        logger.info("manage_tasks create: %s", cmd)
        return await bash_fn(cmd)

    if action == "dispatch":
        if not task_id:
            return "Error: task_id required for dispatch"
        return await bash_fn(f"st autocode {task_id}")

    return f"Error: Unknown action '{action}'. Use list_ready/get_context/create/dispatch."
