"""Data-fetching helpers for the heartbeat prompt."""

from __future__ import annotations

import asyncio
import logging
import re
import subprocess
from datetime import UTC, datetime, timedelta

from app.services.cleanup_summary import build_actionable_cleanup_summary
from app.services.git_status_summary import build_actionable_git_summary
from app.services.ownership_lanes import (
    STALE_WORKSTREAM_IDLE_MINUTES,
    collapse_active_workstream_rows,
    idle_minutes_from_timestamps,
    infer_task_id,
)
from app.services.task_overview_summary import (
    build_compact_task_overview,
    parse_task_overview_stats,
)

logger = logging.getLogger(__name__)

_WORKSTREAM_LOOKBACK_HOURS = 24
_STALE_ACTIVE_MINUTES = STALE_WORKSTREAM_IDLE_MINUTES
_ACTIVE_SPECIALIST_LOOKBACK_HOURS = 6
_ACTIVE_SESSION_LOOKBACK_HOURS = 24
_ACTIVE_SESSION_GHOST_MINUTES = 15
_DEFAULT_SESSION_STALE_MINUTES = 15
_CODING_AGENT_SESSION_STALE_MINUTES = 30
_STALE_READY_ALL_LINE = re.compile(r"^\s+\?\s+(task-[^\s]+).*\[stale-running\]$")
_TASK_ID_PATTERN = re.compile(r"\btask-[a-z0-9]+\b")
_CLAUDE_MCP_PREFIX = "mcp__agent-hub__"

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


async def _run_st_command(
    cmd: list[str],
    *,
    timeout: int = 15,
    failure_log: str,
) -> str:
    """Run an `st` command off the event loop and return stripped stdout."""
    try:
        proc = await asyncio.to_thread(
            subprocess.run,
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except Exception:
        logger.debug(failure_log, exc_info=True)
        return ""
    stdout = proc.stdout
    if isinstance(stdout, bytes):
        stdout = stdout.decode(errors="replace")
    return stdout.strip() if isinstance(stdout, str) else ""


def _tool_call(
    tool_name: str,
    arguments: str = "",
    *,
    provider: str | None = None,
) -> str:
    """Render a callable tool invocation string for heartbeat guidance."""
    rendered = f"{_CLAUDE_MCP_PREFIX}{tool_name}" if provider == "claude" else tool_name
    return f"{rendered}({arguments})" if arguments else f"{rendered}()"


def _get_persona_tool_summary(provider: str | None = None) -> tuple[int, str]:
    """Return (count, comma-separated list) of persona-specific tool names."""
    try:
        from app.services.tools._persona_tools import PERSONA_EXTRA_TOOLS

        names = [
            f"{_CLAUDE_MCP_PREFIX}{t.name}" if provider == "claude" else t.name
            for t in PERSONA_EXTRA_TOOLS
        ]
        return len(names), ", ".join(names)
    except Exception:
        logger.exception("Failed to list persona tools")
        return 0, "(unavailable)"


async def _fetch_task_overview_raw() -> str:
    """Return raw cross-project task overview via st ready-all."""
    output = await _run_st_command(
        ["st", "ready-all"],
        failure_log="Failed to fetch task overview for heartbeat prompt",
    )
    return output


async def _fetch_task_overview() -> str:
    """Cross-project task overview condensed for heartbeat prompt injection."""
    output = await _fetch_task_overview_raw()
    if not output:
        return ""
    return build_compact_task_overview(output)


def _session_stale_threshold_minutes(is_coding_agent: bool | None) -> int:
    """Return the stale-session threshold for an agent."""
    if is_coding_agent:
        return _CODING_AGENT_SESSION_STALE_MINUTES
    return _DEFAULT_SESSION_STALE_MINUTES


def _session_display_health(health_detail: str | None, *, is_stale: bool) -> str:
    """Return the display health label for a heartbeat row."""
    in_flight = health_detail is not None and (
        health_detail == "calling_model" or health_detail.startswith("executing_tool:")
    )
    if is_stale and not in_flight:
        return "idle"
    return health_detail or "idle"


def _format_active_session_entry(session: dict[str, object], *, now: datetime) -> str:
    """Format one active-session heartbeat row."""
    is_stale = bool(session.get("is_stale"))
    task_ref = session.get("task_ref") or "-"
    _hd_raw = session.get("health_detail")
    health_detail: str | None = _hd_raw if isinstance(_hd_raw, str) else None
    _la = session.get("last_activity_at")
    if not isinstance(_la, datetime):
        age_str = "unknown"
    else:
        normalized = (
            _la.replace(tzinfo=UTC)
            if _la.tzinfo is None
            else _la.astimezone(UTC)
        )
        seconds = max(int((now - normalized).total_seconds()), 0)
        minutes = seconds // 60
        if seconds < 60:
            age_str = f"{seconds}s ago"
        elif minutes < 60:
            age_str = f"{minutes}m ago"
        else:
            hours = minutes // 60
            age_str = f"{hours}h ago" if hours < 24 else f"{hours // 24}d ago"
    parts = [
        str(session.get("agent_slug") or "session"),
        str(task_ref),
        _session_display_health(health_detail, is_stale=is_stale),
        age_str,
        f"turn {int(session.get('turn_count') or 0)}",
    ]
    in_flight = health_detail is not None and (
        health_detail == "calling_model" or health_detail.startswith("executing_tool:")
    )
    if is_stale and not in_flight:
        parts.append("STALE")
    return f"- {' | '.join(parts)}"


async def _query_active_sessions() -> tuple[list, datetime]:
    """Query active sessions from DB; returns (rows, now)."""
    from sqlalchemy import and_, func, or_, select

    from app.db import async_session
    from app.models import Agent, Session, SessionEvent

    now = datetime.now(UTC)
    cutoff = now - timedelta(hours=_ACTIVE_SESSION_LOOKBACK_HOURS)
    ghost_cutoff = now - timedelta(minutes=_ACTIVE_SESSION_GHOST_MINUTES)
    event_count = (
        select(func.count(SessionEvent.id))
        .where(SessionEvent.session_id == Session.id)
        .correlate(Session)
        .scalar_subquery()
    )
    turn_count = (
        select(func.max(SessionEvent.turn))
        .where(SessionEvent.session_id == Session.id)
        .correlate(Session)
        .scalar_subquery()
    )
    async with async_session() as db:
        rows = (
            await db.execute(
                select(
                    Session.agent_slug, Session.external_id, Session.current_branch,
                    Session.health_detail, Session.last_activity_at, Session.created_at,
                    Agent.is_coding_agent, turn_count.label("turn_count"),
                )
                .outerjoin(Agent, Agent.slug == Session.agent_slug)
                .where(and_(
                    Session.status == "active",
                    Session.agent_slug.isnot(None),
                    Session.created_at >= cutoff,
                    or_(event_count > 0, Session.created_at >= ghost_cutoff),
                ))
                .order_by(func.coalesce(Session.last_activity_at, Session.created_at).desc())
                .limit(5)
            )
        ).all()
    return list(rows), now


def _map_active_session_row(row: object, *, now: datetime) -> dict[str, object]:
    """Map a DB row to an active-session dict with staleness metadata."""
    last_activity_at = getattr(row, "last_activity_at", None) or getattr(row, "created_at", now)
    threshold = _session_stale_threshold_minutes(getattr(row, "is_coding_agent", None))
    idle_minutes = max(int((now - last_activity_at).total_seconds() / 60), 0)
    return {
        "agent_slug": getattr(row, "agent_slug", None),
        "task_ref": (
            infer_task_id(getattr(row, "external_id", None), getattr(row, "current_branch", None))
            or getattr(row, "external_id", None)
            or getattr(row, "current_branch", None)
        ),
        "health_detail": getattr(row, "health_detail", None),
        "last_activity_at": last_activity_at,
        "turn_count": int(getattr(row, "turn_count", None) or 0),
        "idle_minutes": idle_minutes,
        "is_stale": idle_minutes >= threshold,
    }


async def _query_active_sessions_for_heartbeat() -> list[dict[str, object]]:
    """Query and map active sessions for heartbeat display."""
    rows, now = await _query_active_sessions()
    return [_map_active_session_row(r, now=now) for r in rows]


async def _fetch_active_sessions_section() -> str:
    """Return a formatted section string for active sessions, or empty string."""
    try:
        sessions = await _query_active_sessions_for_heartbeat()
        if not sessions:
            return ""
        now = datetime.now(UTC)
        lines = [f"Active agent sessions: {len(sessions)}"]
        for s in sessions:
            lines.append(_format_active_session_entry(s, now=now))
        return "\n".join(lines)
    except Exception:
        logger.debug("Failed to fetch active sessions for heartbeat prompt", exc_info=True)
        return ""


async def _fetch_recently_completed_sessions_section() -> str:
    """Show recently completed agent sessions with their summaries.

    Gives Jenny automatic visibility into what dispatched agents accomplished.
    """
    try:
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
    """Query active specialist sessions and return as dicts with age_minutes."""
    from sqlalchemy import and_, select

    from app.db import async_session
    from app.models import Session

    now = datetime.now(UTC)
    cutoff = now - timedelta(hours=_ACTIVE_SPECIALIST_LOOKBACK_HOURS)
    async with async_session() as db:
        raw_rows = (
            await db.execute(
                select(
                    Session.id, Session.agent_slug, Session.project_id,
                    Session.parent_session_id, Session.request_source, Session.created_at,
                )
                .where(and_(
                    Session.status == "active",
                    Session.agent_slug.isnot(None),
                    Session.project_id != "persona-sandbox",
                    Session.created_at >= cutoff,
                    Session.external_id.is_(None),
                    Session.current_branch.is_(None),
                ))
                .order_by(Session.created_at.desc())
                .limit(50)
            )
        ).all()
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
        for row in raw_rows
    ]


def _format_specialist_group_line(
    project_id: str,
    agent_slug: str,
    group_rows: list[dict[str, object]],
) -> str:
    """Format one specialist group as a single inventory line."""
    session_ids = [str(r["session_id"]) for r in group_rows if r.get("session_id")]
    parent_ids = {str(r["parent_session_id"]) for r in group_rows if r.get("parent_session_id")}
    request_sources = {str(r["request_source"]) for r in group_rows if r.get("request_source")}
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
            lines.append(_format_specialist_group_line(project_id, agent_slug, group_rows))
        body = "\n".join(lines)
        return f"\n<active_specialist_inventory>\n{body}\n</active_specialist_inventory>"
    except Exception:
        logger.debug("Failed to build active specialist inventory for heartbeat", exc_info=True)
        return ""


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
    provider: str | None = None,
) -> str:
    """Return a concrete next action for a classified workstream lane."""
    if state == "completed_ready_for_closure" and task_id:
        return _tool_call(
            "manage_tasks",
            f'action="reconcile", task_id="{task_id}", project_id="{project_id}"',
            provider=provider,
        )
    if state == "completed_ready_for_closure" and not task_id:
        return "completed_no_task_id"
    if state == "stale_active":
        if task_id:
            query_active = _tool_call("query_sessions", 'status="active"', provider=provider)
            retire_lane = _tool_call(
                "manage_tasks",
                f'action="retire_lane", task_id="{task_id}", project_id="{project_id}"',
                provider=provider,
            )
            return f"{query_active} then {retire_lane} if truly stale"
        return (
            f"{_tool_call('query_sessions', 'status=\"active\"', provider=provider)} "
            "then verify or retire the stale lane"
        )
    if state == "mixed":
        return "split/promotion cleanup; do not dispatch more implementation onto this lane"
    if state == "reconciled":
        return "authoritative lane recorded; avoid redispatch unless new facts contradict it"
    if state == "retired":
        return "retired_lane_no_action"
    if state == "superseded":
        return "superseded_lane_no_action"
    return "monitor"


def _map_workstream_row(row: object, *, now: datetime) -> dict[str, object]:
    """Map a raw workstream DB row to a plain dict."""
    pm = getattr(row, "provider_metadata", None)
    created_at = getattr(row, "created_at", now)
    updated_at = getattr(row, "updated_at", None)
    ws_updated_at = getattr(row, "workstream_updated_at", None)
    return {
        "session_id": getattr(row, "id", None),
        "agent_slug": getattr(row, "agent_slug", None),
        "project_id": getattr(row, "project_id", None),
        "external_id": getattr(row, "external_id", None),
        "current_branch": getattr(row, "current_branch", None),
        "working_dir": pm.get("cwd") if isinstance(pm, dict) else None,
        "status": getattr(row, "status", None),
        "workstream_status": getattr(row, "workstream_status", None),
        "workstream_note": getattr(row, "workstream_note", None),
        "workstream_updated_at": ws_updated_at,
        "created_at": created_at,
        "updated_at": updated_at,
        "age_minutes": int((now - created_at).total_seconds() / 60),
        "idle_minutes": idle_minutes_from_timestamps(
            created_at=created_at, updated_at=updated_at,
            workstream_updated_at=ws_updated_at, now=now,
        ),
    }


async def _query_recent_workstream_sessions() -> list[dict[str, object]]:
    """Query workstream sessions from DB and collapse to deduplicated active rows."""
    from sqlalchemy import and_, or_, select

    from app.db import async_session
    from app.models import Session

    cutoff = datetime.now(UTC) - timedelta(hours=_WORKSTREAM_LOOKBACK_HOURS)
    async with async_session() as db:
        raw_rows = (
            await db.execute(
                select(
                    Session.id, Session.agent_slug, Session.project_id,
                    Session.external_id, Session.current_branch, Session.provider_metadata,
                    Session.status, Session.workstream_status, Session.workstream_note,
                    Session.workstream_updated_at, Session.created_at, Session.updated_at,
                )
                .where(and_(
                    Session.agent_slug.isnot(None),
                    Session.created_at >= cutoff,
                    or_(Session.external_id.isnot(None), Session.current_branch.isnot(None)),
                ))
                .order_by(Session.created_at.desc())
                .limit(50)
            )
        ).all()
    now = datetime.now(UTC)
    return collapse_active_workstream_rows([_map_workstream_row(r, now=now) for r in raw_rows])


def _parse_stale_running_tasks(task_overview: str) -> list[dict[str, str]]:
    """Parse stale-running tasks from ready-all TOON output."""
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
    return stale_tasks


def _group_rows_by_lane(
    rows: list[dict[str, object]],
) -> dict[tuple[str, str], list[dict[str, object]]]:
    """Group workstream rows by (project_id, lane_key)."""
    grouped: dict[tuple[str, str], list[dict[str, object]]] = {}
    for row in rows:
        ei = row.get("external_id") if isinstance(row.get("external_id"), str) else None
        br = row.get("current_branch") if isinstance(row.get("current_branch"), str) else None
        tid = infer_task_id(ei, br) or ""
        lane_key = tid or str(row.get("current_branch") or row.get("session_id") or "")
        if lane_key:
            grouped.setdefault((str(row["project_id"]), lane_key), []).append(row)
    return grouped


def _infer_lane_task_id(lane_rows: list[dict[str, object]]) -> str | None:
    """Return the first resolvable task_id from a set of lane rows."""
    for lr in lane_rows:
        ei = lr.get("external_id") if isinstance(lr.get("external_id"), str) else None
        br = lr.get("current_branch") if isinstance(lr.get("current_branch"), str) else None
        task_id = infer_task_id(ei, br)
        if task_id:
            return task_id
    return None


def _should_skip_lane(
    lane_state: str,
    task_id: str | None,
    lane_rows: list[dict[str, object]],
    visible_task_ids: set[str],
    task_overview: str,
) -> bool:
    """Return True if a lane should be excluded from the workstream inventory."""
    if lane_state == "completed_ready_for_closure" and task_id and task_overview:
        return task_id not in visible_task_ids
    if lane_state == "completed_ready_for_closure" and not task_id:
        agents = {str(r["agent_slug"]) for r in lane_rows if r.get("agent_slug")}
        return agents == {"persona"}
    return False


def _build_lane_line(
    project_id: str,
    lane_key: str,
    task_id: str | None,
    lane_state: str,
    lane_rows: list[dict[str, object]],
    provider: str | None,
) -> str:
    """Format one workstream lane as a single inventory line."""
    active_rows = [r for r in lane_rows if r.get("status") == "active"]
    completed_count = sum(1 for r in lane_rows if r.get("status") == "completed")
    idle_minutes = (
        min(int(r.get("idle_minutes", _STALE_ACTIVE_MINUTES + 1)) for r in active_rows)
        if active_rows else None
    )
    branches = {str(r["current_branch"]) for r in lane_rows if r.get("current_branch")}
    agents = {str(r["agent_slug"]) for r in lane_rows if r.get("agent_slug")}
    ws_statuses = {str(r["workstream_status"]) for r in lane_rows if r.get("workstream_status")}
    working_dirs = {str(r["working_dir"]) for r in lane_rows if r.get("working_dir")}
    next_action = _build_workstream_next_action(
        state=lane_state, project_id=project_id, task_id=task_id, provider=provider,
    )
    label = task_id or lane_key
    parts = [f"- {project_id} | {label}", f"state={lane_state}", f"active={len(active_rows)}"]
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
    return " | ".join(parts)


def _build_workstream_lines(
    grouped: dict[tuple[str, str], list[dict[str, object]]],
    stale_keys: set[tuple[str, str]],
    visible_task_ids: set[str],
    task_overview: str,
    provider: str | None,
) -> list[str]:
    """Build per-lane inventory lines for the workstream section."""
    lines = ["Recent workstreams:"]
    for (project_id, lane_key), lane_rows in sorted(grouped.items()):
        task_id = _infer_lane_task_id(lane_rows)
        lane_state = _classify_workstream_lane(lane_rows)
        if _should_skip_lane(lane_state, task_id, lane_rows, visible_task_ids, task_overview):
            continue
        if task_id and (project_id, task_id) in stale_keys:
            next_a = _tool_call(
                "manage_tasks",
                f'action="reconcile", task_id="{task_id}", project_id="{project_id}"',
                provider=provider,
            )
            lines.append(
                f"- {project_id} | {task_id} | state=stale_running_task | active=0 | next={next_a}"
            )
            stale_keys.discard((project_id, task_id))
            continue
        lines.append(_build_lane_line(project_id, lane_key, task_id, lane_state, lane_rows, provider))
    for project_id, task_id in sorted(stale_keys):
        if (project_id, task_id) not in grouped:
            next_a = _tool_call(
                "manage_tasks",
                f'action="reconcile", task_id="{task_id}", project_id="{project_id}"',
                provider=provider,
            )
            lines.append(
                f"- {project_id} | {task_id} | state=stale_running_task | active=0 | next={next_a}"
            )
    return lines


async def _get_workstream_inventory(
    provider: str | None = None,
    *,
    task_overview: str | None = None,
) -> str:
    """Build a heartbeat section that classifies active/recent work lanes."""
    try:
        if task_overview is None:
            task_overview = await _fetch_task_overview()
        rows = await _query_recent_workstream_sessions()
        stale_tasks = _parse_stale_running_tasks(task_overview)
        if not rows and not stale_tasks:
            return ""
        visible_task_ids = {m.group(0) for m in _TASK_ID_PATTERN.finditer(task_overview)}
        grouped = _group_rows_by_lane(rows)
        stale_keys = {(item["project_id"], item["task_id"]) for item in stale_tasks}
        if not grouped and not stale_tasks:
            return ""
        lines = _build_workstream_lines(grouped, stale_keys, visible_task_ids, task_overview, provider)
        if len(lines) == 1:
            return ""
        body = "\n".join(lines)
        return f"\n<workstream_inventory>\n{body}\n</workstream_inventory>"
    except Exception:
        logger.debug("Failed to build workstream inventory for heartbeat", exc_info=True)
        return ""


async def _get_active_work_summary(*, task_overview: str | None = None) -> str:
    """Build an <active_work> XML block with task overview, sessions, and completed sessions."""
    if task_overview is None:
        task_overview = await _fetch_task_overview()
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


async def _fetch_cleanup_status() -> str:
    """Run `st cleanup status --all` and return stripped stdout."""
    return await _run_st_command(
        ["st", "cleanup", "status", "--all"],
        failure_log="Failed to fetch cleanup status for heartbeat prompt",
    )


async def _get_cleanup_status_summary() -> str:
    """Build a <cleanup_status> XML block from the canonical st cleanup summary."""
    output = await _fetch_cleanup_status()
    if not output:
        return ""
    actionable = build_actionable_cleanup_summary(output)
    body = f"{output}\n\n{actionable}" if actionable else output
    return f"\n<cleanup_status>\n{body}\n</cleanup_status>"


async def _fetch_backup_status(target_project_id: str | None = None) -> str:
    """Run `st backup status` for the given project and return stripped stdout."""
    cmd = ["st"]
    if target_project_id:
        cmd.extend(["-P", target_project_id])
    cmd.extend(["backup", "status"])
    return await _run_st_command(cmd, failure_log="Failed to fetch backup status for heartbeat prompt")


async def _fetch_backup_schedule(target_project_id: str | None = None) -> str:
    """Run `st backup schedule` for the given project source and return stripped stdout."""
    source = target_project_id or "persona-sandbox"
    return await _run_st_command(
        ["st", "backup", "schedule", source],
        failure_log="Failed to fetch backup schedule for heartbeat prompt",
    )


async def _get_protection_status_summary(target_project_id: str | None = None) -> str:
    """Build a <protection_status> XML block from canonical backup surfaces."""
    latest, schedule = await asyncio.gather(
        _fetch_backup_status(target_project_id),
        _fetch_backup_schedule(target_project_id),
    )
    sections = [s for s in (latest, schedule) if s]
    if not sections:
        return ""
    return "\n<protection_status>\n" + "\n---\n".join(sections) + "\n</protection_status>"


async def _get_agent_roster_summary() -> str:
    """Build a compact <agent_roster> XML block listing active agent slugs."""
    try:
        from app.db import async_session
        from app.services.agent_service import get_agent_service

        agent_service = get_agent_service()
        async with async_session() as db:
            agents = await agent_service.list_agents(db, active_only=True)

        if not agents:
            return ""

        coding_agents = sorted(a.slug for a in agents if a.is_coding_agent)
        general_agents = sorted(a.slug for a in agents if not a.is_coding_agent)
        lines = [f"Total active agents: {len(agents)}"]
        if coding_agents:
            lines.append(f"Coding ({len(coding_agents)}): {', '.join(coding_agents)}")
        if general_agents:
            lines.append(f"General ({len(general_agents)}): {', '.join(general_agents)}")
        body = "\n".join(lines)
        logger.info("Agent roster summary: %d agents", len(agents))
        return f"\n<agent_roster>\n{body}\n</agent_roster>"
    except Exception:
        logger.debug("Failed to fetch agent roster for heartbeat prompt", exc_info=True)
        return ""


async def _get_git_status_summary() -> str:
    """Build a <git_state> XML block from the canonical `st git status` surface."""
    git_status = await _run_st_command(
        ["st", "--compact", "git", "status"],
        failure_log="Failed to fetch git status for heartbeat prompt",
    )
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

        top_items = summary.get("top_unresolved", [])
        if not top_items:
            return ""

        # Aggregate open/acknowledged counts by type
        type_counts: dict[str, int] = {}
        for row in summary.get("counts_by_type_status", []):
            if row.get("status") in {"open", "acknowledged"}:
                ft = row.get("feedback_type", "unknown")
                type_counts[ft] = type_counts.get(ft, 0) + row.get("count", 0)

        unresolved_count = sum(type_counts.values())
        if unresolved_count == 0:
            return ""

        lines = [f"Unresolved items: {unresolved_count} (of {summary.get('total_items', 0)} total, last 30d)"]
        if type_counts:
            breakdown = ", ".join(f"{k}: {v}" for k, v in sorted(type_counts.items()))
            lines.append(f"By type: {breakdown}")
        hot = [r for r in summary.get("by_component", []) if int(r.get("open_count", 0) or 0) > 0][:3]
        if hot:
            hotspots = ", ".join(
                f"{r['component_id']} open={r['open_count']} votes={r['total_votes'] or 0}"
                for r in hot
            )
            lines.append(f"Hotspots: {hotspots}")

        lines += ["", f"{'ID':>8}  {'Type':<11}  {'Component':<20}  {'Votes':>5}  Title", "-" * 78]
        for item in top_items[:5]:
            short_id = str(item.id)[:8]
            lines.append(
                f"{short_id:>8}  {item.feedback_type:<11}  "
                f"{item.component_id:<20}  {item.vote_count:>5}  "
                f"{(item.title or '')[:40]}"
            )

        body = "\n".join(lines)
        logger.info("Feedback summary: %d unresolved items", unresolved_count)
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
    "_format_active_session_entry",
    "_get_active_specialist_inventory",
    "_get_active_work_summary",
    "_get_agent_roster_summary",
    "_get_cleanup_status_summary",
    "_get_feedback_summary_section",
    "_get_git_status_summary",
    "_get_persona_tool_summary",
    "_get_protection_status_summary",
    "_get_workstream_inventory",
    "_query_active_sessions_for_heartbeat",
    "_query_active_specialist_sessions",
    "_query_recent_workstream_sessions",
    "_run_st_command",
    "_session_display_health",
    "_session_stale_threshold_minutes",
    "_tool_call",
    "get_project_access_summary",
]
