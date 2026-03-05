"""Data-fetching helpers for the heartbeat prompt."""

from __future__ import annotations

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



def _get_persona_tool_summary() -> tuple[int, str]:
    """Return (count, comma-separated list) of persona-specific tool names."""
    try:
        from app.services.tools._persona_tools import PERSONA_EXTRA_TOOLS

        names = [t.name for t in PERSONA_EXTRA_TOOLS]
        return len(names), ", ".join(names)
    except Exception:
        logger.exception("Failed to list persona tools")
        return 0, "(unavailable)"


def _fetch_task_overview() -> str:
    """Cross-project task overview via st ready-all (TOON output)."""
    try:
        proc = subprocess.run(
            ["st", "ready-all"], capture_output=True, text=True, timeout=15,
        )
        return proc.stdout.strip() if proc.stdout.strip() else ""
    except Exception:
        logger.debug("Failed to fetch task overview for heartbeat prompt", exc_info=True)
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


async def _fetch_recently_completed_sessions_section() -> str:
    """Show recently completed agent sessions with their summaries.

    Gives Jenny automatic visibility into what dispatched agents accomplished.
    """
    try:
        from datetime import timedelta

        from sqlalchemy import and_, select

        from app.db import async_session
        from app.models import Session

        cutoff = datetime.now(UTC) - timedelta(hours=2)

        async with async_session() as db:
            query = (
                select(
                    Session.agent_slug,
                    Session.project_id,
                    Session.summary_oneliner,
                    Session.created_at,
                )
                .where(
                    and_(
                        Session.status == "completed",
                        Session.created_at >= cutoff,
                        Session.summary_oneliner.isnot(None),
                    )
                )
                .order_by(Session.created_at.desc())
                .limit(10)
            )
            result = await db.execute(query)
            rows = result.all()

        if not rows:
            return ""

        now = datetime.now(UTC)
        lines = [f"Recently completed sessions: {len(rows)}"]
        for row in rows:
            ago = int((now - row.created_at).total_seconds() / 60)
            time_label = f"{ago}m ago" if ago < 60 else f"{ago // 60}h ago"
            lines.append(
                f"- {row.agent_slug or '?'} on {row.project_id}: "
                f"{row.summary_oneliner} ({time_label})"
            )
        return "\n".join(lines)
    except Exception:
        logger.debug(
            "Failed to fetch completed sessions for heartbeat prompt", exc_info=True
        )
        return ""


async def _get_active_work_summary() -> str:
    """Build an <active_work> XML block with task overview, sessions, and completed sessions."""
    task_overview = _fetch_task_overview()
    sessions_section = await _fetch_active_sessions_section()
    completed_section = await _fetch_recently_completed_sessions_section()

    sections = [s for s in (task_overview, sessions_section, completed_section) if s]

    if not sections:
        logger.info("Active work summary: empty (no tasks or sessions)")
        return ""

    body = "\n\n".join(sections)
    logger.info("Active work summary: %d section(s), %d chars", len(sections), len(body))
    return f"\n<active_work>\n{body}\n</active_work>"


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
    "_fetch_recently_completed_sessions_section",
    "_fetch_task_overview",
    "_format_session_line",
    "_get_active_work_summary",
    "_get_agent_roster_summary",
    "_get_feedback_summary_section",
    "_get_git_status_summary",
    "_get_persona_tool_summary",
    "get_project_access_summary",
]
