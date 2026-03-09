"""Data-fetching helpers for the heartbeat prompt."""

from __future__ import annotations

import logging
import re
import subprocess
from datetime import UTC, datetime

from app.services.ownership_lanes import (
    STALE_WORKSTREAM_IDLE_MINUTES,
    collapse_active_workstream_rows,
    idle_minutes_from_timestamps,
    infer_task_id,
)

logger = logging.getLogger(__name__)

_WORKSTREAM_LOOKBACK_HOURS = 24
_STALE_ACTIVE_MINUTES = STALE_WORKSTREAM_IDLE_MINUTES
_ACTIVE_SPECIALIST_LOOKBACK_HOURS = 6
_STALE_READY_ALL_LINE = re.compile(r"^\s+\?\s+(task-[^\s]+).*\[stale-running\]$")
_TASK_ID_PATTERN = re.compile(r"\btask-[a-z0-9]+\b")

# Contract: workstream inventory states are derived in precedence order.
# Highest precedence first:
# 1. retired - all observed lifecycle markers are retired
# 2. reconciled - authoritative + superseded evidence exists for the same lane
# 3. superseded - all observed lifecycle markers are superseded
# 4. mixed - multiple active branches for the same task/lane
# 5. stale_active - active lane exists but exceeds the stale age threshold
# 6. active - live non-stale lane exists
# 7. completed_ready_for_closure - no active lane remains and completed evidence exists
# 8. orphaned - lane facts exist but do not yet justify automation
#
# Automation boundary:
# - completed_ready_for_closure: safe to reconcile/close
# - stale_running_task (from ready-all): safe to reconcile stale task state
# - stale_active: advisory only until explicitly verified/reconciled
# - mixed / orphaned / reconciled / retired / superseded: informational, no new automatic close path here


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


def _fetch_cleanup_status() -> str:
    """Cross-project git hygiene summary via st cleanup status (TOON output)."""
    try:
        proc = subprocess.run(
            ["st", "cleanup", "status", "--all"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        return proc.stdout.strip() if proc.stdout.strip() else ""
    except Exception:
        logger.debug("Failed to fetch cleanup status for heartbeat prompt", exc_info=True)
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


async def _query_completed_sessions(cutoff: datetime) -> list:
    """Fetch recently completed non-persona sessions from the DB."""
    from sqlalchemy import and_, select

    from app.db import async_session
    from app.models import Session

    async with async_session() as db:
        result = await db.execute(
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
                    Session.agent_slug != "persona",
                )
            )
            .order_by(Session.created_at.desc())
            .limit(10)
        )
        return list(result.all())


def _format_completed_session_line(row, now: datetime) -> str:
    """Format a single completed session row into a heartbeat summary line."""
    ago = int((now - row.created_at).total_seconds() / 60)
    time_label = f"{ago}m ago" if ago < 60 else f"{ago // 60}h ago"
    return (
        f"- {row.agent_slug or '?'} on {row.project_id}: "
        f"{row.summary_oneliner} ({time_label})"
    )


async def _fetch_recently_completed_sessions_section() -> str:
    """Show recently completed agent sessions with their summaries.

    Gives Jenny automatic visibility into what dispatched agents accomplished.
    """
    try:
        from datetime import timedelta

        cutoff = datetime.now(UTC) - timedelta(hours=2)
        rows = await _query_completed_sessions(cutoff)
        if not rows:
            return ""
        now = datetime.now(UTC)
        lines = [f"Recently completed sessions: {len(rows)}"]
        lines.extend(_format_completed_session_line(row, now) for row in rows)
        return "\n".join(lines)
    except Exception:
        logger.debug(
            "Failed to fetch completed sessions for heartbeat prompt", exc_info=True
        )
        return ""


async def _query_active_specialist_sessions() -> list[dict[str, object]]:
    """Fetch active non-owner specialist sessions for heartbeat duplicate-avoidance.

    These are active sessions without a task/worktree lane, which means they can still
    overlap in practice even though the ownership inventory correctly excludes them.
    """
    from datetime import timedelta

    from sqlalchemy import and_, select

    from app.db import async_session
    from app.models import Session

    cutoff = datetime.now(UTC) - timedelta(hours=_ACTIVE_SPECIALIST_LOOKBACK_HOURS)

    async with async_session() as db:
        query = (
            select(
                Session.id, Session.agent_slug, Session.project_id,
                Session.parent_session_id, Session.request_source, Session.created_at,
            )
            .where(
                and_(
                    Session.status == "active",
                    Session.agent_slug.isnot(None),
                    Session.project_id != "persona-sandbox",
                    Session.created_at >= cutoff,
                    Session.external_id.is_(None),
                    Session.current_branch.is_(None),
                )
            )
            .order_by(Session.created_at.desc())
            .limit(50)
        )
        rows = (await db.execute(query)).all()

    now = datetime.now(UTC)
    return [
        {
            "session_id": row.id,
            "agent_slug": row.agent_slug,
            "project_id": row.project_id,
            "parent_session_id": row.parent_session_id,
            "request_source": row.request_source,
            "created_at": row.created_at,
            "age_minutes": int((now - row.created_at).total_seconds() / 60),
        }
        for row in rows
    ]


def _format_active_specialist_group(
    project_id: str,
    agent_slug: str,
    rows: list[dict[str, object]],
) -> str:
    """Format an active specialist group into a heartbeat summary line."""
    session_ids = [str(row["session_id"]) for row in rows if row.get("session_id")]
    parent_ids = {
        str(row["parent_session_id"])
        for row in rows
        if row.get("parent_session_id")
    }
    request_sources = {
        str(row["request_source"])
        for row in rows
        if row.get("request_source")
    }
    oldest_age = max(int(row.get("age_minutes", 0)) for row in rows)
    newest_age = min(int(row.get("age_minutes", 0)) for row in rows)
    duplicate = len(rows) > 1
    parts = [
        f"- {project_id} | {agent_slug}",
        f"active={len(rows)}",
        f"age={newest_age}-{oldest_age}m" if duplicate else f"age={oldest_age}m",
        "next=dedupe_or_wait" if duplicate else "next=wait_or_complement",
    ]
    if request_sources:
        parts.append(f"source={','.join(sorted(request_sources))}")
    if parent_ids:
        parts.append(f"parents={len(parent_ids)}")
    if session_ids:
        parts.append(f"sessions={','.join(session_ids[:2])}")
    return " | ".join(parts)


async def _get_active_specialist_inventory() -> str:
    """Build a heartbeat section for active read-only/planning specialist sessions."""
    try:
        rows = await _query_active_specialist_sessions()
        if not rows:
            return ""

        grouped: dict[tuple[str, str], list[dict[str, object]]] = {}
        for row in rows:
            key = (str(row["project_id"]), str(row["agent_slug"]))
            grouped.setdefault(key, []).append(row)

        lines = ["Active specialist sessions:"]
        for (project_id, agent_slug), group_rows in sorted(grouped.items()):
            lines.append(_format_active_specialist_group(project_id, agent_slug, group_rows))
        body = "\n".join(lines)
        return f"\n<active_specialist_inventory>\n{body}\n</active_specialist_inventory>"
    except Exception:
        logger.debug("Failed to build active specialist inventory for heartbeat", exc_info=True)
        return ""


def _map_workstream_row(row, now: datetime) -> dict[str, object]:
    """Map a raw DB row to a workstream session dict."""
    return {
        "session_id": row.id,
        "agent_slug": row.agent_slug,
        "project_id": row.project_id,
        "external_id": row.external_id,
        "current_branch": row.current_branch,
        "working_dir": (
            row.provider_metadata.get("cwd")
            if isinstance(row.provider_metadata, dict)
            else None
        ),
        "status": row.status,
        "workstream_status": row.workstream_status,
        "workstream_note": row.workstream_note,
        "workstream_updated_at": row.workstream_updated_at,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
        "age_minutes": int((now - row.created_at).total_seconds() / 60),
        "idle_minutes": idle_minutes_from_timestamps(
            created_at=row.created_at,
            updated_at=row.updated_at,
            workstream_updated_at=row.workstream_updated_at,
            now=now,
        ),
    }


async def _query_recent_workstream_sessions() -> list[dict[str, object]]:
    """Fetch recent session rows that look like task/worktree lanes."""
    from datetime import timedelta

    from sqlalchemy import and_, or_, select

    from app.db import async_session
    from app.models import Session

    cutoff = datetime.now(UTC) - timedelta(hours=_WORKSTREAM_LOOKBACK_HOURS)

    async with async_session() as db:
        query = (
            select(
                Session.id, Session.agent_slug, Session.project_id,
                Session.external_id, Session.current_branch, Session.provider_metadata,
                Session.status, Session.workstream_status, Session.workstream_note,
                Session.workstream_updated_at, Session.created_at, Session.updated_at,
            )
            .where(
                and_(
                    Session.agent_slug.isnot(None),
                    Session.created_at >= cutoff,
                    or_(
                        Session.external_id.isnot(None),
                        Session.current_branch.isnot(None),
                    ),
                )
            )
            .order_by(Session.created_at.desc())
            .limit(50)
        )
        rows = (await db.execute(query)).all()

    now = datetime.now(UTC)
    return [_map_workstream_row(row, now) for row in rows]


def _infer_task_id(row: dict[str, object]) -> str | None:
    """Infer a task id from explicit linkage or task branch naming."""
    external_id = row.get("external_id") if isinstance(row.get("external_id"), str) else None
    branch = row.get("current_branch") if isinstance(row.get("current_branch"), str) else None
    return infer_task_id(external_id, branch)


def _classify_workstream_lane(rows: list[dict[str, object]]) -> str:
    """Classify a grouped task/worktree lane into an actionable lifecycle state.

    See module-level contract comment for the precedence order and automation boundary.
    """
    statuses = {str(row["workstream_status"]) for row in rows if row.get("workstream_status")}
    active_rows = [row for row in rows if row.get("status") == "active"]
    completed_rows = [row for row in rows if row.get("status") == "completed"]
    branches = {str(row["current_branch"]) for row in rows if row.get("current_branch")}

    if statuses == {"retired"}:
        return "retired"
    if "authoritative" in statuses and "superseded" in statuses:
        return "reconciled"
    if statuses == {"superseded"}:
        return "superseded"
    if len(active_rows) > 1 and len(branches) > 1:
        return "mixed"
    if active_rows:
        freshest_active_idle = min(
            int(row.get("idle_minutes", _STALE_ACTIVE_MINUTES + 1))
            for row in active_rows
        )
        if freshest_active_idle >= _STALE_ACTIVE_MINUTES:
            return "stale_active"
        return "active"
    if completed_rows:
        return "completed_ready_for_closure"
    return "orphaned"


def _build_workstream_next_action(
    *,
    state: str,
    project_id: str,
    task_id: str | None,
) -> str:
    """Return a concrete next action for a classified workstream lane."""
    if state == "completed_ready_for_closure" and task_id:
        return (
            f'manage_tasks(action="reconcile", task_id="{task_id}", '
            f'project_id="{project_id}")'
        )
    if state == "completed_ready_for_closure" and not task_id:
        return "completed_no_task_id"
    if state == "stale_active":
        if task_id:
            return (
                f'query_sessions(status="active") then manage_tasks(action="retire_lane", '
                f'task_id="{task_id}", project_id="{project_id}") if truly stale'
            )
        return "query_sessions(status='active') then verify or retire the stale lane"
    if state == "mixed":
        return "split/promotion cleanup; do not dispatch more implementation onto this lane"
    if state == "reconciled":
        return "authoritative lane recorded; avoid redispatch unless new facts contradict it"
    if state == "retired":
        return "retired_lane_no_action"
    if state == "superseded":
        return "superseded_lane_no_action"
    return "monitor"


def _collect_lane_metadata(lane_rows: list[dict[str, object]]) -> dict[str, object]:
    """Collect computed metadata fields from a group of workstream lane rows."""
    task_id = next((_infer_task_id(row) for row in lane_rows if _infer_task_id(row)), None)
    branches = {str(row["current_branch"]) for row in lane_rows if row.get("current_branch")}
    agents = {str(row["agent_slug"]) for row in lane_rows if row.get("agent_slug")}
    active_rows = [row for row in lane_rows if row.get("status") == "active"]
    active_count = len(active_rows)
    completed_count = sum(1 for row in lane_rows if row.get("status") == "completed")
    idle_minutes = (
        min(int(row.get("idle_minutes", _STALE_ACTIVE_MINUTES + 1)) for row in active_rows)
        if active_count else None
    )
    workstream_statuses = {
        str(row["workstream_status"]) for row in lane_rows if row.get("workstream_status")
    }
    working_dirs = {str(row["working_dir"]) for row in lane_rows if row.get("working_dir")}
    return {
        "task_id": task_id,
        "branches": branches,
        "agents": agents,
        "active_count": active_count,
        "completed_count": completed_count,
        "idle_minutes": idle_minutes,
        "workstream_statuses": workstream_statuses,
        "working_dirs": working_dirs,
        "state": _classify_workstream_lane(lane_rows),
    }


def _format_workstream_lane(
    project_id: str,
    lane_key: str,
    lane_rows: list[dict[str, object]],
) -> str:
    """Format a single workstream lane into a summary line."""
    meta = _collect_lane_metadata(lane_rows)
    next_action = _build_workstream_next_action(
        state=str(meta["state"]),
        project_id=project_id,
        task_id=meta["task_id"],
    )
    label = meta["task_id"] or lane_key
    parts = [f"- {project_id} | {label}", f"state={meta['state']}", f"active={meta['active_count']}"]
    if meta["idle_minutes"] is not None:
        parts.append(f"idle={meta['idle_minutes']}m")
    if meta["completed_count"]:
        parts.append(f"completed={meta['completed_count']}")
    if meta["workstream_statuses"]:
        parts.append(f"lifecycle={','.join(sorted(meta['workstream_statuses']))}")
    if meta["branches"]:
        parts.append(f"branches={len(meta['branches'])}")
    if meta["working_dirs"]:
        parts.append(f"worktree={next(iter(sorted(meta['working_dirs'])))}")
    if meta["agents"]:
        parts.append(f"agents={','.join(sorted(meta['agents']))}")
    parts.append(f"next={next_action}")
    return " | ".join(parts)


def _extract_stale_running_tasks(task_overview: str) -> list[dict[str, str]]:
    """Parse stale-running task entries from `st ready-all` output."""
    project_id: str | None = None
    stale_tasks: list[dict[str, str]] = []

    for raw_line in task_overview.splitlines():
        line = raw_line.rstrip()
        if not line:
            continue
        if not line.startswith(" ") and "(" in line and line.endswith(")"):
            project_id = line.split(" ", 1)[0]
            continue
        match = _STALE_READY_ALL_LINE.match(line)
        if match and project_id:
            stale_tasks.append({
                "project_id": project_id,
                "task_id": match.group(1),
            })

    return stale_tasks


def _extract_task_ids(task_overview: str) -> set[str]:
    """Extract all task ids present in the current queue snapshot."""
    return {match.group(0) for match in _TASK_ID_PATTERN.finditer(task_overview)}


def _format_stale_running_task(project_id: str, task_id: str) -> str:
    """Format an orphan running task from queue truth into the workstream inventory."""
    next_action = (
        f'manage_tasks(action="reconcile", task_id="{task_id}", project_id="{project_id}")'
    )
    return (
        f"- {project_id} | {task_id} | state=stale_running_task | "
        f"active=0 | next={next_action}"
    )


def _group_workstream_rows(
    rows: list[dict[str, object]],
) -> dict[tuple[str, str], list[dict[str, object]]]:
    """Group collapsed workstream rows by (project_id, lane_key)."""
    grouped: dict[tuple[str, str], list[dict[str, object]]] = {}
    for row in rows:
        task_id = _infer_task_id(row) or ""
        branch = str(row.get("current_branch") or row.get("session_id") or "")
        lane_key = task_id or branch
        if not lane_key:
            continue
        grouped.setdefault((str(row["project_id"]), lane_key), []).append(row)
    return grouped


async def _get_workstream_inventory() -> str:
    """Build a heartbeat section that classifies active/recent work lanes."""
    try:
        rows = collapse_active_workstream_rows(await _query_recent_workstream_sessions())
        task_overview = _fetch_task_overview()
        visible_task_ids = _extract_task_ids(task_overview)
        stale_tasks = _extract_stale_running_tasks(task_overview)
        if not rows and not stale_tasks:
            return ""
        grouped = _group_workstream_rows(rows)
        if not grouped and not stale_tasks:
            return ""
        lines = ["Recent workstreams:"]
        stale_keys = {(item["project_id"], item["task_id"]) for item in stale_tasks}
        for (project_id, lane_key), lane_rows in sorted(grouped.items()):
            task_id = next((_infer_task_id(row) for row in lane_rows if _infer_task_id(row)), None)
            lane_state = _classify_workstream_lane(lane_rows)
            if (
                lane_state == "completed_ready_for_closure"
                and task_id
                and task_overview
                and task_id not in visible_task_ids
            ):
                continue
            if task_id and (project_id, task_id) in stale_keys:
                lines.append(_format_stale_running_task(project_id, task_id))
                stale_keys.discard((project_id, task_id))
                continue
            lines.append(_format_workstream_lane(project_id, lane_key, lane_rows))
        for project_id, task_id in sorted(stale_keys):
            if (project_id, task_id) in grouped:
                continue
            lines.append(_format_stale_running_task(project_id, task_id))
        if len(lines) == 1:
            return ""
        body = "\n".join(lines)
        return f"\n<workstream_inventory>\n{body}\n</workstream_inventory>"
    except Exception:
        logger.debug("Failed to build workstream inventory for heartbeat", exc_info=True)
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


def _get_cleanup_status_summary() -> str:
    """Build a <cleanup_status> XML block from the canonical st cleanup summary."""
    cleanup_status = _fetch_cleanup_status()
    if not cleanup_status:
        return ""
    return f"\n<cleanup_status>\n{cleanup_status}\n</cleanup_status>"


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
            f"- {a.slug} [{'coding' if a.is_coding_agent else 'general'}]: "
            f"{a.description or '(no description)'}"
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
    "_fetch_cleanup_status",
    "_fetch_recently_completed_sessions_section",
    "_fetch_task_overview",
    "_format_session_line",
    "_get_active_specialist_inventory",
    "_get_active_work_summary",
    "_get_agent_roster_summary",
    "_get_cleanup_status_summary",
    "_get_feedback_summary_section",
    "_get_git_status_summary",
    "_get_persona_tool_summary",
    "_get_workstream_inventory",
    "get_project_access_summary",
]
