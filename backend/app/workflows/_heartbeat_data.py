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
    """Build an <active_work> XML block with running tasks, sessions, failures, and backlog."""
    tasks_section = _fetch_running_tasks_section()
    sessions_section = await _fetch_active_sessions_section()

    sections = [s for s in (tasks_section, sessions_section) if s]

    if not sections:
        logger.info("Active work summary: empty (no running tasks or sessions)")
        return ""

    body = "\n\n".join(sections)
    logger.info("Active work summary: %d section(s), %d chars", len(sections), len(body))

    # Append failure and backlog sections (outside <active_work> as separate XML blocks)
    result = f"\n<active_work>\n{body}\n</active_work>"
    failed_section = _fetch_failed_work_section()
    backlog_section = _fetch_backlog_summary_section()
    if failed_section:
        result += failed_section
    if backlog_section:
        result += backlog_section
    return result


async def _get_agent_roster_summary() -> str:
    """Build an <agent_roster> XML block listing active agents with descriptions."""
    try:
        from app.db import async_session
        from app.services.agent_service import get_agent_service

        agent_service = get_agent_service()
        async with async_session() as db:
            agents = await agent_service.list_agents(db, active_only=True)

        if not agents:
            return ""

        lines = [
            f"- {a.slug}: {a.description or '(no description)'}"
            for a in agents
        ]
        body = "\n".join(lines)
        logger.info("Agent roster summary: %d agents", len(agents))
        return f"\n<agent_roster>\n{body}\n</agent_roster>"
    except Exception:
        logger.debug("Failed to fetch agent roster for heartbeat prompt", exc_info=True)
        return ""


def _fetch_recent_completions_section() -> str:
    """Fetch recently completed tasks across projects for the heartbeat digest."""
    from datetime import timedelta

    try:
        proc = subprocess.run(
            ["st", "list", "--status", "completed", "--json"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        tasks: list[dict[str, object]] = (
            json.loads(proc.stdout) if proc.stdout.strip() else []
        )
        if not tasks:
            return ""

        # Filter to tasks completed within the last 6 hours
        cutoff = datetime.now(UTC) - timedelta(hours=6)
        recent: list[dict[str, object]] = []
        for task in tasks:
            completed_at = task.get("completed_at") or task.get("updated_at")
            if not completed_at or not isinstance(completed_at, str):
                continue
            try:
                ts = datetime.fromisoformat(completed_at.replace("Z", "+00:00"))
                if ts >= cutoff:
                    recent.append(task)
            except (ValueError, TypeError):
                continue

        if not recent:
            return ""

        lines = [f"Recently completed tasks: {len(recent)}"]
        for task in recent[:10]:
            tid = task.get("id", "?")
            title = task.get("title", "untitled")
            proj = task.get("project_id", "")
            proj_suffix = f" ({proj})" if proj else ""
            lines.append(f"- {tid}: '{title}'{proj_suffix} — completed")
        return "\n".join(lines)
    except Exception:
        logger.debug(
            "Failed to fetch recent completions for heartbeat prompt", exc_info=True
        )
        return ""


def _fetch_failed_work_section() -> str:
    """Fetch abandoned, cancelled, and blocked tasks from last 24h."""
    from datetime import timedelta

    try:
        proc = subprocess.run(
            ["st", "list", "--status", "abandoned,cancelled,blocked", "--json"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        tasks: list[dict[str, object]] = (
            json.loads(proc.stdout) if proc.stdout.strip() else []
        )
        if not tasks:
            return ""

        cutoff = datetime.now(UTC) - timedelta(hours=24)
        recent: list[dict[str, object]] = []
        for task in tasks:
            updated_at = task.get("completed_at") or task.get("updated_at")
            if not updated_at or not isinstance(updated_at, str):
                recent.append(task)  # Include tasks without timestamps
                continue
            try:
                ts = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
                if ts >= cutoff:
                    recent.append(task)
            except (ValueError, TypeError):
                recent.append(task)

        if not recent:
            return ""

        lines: list[str] = []
        for task in recent[:15]:
            status = task.get("status", "?")
            tid = task.get("id", "?")
            title = task.get("title", "untitled")
            proj = task.get("project_id", "")
            error = task.get("error_message")
            error_suffix = f" — {error}" if error else " — no error recorded"
            lines.append(f"[{status}] {tid}: {title} ({proj}){error_suffix}")

        body = "\n".join(lines)
        return f"\n<failed_work>\n{body}\n</failed_work>"
    except Exception:
        logger.debug("Failed to fetch failed work for heartbeat", exc_info=True)
        return ""


def _fetch_backlog_summary_section() -> str:
    """Fetch pending and blocked task counts per project."""
    try:
        proc = subprocess.run(
            ["st", "list", "--status", "pending,blocked", "--json"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        tasks: list[dict[str, object]] = (
            json.loads(proc.stdout) if proc.stdout.strip() else []
        )
        if not tasks:
            return ""

        # Group by project and status
        project_counts: dict[str, dict[str, int]] = {}
        for task in tasks:
            proj = str(task.get("project_id", "unknown"))
            status = str(task.get("status", "unknown"))
            if proj not in project_counts:
                project_counts[proj] = {"pending": 0, "blocked": 0}
            if status in project_counts[proj]:
                project_counts[proj][status] += 1

        lines: list[str] = []
        for proj, counts in sorted(project_counts.items()):
            lines.append(
                f"{proj}: {counts['pending']} pending, {counts['blocked']} blocked"
            )

        body = "\n".join(lines)
        return f"\n<backlog_summary>\n{body}\n</backlog_summary>"
    except Exception:
        logger.debug("Failed to fetch backlog summary for heartbeat", exc_info=True)
        return ""


def _get_git_project_status(project_id: str, root_path: str) -> str | None:
    """Get git status summary for a single project. Returns formatted text or None."""
    sections: list[str] = []

    def _run(args: list[str]) -> str:
        try:
            proc = subprocess.run(
                args, capture_output=True, text=True, timeout=5, cwd=root_path,
            )
            return proc.stdout.strip()
        except (subprocess.TimeoutExpired, OSError):
            return ""

    # Uncommitted changes
    porcelain = _run(["git", "status", "--porcelain"])
    if porcelain:
        lines = porcelain.splitlines()[:10]
        sections.append(f"  uncommitted ({len(porcelain.splitlines())} files):\n" +
                        "\n".join(f"    {line}" for line in lines))

    # Recent commits with author
    log_output = _run([
        "git", "log", "--oneline", "--format=%h %s (%an)", "-n", "5",
    ])
    if log_output:
        sections.append("  recent commits:\n" +
                        "\n".join(f"    {line}" for line in log_output.splitlines()))

    # Active task worktree branches
    branches = _run(["git", "branch", "--list", "task-*"])
    if branches:
        branch_lines = [b.strip() for b in branches.splitlines()[:5]]
        sections.append("  task branches:\n" +
                        "\n".join(f"    {b}" for b in branch_lines))

    if not sections:
        return None

    return f"[{project_id}] ({root_path})\n" + "\n".join(sections)


def _get_git_status_summary() -> str:
    """Build a <git_state> XML block with git status for all known projects."""
    from app.constants.projects import get_known_roots

    roots = get_known_roots()
    if not roots:
        return ""

    project_sections: list[str] = []
    for project_id, root_path in sorted(roots.items()):
        try:
            section = _get_git_project_status(project_id, root_path)
            if section:
                project_sections.append(section)
        except Exception:
            logger.debug("Git status failed for %s", project_id, exc_info=True)

    if not project_sections:
        return ""

    body = "\n\n".join(project_sections)
    return f"\n<git_state>\n{body}\n</git_state>"


async def _get_feedback_summary_section() -> str:
    """Build a <feedback_summary> XML block with open feedback stats and top items."""
    try:
        from app.db import async_session
        from app.services.feedback_storage import get_feedback_summary

        async with async_session() as db:
            summary = await get_feedback_summary(db, days=30)

        total = summary.get("total_items", 0)
        top_items = summary.get("top_unresolved", [])

        if not top_items:
            return ""

        # Type breakdown from counts_by_type_status
        type_counts: dict[str, int] = {}
        for row in summary.get("counts_by_type_status", []):
            if row.get("status") == "open":
                ft = row.get("feedback_type", "unknown")
                type_counts[ft] = type_counts.get(ft, 0) + row.get("count", 0)

        open_count = sum(type_counts.values())
        if open_count == 0:
            return ""

        lines = [f"Open items: {open_count} (of {total} total, last 30d)"]

        if type_counts:
            breakdown = ", ".join(f"{k}: {v}" for k, v in sorted(type_counts.items()))
            lines.append(f"By type: {breakdown}")

        lines.append("")
        lines.append(f"{'ID':>8}  {'Type':<11}  {'Component':<20}  {'Votes':>5}  Title")
        lines.append("-" * 78)
        for item in top_items[:5]:
            short_id = str(item.id)[:8]
            lines.append(
                f"{short_id:>8}  {item.feedback_type:<11}  "
                f"{item.component_id:<20}  {item.vote_count:>5}  "
                f"{(item.title or '')[:40]}"
            )

        body = "\n".join(lines)
        logger.info("Feedback summary: %d open items", open_count)
        return f"\n<feedback_summary>\n{body}\n</feedback_summary>"
    except Exception:
        logger.debug("Failed to fetch feedback summary for heartbeat", exc_info=True)
        return ""


__all__ = [
    "_fetch_active_sessions_section",
    "_fetch_backlog_summary_section",
    "_fetch_failed_work_section",
    "_fetch_recent_completions_section",
    "_fetch_running_tasks_section",
    "_format_session_line",
    "_format_task_line",
    "_get_active_work_summary",
    "_get_agent_roster_summary",
    "_get_feedback_summary_section",
    "_get_git_status_summary",
    "_get_persona_tool_summary",
    "_get_recent_journal_types",
    "get_project_access_summary",
]
