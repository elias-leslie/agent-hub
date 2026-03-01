"""Data-fetching helpers for the heartbeat prompt."""

from __future__ import annotations

import json
import logging
import subprocess
from datetime import UTC, datetime

logger = logging.getLogger(__name__)


async def get_project_access_summary() -> str:
    """Build a summary of project access tiers for the heartbeat prompt."""
    from sqlalchemy import text

    from app.db import async_session

    try:
        async with async_session() as db:
            result = await db.execute(
                text(
                    "SELECT project_id, permission_tier, auto_exec_enabled"
                    " FROM project_permissions ORDER BY project_id"
                )
            )
            rows = result.fetchall()
    except Exception:
        logger.exception("Failed to fetch project access summary")
        return "Your project access: (unavailable)"

    if not rows:
        return "Your project access: (no projects configured)"

    lines = ["Your project access:"]
    for row in rows:
        auto = "auto-exec" if row.auto_exec_enabled else "manual"
        lines.append(f"- {row.project_id}: {row.permission_tier} ({auto})")
    return "\n".join(lines)


async def _get_recent_journal_types(limit: int = 5) -> str:
    """Return comma-separated list of recent journal entry types."""
    try:
        from datetime import timedelta

        from app.services.memory.repository import get_memory_repository

        repo = get_memory_repository()
        since = datetime.now(UTC) - timedelta(days=7)
        memories = await repo.list_by_scope_and_tier(
            scope="agent:persona",
            memory_type="journal",
            status="active",
            since=since,
            order_by="created_at",
            limit=limit,
        )
        types = [(m.metadata_ or {}).get("entry_type", "observation") for m in memories]
        return ", ".join(types) if types else "(none yet)"
    except Exception:
        logger.exception("Failed to fetch recent journal types")
        return "(unavailable)"


def _get_persona_tool_summary() -> tuple[int, str]:
    """Return (count, comma-separated list) of persona-specific tool names."""
    try:
        from app.services.tools._persona_tools import PERSONA_EXTRA_TOOLS

        names = [t.name for t in PERSONA_EXTRA_TOOLS]
        return len(names), ", ".join(names)
    except Exception:
        logger.exception("Failed to list persona tools")
        return 0, "(unavailable)"


def _format_task_line(task: dict[str, object]) -> str:
    """Format a single task dict into a summary line."""
    tid = task.get("id", "?")
    title = task.get("title", "untitled")
    status = task.get("status", "?")
    phase = task.get("phase", "?")
    proj = task.get("project_id", "")
    proj_suffix = f" ({proj})" if proj else ""
    return f"- [{status}/{phase}] {tid}: {title}{proj_suffix}"


def _fetch_running_tasks_section() -> str:
    """Return a formatted section string for running/queued tasks, or empty string."""
    try:
        proc = subprocess.run(
            ["st", "list", "--status", "running,queue", "--json"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        tasks: list[dict[str, object]] = (
            json.loads(proc.stdout) if proc.stdout.strip() else []
        )
        if not tasks:
            return ""
        lines = [f"Running/queued tasks: {len(tasks)}"]
        lines.extend(_format_task_line(t) for t in tasks[:10])
        return "\n".join(lines)
    except Exception:
        logger.debug("Failed to fetch active tasks for heartbeat prompt", exc_info=True)
        return ""


def _format_session_line(session: dict[str, object]) -> str:
    """Format a single session dict into a summary line."""
    agent = session.get("agent_slug", "session")
    project = session.get("project_id", "unknown")
    parts: list[str] = []
    if session.get("external_id"):
        parts.append(str(session["external_id"]))
    if session.get("current_branch"):
        parts.append(f"branch: {session['current_branch']}")
    fc = session.get("touched_file_count", 0)
    if fc:
        parts.append(f"files: {fc}")
    detail = ", ".join(parts) if parts else f"{session.get('event_count', 0)} events"
    return f"- {agent} on {project}, {detail}"


async def _fetch_active_sessions_section() -> str:
    """Return a formatted section string for active sessions, or empty string."""
    try:
        from app.db import async_session
        from app.services.memory.continuity_query import query_active_sessions

        async with async_session() as db:
            sessions: list[dict[str, object]] = await query_active_sessions(
                db, max_entries=5
            )

        if not sessions:
            return ""
        lines = [f"Active agent sessions: {len(sessions)}"]
        lines.extend(_format_session_line(s) for s in sessions)
        return "\n".join(lines)
    except Exception:
        logger.debug("Failed to fetch active sessions for heartbeat prompt", exc_info=True)
        return ""


async def _get_active_work_summary() -> str:
    """Build an <active_work> XML block with running tasks and live sessions."""
    tasks_section = _fetch_running_tasks_section()
    sessions_section = await _fetch_active_sessions_section()

    sections = [s for s in (tasks_section, sessions_section) if s]

    if not sections:
        logger.info("Active work summary: empty (no running tasks or sessions)")
        return ""

    body = "\n\n".join(sections)
    logger.info("Active work summary: %d section(s), %d chars", len(sections), len(body))
    return f"\n<active_work>\n{body}\n</active_work>"


__all__ = [
    "_fetch_active_sessions_section",
    "_fetch_running_tasks_section",
    "_format_session_line",
    "_format_task_line",
    "_get_active_work_summary",
    "_get_persona_tool_summary",
    "_get_recent_journal_types",
    "get_project_access_summary",
]
