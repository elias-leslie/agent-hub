"""Data-fetching helpers for the heartbeat prompt."""

from __future__ import annotations

import logging
import re
import subprocess
from datetime import UTC, datetime

from app.services.cleanup_summary import build_actionable_cleanup_summary
from app.services.git_status_summary import build_actionable_git_summary
from app.services.ownership_lanes import (
    STALE_WORKSTREAM_IDLE_MINUTES,
    collapse_active_workstream_rows,
    idle_minutes_from_timestamps,
    infer_task_id,
)
from app.services.task_overview_summary import (
    build_actionable_ready_summary,
    parse_task_overview_stats,
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
        output = proc.stdout.strip()
        if not output:
            return ""
        actionable = build_actionable_ready_summary(output)
        return f"{output}\n\n{actionable}" if actionable else output
    except Exception:
        logger.debug("Failed to fetch task overview for heartbeat prompt", exc_info=True)
        return ""


def _fetch_cleanup_status() -> str:
    """Cross-project git hygiene summary via st cleanup status (TOON output)."""
    try:
        proc = subprocess.run(
            ["st", "cleanup", "status", "--all"],
            capture_output=True, text=True, timeout=15,
        )
        output = proc.stdout.strip()
        if not output:
            return ""
        actionable = build_actionable_cleanup_summary(output)
        return f"{output}\n\n{actionable}" if actionable else output
    except Exception:
        logger.debug("Failed to fetch cleanup status for heartbeat prompt", exc_info=True)
        return ""


def _fetch_backup_status(project_id: str | None = None) -> str:
    """Fetch most recent backup status for a project-backed source."""
    cmd = ["st"]
    if project_id:
        cmd.extend(["-P", project_id])
    cmd.extend(["backup", "status"])
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        return proc.stdout.strip() if proc.stdout.strip() else ""
    except Exception:
        logger.debug("Failed to fetch backup status for heartbeat prompt", exc_info=True)
        return ""


def _fetch_backup_schedule(source_id: str) -> str:
    """Fetch schedule details for a single backup source."""
    try:
        proc = subprocess.run(
            ["st", "backup", "schedule", source_id],
            capture_output=True, text=True, timeout=15,
        )
        return proc.stdout.strip() if proc.stdout.strip() else ""
    except Exception:
        logger.debug("Failed to fetch backup schedule for heartbeat prompt", exc_info=True)
        return ""


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
        for s in sessions:
            parts: list[str] = []
            if s.get("external_id"):
                parts.append(str(s["external_id"]))
            if s.get("current_branch"):
                parts.append(f"branch: {s['current_branch']}")
            fc = s.get("touched_file_count", 0)
            if fc:
                parts.append(f"files: {fc}")
            detail = ", ".join(parts) if parts else f"{s.get('event_count', 0)} events"
            lines.append(
                f"- {s.get('agent_slug', 'session')} on {s.get('project_id', 'unknown')}, {detail}"
            )
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
        now = datetime.now(UTC)

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
            rows = list(result.all())

        if not rows:
            return ""
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
            session_ids = [str(r["session_id"]) for r in group_rows if r.get("session_id")]
            parent_ids = {
                str(r["parent_session_id"]) for r in group_rows if r.get("parent_session_id")
            }
            request_sources = {
                str(r["request_source"]) for r in group_rows if r.get("request_source")
            }
            oldest_age = max(int(r.get("age_minutes", 0)) for r in group_rows)
            newest_age = min(int(r.get("age_minutes", 0)) for r in group_rows)
            duplicate = len(group_rows) > 1
            parts = [
                f"- {project_id} | {agent_slug}",
                f"active={len(group_rows)}",
                f"age={newest_age}-{oldest_age}m" if duplicate else f"age={oldest_age}m",
                "next=dedupe_or_wait" if duplicate else "next=wait_or_complement",
            ]
            if request_sources:
                parts.append(f"source={','.join(sorted(request_sources))}")
            if parent_ids:
                parts.append(f"parents={len(parent_ids)}")
            if session_ids:
                parts.append(f"sessions={','.join(session_ids[:2])}")
            lines.append(" | ".join(parts))

        body = "\n".join(lines)
        return f"\n<active_specialist_inventory>\n{body}\n</active_specialist_inventory>"
    except Exception:
        logger.debug("Failed to build active specialist inventory for heartbeat", exc_info=True)
        return ""


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
    return [
        {
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
        for row in rows
    ]


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


async def _get_workstream_inventory() -> str:
    """Build a heartbeat section that classifies active/recent work lanes."""
    try:
        rows = collapse_active_workstream_rows(await _query_recent_workstream_sessions())
        task_overview = _fetch_task_overview()
        visible_task_ids = {m.group(0) for m in _TASK_ID_PATTERN.finditer(task_overview)}

        # Parse stale-running task entries from ready-all output
        stale_tasks: list[dict[str, str]] = []
        cur_project: str | None = None
        for raw_line in task_overview.splitlines():
            line = raw_line.rstrip()
            if not line:
                continue
            if not line.startswith(" ") and "(" in line and line.endswith(")"):
                cur_project = line.split(" ", 1)[0]
                continue
            m = _STALE_READY_ALL_LINE.match(line)
            if m and cur_project:
                stale_tasks.append({"project_id": cur_project, "task_id": m.group(1)})

        if not rows and not stale_tasks:
            return ""

        # Group rows by (project_id, lane_key)
        grouped: dict[tuple[str, str], list[dict[str, object]]] = {}
        for row in rows:
            ei = row.get("external_id") if isinstance(row.get("external_id"), str) else None
            br = row.get("current_branch") if isinstance(row.get("current_branch"), str) else None
            tid = infer_task_id(ei, br) or ""
            lane_key = tid or str(row.get("current_branch") or row.get("session_id") or "")
            if not lane_key:
                continue
            grouped.setdefault((str(row["project_id"]), lane_key), []).append(row)

        if not grouped and not stale_tasks:
            return ""

        lines = ["Recent workstreams:"]
        stale_keys = {(item["project_id"], item["task_id"]) for item in stale_tasks}

        for (project_id, lane_key), lane_rows in sorted(grouped.items()):
            # Derive task_id for this lane
            task_id: str | None = None
            for row in lane_rows:
                ei = row.get("external_id") if isinstance(row.get("external_id"), str) else None
                br = row.get("current_branch") if isinstance(row.get("current_branch"), str) else None
                task_id = infer_task_id(ei, br)
                if task_id:
                    break

            lane_state = _classify_workstream_lane(lane_rows)
            if (
                lane_state == "completed_ready_for_closure"
                and task_id
                and task_overview
                and task_id not in visible_task_ids
            ):
                continue
            if task_id and (project_id, task_id) in stale_keys:
                next_action = (
                    f'manage_tasks(action="reconcile", task_id="{task_id}", '
                    f'project_id="{project_id}")'
                )
                lines.append(
                    f"- {project_id} | {task_id} | state=stale_running_task | "
                    f"active=0 | next={next_action}"
                )
                stale_keys.discard((project_id, task_id))
                continue

            # Format workstream lane inline
            branches = {str(r["current_branch"]) for r in lane_rows if r.get("current_branch")}
            agents = {str(r["agent_slug"]) for r in lane_rows if r.get("agent_slug")}
            active_rows = [r for r in lane_rows if r.get("status") == "active"]
            active_count = len(active_rows)
            completed_count = sum(1 for r in lane_rows if r.get("status") == "completed")
            idle_minutes = (
                min(int(r.get("idle_minutes", _STALE_ACTIVE_MINUTES + 1)) for r in active_rows)
                if active_count else None
            )
            ws_statuses = {
                str(r["workstream_status"]) for r in lane_rows if r.get("workstream_status")
            }
            working_dirs = {str(r["working_dir"]) for r in lane_rows if r.get("working_dir")}
            next_action = _build_workstream_next_action(
                state=lane_state, project_id=project_id, task_id=task_id,
            )
            label = task_id or lane_key
            parts = [f"- {project_id} | {label}", f"state={lane_state}", f"active={active_count}"]
            if idle_minutes is not None:
                parts.append(f"idle={idle_minutes}m")
            if completed_count:
                parts.append(f"completed={completed_count}")
            if ws_statuses:
                parts.append(f"lifecycle={','.join(sorted(ws_statuses))}")
            if branches:
                parts.append(f"branches={len(branches)}")
            if working_dirs:
                parts.append(f"worktree={next(iter(sorted(working_dirs)))}")
            if agents:
                parts.append(f"agents={','.join(sorted(agents))}")
            parts.append(f"next={next_action}")
            lines.append(" | ".join(parts))

        for project_id, task_id in sorted(stale_keys):
            if (project_id, task_id) in grouped:
                continue
            next_action = (
                f'manage_tasks(action="reconcile", task_id="{task_id}", '
                f'project_id="{project_id}")'
            )
            lines.append(
                f"- {project_id} | {task_id} | state=stale_running_task | "
                f"active=0 | next={next_action}"
            )

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
    overview_stats = parse_task_overview_stats(task_overview)
    sessions_section = await _fetch_active_sessions_section()
    suppress_completed = (
        overview_stats.ready > 0 and overview_stats.active == 0 and overview_stats.stale == 0
    )
    completed_section = (
        ""
        if suppress_completed
        else await _fetch_recently_completed_sessions_section()
    )

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


def _get_protection_status_summary(target_project_id: str | None = None) -> str:
    """Build a <protection_status> XML block from canonical backup surfaces."""
    sections: list[str] = []

    latest = _fetch_backup_status(target_project_id)
    if latest:
        sections.append(latest)

    target_source = target_project_id or "persona-sandbox"
    schedule = _fetch_backup_schedule(target_source)
    if schedule:
        sections.append(schedule)

    if not sections:
        return ""
    return "\n<protection_status>\n" + "\n---\n".join(sections) + "\n</protection_status>"


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


def _get_git_status_summary() -> str:
    """Build a <git_state> XML block from the canonical `st git status` surface."""
    try:
        proc = subprocess.run(
            ["st", "--compact", "git", "status"],
            capture_output=True,
            text=True,
            timeout=15,
        )
    except Exception:
        logger.debug("Failed to fetch git status for heartbeat prompt", exc_info=True)
        return ""

    git_status = proc.stdout.strip()
    if not git_status:
        return ""

    actionable = build_actionable_git_summary(git_status)
    body = f"{git_status}\n\n{actionable}" if actionable else git_status
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
    "_build_workstream_next_action",
    "_classify_workstream_lane",
    "_fetch_active_sessions_section",
    "_fetch_backup_schedule",
    "_fetch_backup_status",
    "_fetch_cleanup_status",
    "_fetch_recently_completed_sessions_section",
    "_fetch_task_overview",
    "_get_active_specialist_inventory",
    "_get_active_work_summary",
    "_get_agent_roster_summary",
    "_get_cleanup_status_summary",
    "_get_feedback_summary_section",
    "_get_git_status_summary",
    "_get_persona_tool_summary",
    "_get_protection_status_summary",
    "_get_workstream_inventory",
    "_query_active_specialist_sessions",
    "_query_recent_workstream_sessions",
    "get_project_access_summary",
]
