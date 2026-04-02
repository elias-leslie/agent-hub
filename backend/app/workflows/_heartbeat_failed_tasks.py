"""Heartbeat failed-tasks section builder.

Helpers for formatting and rendering the recent-failed-tasks heartbeat section.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from app.workflows._heartbeat_state import SummitFlowHeartbeatState

logger = logging.getLogger(__name__)


def _format_recent_failed_task_age(last_changed_at: object, *, now: datetime) -> str:
    """Format one failed-task timestamp for heartbeat display."""
    if not isinstance(last_changed_at, datetime):
        return "unknown"
    normalized = (
        last_changed_at.replace(tzinfo=UTC)
        if last_changed_at.tzinfo is None
        else last_changed_at.astimezone(UTC)
    )
    minutes = max(int((now - normalized).total_seconds() / 60), 0)
    if minutes < 60:
        return f"{minutes}m ago"
    hours = minutes // 60
    return f"{hours}h ago" if hours < 24 else f"{hours // 24}d ago"


def _render_failed_task_line(task: dict[str, object], *, now: datetime) -> str:
    """Render one failed task as a single display line."""
    project_id = str(task.get("project_id") or "unknown")
    task_id = str(task.get("id") or "unknown")
    title = str(task.get("title") or "Untitled task")
    phase = str(task.get("current_phase") or "").strip()
    error_message = str(task.get("error_message") or "").strip()
    details = [
        project_id,
        task_id,
        "failed",
        _format_recent_failed_task_age(task.get("last_changed_at"), now=now),
    ]
    if phase:
        details.append(f"phase={phase}")
    line = f"- {' | '.join(details)} | {title}"
    if error_message:
        line += f" | error={error_message}"
    return line


def _render_failed_tasks_follow_first(top_task: dict[str, object], *, now: datetime) -> str:
    """Render the 'Follow first' line for the top failed task."""
    project_id = str(top_task.get("project_id") or "unknown")
    task_id = str(top_task.get("id") or "unknown")
    title = str(top_task.get("title") or "Untitled task")
    phase = str(top_task.get("current_phase") or "").strip()
    details = [
        project_id,
        task_id,
        "failed",
        _format_recent_failed_task_age(top_task.get("last_changed_at"), now=now),
    ]
    if phase:
        details.append(f"phase={phase}")
    return f"Follow first: {' | '.join(details)} | {title}"


async def _get_recent_failed_tasks_summary(
    target_project_id: str | None = None,
    *,
    heartbeat_state: SummitFlowHeartbeatState | None = None,
) -> str:
    """Build a heartbeat section listing recent failed tasks that still need recovery."""
    from app.workflows._heartbeat_data import _fetch_recent_failed_tasks

    try:
        failed_tasks = (
            heartbeat_state.recent_failed_tasks
            if heartbeat_state is not None
            else await _fetch_recent_failed_tasks(target_project_id)
        )
        if not failed_tasks:
            return ""
        now = datetime.now(UTC)
        lines = [f"Recent failed tasks: {len(failed_tasks)}"]
        lines.append(_render_failed_tasks_follow_first(failed_tasks[0], now=now))
        lines.extend(_render_failed_task_line(task, now=now) for task in failed_tasks)
        return f"\n<recent_failed_tasks>\n{chr(10).join(lines)}\n</recent_failed_tasks>"
    except Exception:
        logger.debug("Failed to build recent failed tasks summary for heartbeat", exc_info=True)
        return ""
