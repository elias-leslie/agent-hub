"""Data-fetching helpers for the heartbeat prompt.

Orchestrator functions and patchable API callers live here; pure helpers and
formatters are extracted into focused sub-modules:
  _heartbeat_state     — dataclasses and constants
  _heartbeat_project   — project access/index reading
  _heartbeat_sessions  — session formatting helpers and specialist inventory
  _heartbeat_workstream — lane classification and formatting helpers
  _heartbeat_sections  — roster, feedback, agent tool summary
"""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx

from app.adapters._claude_constants import MCP_TOOL_PREFIX
from app.services.backup_summary import (
    fetch_backup_schedule_line,
    fetch_latest_backup_status_line,
)
from app.services.cleanup_summary import (
    build_actionable_cleanup_summary,
    build_actionable_cleanup_summary_from_payload,
)
from app.services.git_status_summary import (
    RepoGitStatus,
    build_actionable_git_summary_from_rows,
    build_compact_git_status,
)
from app.services.ownership_lanes import (
    STALE_WORKSTREAM_IDLE_MINUTES,
    collapse_active_workstream_rows,
)
from app.services.session_display_summary import (
    SessionDisplaySummaryCandidate,
    fetch_session_display_summary_results,
)
from app.services.task_overview_summary import (
    build_compact_task_overview,
    build_compact_task_overview_from_payload,
    collect_visible_task_ids_from_payload,
    extract_stale_task_candidates_from_payload,
    parse_task_overview_stats,
    parse_task_overview_stats_from_payload,
)

# Re-export project access helpers
from app.workflows._heartbeat_project import (
    _read_project_api_url,
    get_project_access_summary,
)

# Re-export section helpers (roster, feedback, persona tools)
from app.workflows._heartbeat_sections import (
    _get_agent_roster_summary,
    _get_feedback_summary_section,
    _get_persona_tool_summary,
)

# Re-export pure session formatting helpers (orchestrators using these names defined below)
from app.workflows._heartbeat_sessions import (
    _format_active_session_entry,
    _format_specialist_group_line,
    _query_active_sessions_for_heartbeat,
    _query_active_specialist_sessions,
    _session_display_health,
    _session_stale_threshold_minutes,
)

# Re-export state types from sub-module
from app.workflows._heartbeat_state import (
    AgentHubHeartbeatState,
    SummitFlowHeartbeatState,
)

# Re-export workstream classification helpers (pure, no IO)
from app.workflows._heartbeat_workstream import (
    _build_workstream_lines,
    _build_workstream_next_action,
    _classify_workstream_lane,
    _group_rows_by_lane,
    _map_workstream_row,
    _parse_stale_running_tasks,
)

logger = logging.getLogger(__name__)

_WORKSTREAM_LOOKBACK_HOURS = 24
_STALE_ACTIVE_MINUTES = STALE_WORKSTREAM_IDLE_MINUTES
_ACTIVE_SPECIALIST_LOOKBACK_HOURS = 6
_ACTIVE_SESSION_LOOKBACK_HOURS = 24
_ACTIVE_SESSION_GHOST_MINUTES = 15
_ACTIVE_SESSION_DISPLAY_LIMIT = 5
_ACTIVE_SESSION_PREFILTER_LIMIT = 25
_DEFAULT_SESSION_STALE_MINUTES = 15
_CODING_AGENT_SESSION_STALE_MINUTES = 30
_BENCHMARK_EXTERNAL_ID_PREFIXES = (
    "benchmark:",
    "agent-output-benchmark:",
    "persona-benchmark:",
)
_STALE_READY_ALL_LINE = re.compile(r"^\s+\?\s+(task-[^\s]+).*\[stale-running\]$")
_COMPACT_STALE_LINE = re.compile(r"^- (?P<project>[a-z0-9-]+) \| (?P<task_id>task-[^\s|]+) \| ")
_TASK_ID_PATTERN = re.compile(r"\btask-[a-z0-9]+\b")
_CLAUDE_MCP_PREFIX = MCP_TOOL_PREFIX
_WORKSPACE_BASE = Path("/srv/workspaces/projects")
_SUMMITFLOW_PROJECT_ID = "summitflow"


async def _fetch_summitflow_json(endpoint: str, *, failure_log: str) -> dict[str, object] | None:
    """Fetch one SummitFlow API JSON response for heartbeat assembly."""
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(endpoint)
            response.raise_for_status()
            payload = response.json()
    except Exception:
        logger.debug(failure_log, exc_info=True)
        return None
    return payload if isinstance(payload, dict) else None


async def _fetch_task_overview_response(
    target_project_id: str | None = None,
) -> dict[str, object] | None:
    """Fetch canonical SummitFlow ready-all response via API."""
    api_base = _read_project_api_url(_SUMMITFLOW_PROJECT_ID)
    if not api_base:
        logger.debug("Missing SummitFlow API URL for heartbeat task overview")
        return None
    endpoint = (
        f"{api_base}/projects/{target_project_id}/tasks/ready-all"
        if target_project_id
        else f"{api_base}/tasks/ready-all"
    )
    return await _fetch_summitflow_json(
        endpoint,
        failure_log="Failed to fetch task overview for heartbeat prompt from SummitFlow API",
    )


async def _fetch_task_overview_payload(
    target_project_id: str | None = None,
) -> dict[str, object] | None:
    """Fetch structured ready-all payload from SummitFlow API."""
    response = await _fetch_task_overview_response(target_project_id)
    if not response:
        return None
    payload: object = response.get("payload")
    if not isinstance(payload, dict):
        return None
    return payload  # type: ignore[return-value]


async def _fetch_task_overview_raw(target_project_id: str | None = None) -> str:
    """Fetch canonical SummitFlow ready-all raw text via API."""
    response = await _fetch_task_overview_response(target_project_id)
    if not response:
        return ""
    raw = response.get("raw")
    return raw.strip() if isinstance(raw, str) else ""


async def _fetch_git_status_rows(
    target_project_id: str | None = None,
) -> list[RepoGitStatus]:
    """Fetch canonical SummitFlow git status rows via API."""
    from app.workflows._heartbeat_summitflow import _parse_git_status_rows

    api_base = _read_project_api_url(_SUMMITFLOW_PROJECT_ID)
    if not api_base:
        logger.debug("Missing SummitFlow API URL for heartbeat git status")
        return []
    endpoint = (
        f"{api_base}/projects/{target_project_id}/git/status"
        if target_project_id
        else f"{api_base}/git/status"
    )
    payload = await _fetch_summitflow_json(
        endpoint,
        failure_log="Failed to fetch git status for heartbeat prompt from SummitFlow API",
    )
    if not payload:
        return []
    repositories = payload.get("repositories", [])
    if not isinstance(repositories, list) or not repositories:
        return []
    return _parse_git_status_rows(repositories)


async def _fetch_git_status_compact(target_project_id: str | None = None) -> str:
    """Fetch canonical SummitFlow git status and render compact st-compatible output."""
    rows = await _fetch_git_status_rows(target_project_id)
    return build_compact_git_status(rows)


async def _fetch_cleanup_status_response(
    target_project_id: str | None = None,
) -> dict[str, object] | None:
    """Fetch canonical SummitFlow cleanup-status response via API."""
    api_base = _read_project_api_url(_SUMMITFLOW_PROJECT_ID)
    if not api_base:
        logger.debug("Missing SummitFlow API URL for heartbeat cleanup status")
        return None
    endpoint = (
        f"{api_base}/projects/{target_project_id}/git/cleanup-status"
        if target_project_id
        else f"{api_base}/git/cleanup-status"
    )
    return await _fetch_summitflow_json(
        endpoint,
        failure_log="Failed to fetch cleanup status for heartbeat prompt from SummitFlow API",
    )


async def _fetch_cleanup_status(target_project_id: str | None = None) -> str:
    """Fetch canonical SummitFlow cleanup status via API and return compact text."""
    response = await _fetch_cleanup_status_response(target_project_id)
    if not response:
        return ""
    compact = response.get("compact")
    return compact.strip() if isinstance(compact, str) else ""


async def _fetch_backup_status(target_project_id: str | None = None) -> str:
    """Fetch the compact latest-backup status line from structured SummitFlow data."""
    return await fetch_latest_backup_status_line(target_project_id)


async def _fetch_backup_schedule(target_project_id: str | None = None) -> str:
    """Fetch the compact backup-source schedule line from structured SummitFlow data."""
    return await fetch_backup_schedule_line(target_project_id)


async def _collect_summitflow_heartbeat_state(
    target_project_id: str | None = None,
) -> SummitFlowHeartbeatState:
    """Collect canonical SummitFlow truth once for heartbeat prompt assembly."""
    task_overview_response, cleanup_status_response, git_status_rows = await asyncio.gather(
        _fetch_task_overview_response(),
        _fetch_cleanup_status_response(target_project_id),
        _fetch_git_status_rows(target_project_id),
    )
    return SummitFlowHeartbeatState(
        task_overview_response=task_overview_response,
        cleanup_status_response=cleanup_status_response,
        git_status_rows=git_status_rows,
    )


async def _collect_agent_hub_heartbeat_state(
    target_project_id: str | None = None,
) -> AgentHubHeartbeatState:
    """Collect canonical Agent Hub truth once for heartbeat prompt assembly."""
    collected_at = datetime.now(UTC)
    active_sessions, active_specialist_sessions, workstream_rows = await asyncio.gather(
        _query_active_sessions_for_heartbeat(target_project_id, now=collected_at),
        _query_active_specialist_sessions(target_project_id, now=collected_at),
        _query_recent_workstream_sessions(target_project_id, now=collected_at),
    )
    return AgentHubHeartbeatState(
        collected_at=collected_at,
        active_sessions=active_sessions,
        active_specialist_sessions=active_specialist_sessions,
        workstream_rows=workstream_rows,
    )


async def _query_recent_workstream_sessions(
    target_project_id: str | None = None,
    *,
    now: datetime | None = None,
) -> list[dict[str, object]]:
    """Query workstream sessions from DB and collapse to deduplicated active rows."""
    from sqlalchemy import and_, or_, select

    from app.db import async_session
    from app.models import Session

    collected_at = now or datetime.now(UTC)
    cutoff = collected_at - timedelta(hours=_WORKSTREAM_LOOKBACK_HOURS)
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
                    Session.project_id == target_project_id if target_project_id else True,
                ))
                .order_by(Session.created_at.desc())
                .limit(50)
            )
        ).all()
    return collapse_active_workstream_rows(
        [_map_workstream_row(r, now=collected_at) for r in raw_rows]
    )


async def _fetch_task_overview(target_project_id: str | None = None) -> str:
    """Cross-project task overview condensed for heartbeat prompt injection."""
    payload = await _fetch_task_overview_payload(target_project_id)
    if payload is not None:
        return build_compact_task_overview_from_payload(payload)
    output = await _fetch_task_overview_raw(target_project_id)
    if not output:
        return ""
    return build_compact_task_overview(output)


def _filter_task_overview_for_project(task_overview: str, project_id: str) -> str:
    """Return the compact task overview narrowed to one project."""
    if not task_overview or not project_id:
        return task_overview
    project_lines: list[str] = []
    ready_lines: list[str] = []
    blocked_lines: list[str] = []
    stale_lines: list[str] = []
    current_section: str | None = None
    project_prefix = f"- {project_id} |"
    for raw_line in task_overview.splitlines():
        line = raw_line.rstrip()
        if not line:
            continue
        if line.startswith("PROJECTS["):
            current_section = "projects"
            continue
        if line.startswith("ACTIONABLE-READY["):
            current_section = "ready"
            continue
        if line.startswith("ACTIONABLE-BLOCKED["):
            current_section = "blocked"
            continue
        if line.startswith("ACTIONABLE-STALE["):
            current_section = "stale"
            continue
        if not line.startswith(project_prefix):
            continue
        if current_section == "projects":
            project_lines.append(line)
        elif current_section == "ready":
            ready_lines.append(line)
        elif current_section == "blocked":
            blocked_lines.append(line)
        elif current_section == "stale":
            stale_lines.append(line)
    sections: list[str] = []
    if project_lines:
        sections.append("PROJECTS[1]\n" + "\n".join(project_lines))
    if ready_lines:
        sections.append(f"ACTIONABLE-READY[{len(ready_lines)}]\n" + "\n".join(ready_lines))
    if blocked_lines:
        sections.append(f"ACTIONABLE-BLOCKED[{len(blocked_lines)}]\n" + "\n".join(blocked_lines))
    if stale_lines:
        sections.append(f"ACTIONABLE-STALE[{len(stale_lines)}]\n" + "\n".join(stale_lines))
    return "\n\n".join(sections)


async def _resolve_workstream_task_context(
    *,
    task_overview: str | None,
    task_overview_payload: dict[str, object] | None,
    heartbeat_state: SummitFlowHeartbeatState | None,
    target_project_id: str | None,
) -> tuple[bool, list[dict[str, str]], set[str], str]:
    """Resolve task overview data from state/payload/raw for workstream inventory."""
    if task_overview_payload is None and heartbeat_state is not None:
        task_overview_payload = heartbeat_state.task_overview_payload
    if task_overview is None and heartbeat_state is not None and task_overview_payload is None:
        task_overview = heartbeat_state.task_overview_raw
    if task_overview_payload is not None:
        return _resolve_task_overview_from_payload(
            task_overview_payload=task_overview_payload,
            task_overview=task_overview,
            target_project_id=target_project_id,
        )
    return await _resolve_task_overview_from_raw(
        task_overview=task_overview,
        target_project_id=target_project_id,
    )


async def _get_workstream_inventory(
    provider: str | None = None,
    *,
    task_overview: str | None = None,
    task_overview_payload: dict[str, object] | None = None,
    target_project_id: str | None = None,
    heartbeat_state: SummitFlowHeartbeatState | None = None,
    agent_hub_state: AgentHubHeartbeatState | None = None,
) -> str:
    """Build a heartbeat section that classifies active/recent work lanes."""
    try:
        queue_truth_available, stale_tasks, visible_task_ids, _ = (
            await _resolve_workstream_task_context(
                task_overview=task_overview,
                task_overview_payload=task_overview_payload,
                heartbeat_state=heartbeat_state,
                target_project_id=target_project_id,
            )
        )
        rows = (
            agent_hub_state.workstream_rows
            if agent_hub_state is not None
            else await _query_recent_workstream_sessions(target_project_id)
        )
        if not rows and not stale_tasks:
            return ""
        grouped = _group_rows_by_lane(rows)
        stale_keys = {(item["project_id"], item["task_id"]) for item in stale_tasks}
        if not grouped and not stale_tasks:
            return ""
        lines = _build_workstream_lines(
            grouped, stale_keys, visible_task_ids,
            queue_truth_available=queue_truth_available, provider=provider,
        )
        if len(lines) == 1:
            return ""
        return f"\n<workstream_inventory>\n{chr(10).join(lines)}\n</workstream_inventory>"
    except Exception:
        logger.debug("Failed to build workstream inventory for heartbeat", exc_info=True)
        return ""


def _resolve_task_overview_from_payload(
    *,
    task_overview_payload: dict[str, object],
    task_overview: str | None,
    target_project_id: str | None,
) -> tuple[bool, list[dict[str, str]], set[str], str]:
    """Resolve stale tasks and visible IDs from structured payload."""
    stale_tasks = [
        {"project_id": candidate.project_id, "task_id": candidate.task_id}
        for candidate in extract_stale_task_candidates_from_payload(
            task_overview_payload,
            per_project_limit=None,
            project_id=target_project_id,
        )
    ]
    visible_task_ids = collect_visible_task_ids_from_payload(
        task_overview_payload,
        project_id=target_project_id,
    )
    resolved = task_overview or build_compact_task_overview_from_payload(task_overview_payload)
    return True, stale_tasks, visible_task_ids, resolved


async def _resolve_task_overview_from_raw(
    *,
    task_overview: str | None,
    target_project_id: str | None,
) -> tuple[bool, list[dict[str, str]], set[str], str]:
    """Resolve stale tasks and visible IDs from raw task overview text."""
    if task_overview is None:
        task_overview = await _fetch_task_overview_raw(target_project_id)
    stale_tasks = [
        task
        for task in _parse_stale_running_tasks(task_overview)
        if not target_project_id or task["project_id"] == target_project_id
    ]
    visible_task_ids = {m.group(0) for m in _TASK_ID_PATTERN.finditer(task_overview)}
    return bool(task_overview), stale_tasks, visible_task_ids, task_overview


async def _fetch_active_sessions_section(
    target_project_id: str | None = None,
    *,
    agent_hub_state: AgentHubHeartbeatState | None = None,
) -> str:
    """Return a formatted section string for active sessions, or empty string."""
    try:
        sessions = (
            agent_hub_state.active_sessions
            if agent_hub_state is not None
            else await _query_active_sessions_for_heartbeat(target_project_id)
        )
        if not sessions:
            return ""
        collected_at = (
            agent_hub_state.collected_at
            if agent_hub_state is not None
            else datetime.now(UTC)
        )
        lines = [f"Active agent sessions: {len(sessions)}"]
        for s in sessions:
            lines.append(_format_active_session_entry(s, now=collected_at))
        return "\n".join(lines)
    except Exception:
        logger.debug("Failed to fetch active sessions for heartbeat prompt", exc_info=True)
        return ""


async def _fetch_recently_completed_sessions_section(
    target_project_id: str | None = None,
) -> str:
    """Show recently completed agent sessions with their summaries.

    Gives the persona automatic visibility into what dispatched agents accomplished.
    """
    try:
        now = datetime.now(UTC)
        rows, display_summaries = await _query_completed_sessions_with_summaries(
            target_project_id, now=now
        )
        if not rows:
            return ""
        rendered_rows = _render_completed_session_rows(rows, display_summaries, now)
        if not rendered_rows:
            return ""
        lines = [f"Recently completed sessions: {len(rendered_rows)}"]
        for _row, rendered in rendered_rows:
            lines.append(rendered)
        return "\n".join(lines)
    except Exception:
        logger.debug("Failed to fetch completed sessions for heartbeat prompt", exc_info=True)
        return ""


async def _query_completed_sessions_with_summaries(
    target_project_id: str | None,
    *,
    now: datetime,
) -> tuple[list[object], object]:
    """Query completed sessions and their display summaries from DB."""
    from sqlalchemy import and_, select

    from app.db import async_session
    from app.models import Session

    cutoff = now - timedelta(hours=2)
    async with async_session() as db:
        result = await db.execute(
            select(
                Session.id, Session.agent_slug, Session.project_id,
                Session.external_id, Session.summary_oneliner, Session.created_at,
            )
            .where(and_(
                Session.status == "completed",
                Session.created_at >= cutoff,
                Session.summary_oneliner.isnot(None),
                Session.agent_slug != "persona",
                Session.project_id == target_project_id if target_project_id else True,
            ))
            .order_by(Session.created_at.desc())
            .limit(10)
        )
        rows = list(result.all())
        display_summaries = await fetch_session_display_summary_results(
            db,
            [
                SessionDisplaySummaryCandidate(
                    session_id=row.id,
                    summary_oneliner=row.summary_oneliner,
                )
                for row in rows
            ],
        )
    return rows, display_summaries  # type: ignore[invalid-return-type]


def _render_completed_session_rows(
    rows: list[object],
    display_summaries: dict[object, object],
    now: datetime,
) -> list[tuple[object, str]]:
    """Filter and render completed session rows for heartbeat display."""
    rendered_rows: list[tuple[object, str]] = []
    for row in rows:
        external_id = str(getattr(row, "external_id", "") or "")
        if external_id.startswith(_BENCHMARK_EXTERNAL_ID_PREFIXES):
            continue
        ago = int((now - getattr(row, "created_at", now)).total_seconds() / 60)
        time_label = f"{ago}m ago" if ago < 60 else f"{ago // 60}h ago"
        summary_result = display_summaries.get(getattr(row, "id", None))
        if not _is_valid_summary_result(summary_result):
            continue
        rendered_rows.append((
            row,
            f"- {getattr(row, 'agent_slug', None) or '?'} on {getattr(row, 'project_id', '?')}: "
            f"{summary_result.summary} ({time_label})",  # type: ignore[union-attr]
        ))
    return rendered_rows


def _is_valid_summary_result(summary_result: object) -> bool:
    """Return True if a summary result is valid for heartbeat display."""
    if not summary_result:
        return False
    return bool(
        getattr(summary_result, "summary", None)
        and getattr(summary_result, "has_summary_tag", False)
        and getattr(summary_result, "summary_outcome", None) == "completed"
        and not getattr(summary_result, "has_unresolved_blocker", False)
    )


async def _get_active_specialist_inventory(
    target_project_id: str | None = None,
    *,
    agent_hub_state: AgentHubHeartbeatState | None = None,
) -> str:
    """Build a heartbeat section for active read-only/planning specialist sessions."""
    try:
        rows = (
            agent_hub_state.active_specialist_sessions
            if agent_hub_state is not None
            else await _query_active_specialist_sessions(target_project_id)
        )
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


async def _get_active_work_summary(
    *,
    task_overview: str | None = None,
    task_overview_payload: dict[str, object] | None = None,
    target_project_id: str | None = None,
    heartbeat_state: SummitFlowHeartbeatState | None = None,
    agent_hub_state: AgentHubHeartbeatState | None = None,
) -> str:
    """Build an <active_work> XML block with task overview, sessions, and completed sessions."""
    if task_overview_payload is None and heartbeat_state is not None:
        task_overview_payload = heartbeat_state.task_overview_payload
    if task_overview is None and heartbeat_state is not None and task_overview_payload is None:
        task_overview = heartbeat_state.task_overview_raw
    if task_overview is None and task_overview_payload is not None:
        task_overview = build_compact_task_overview_from_payload(task_overview_payload)
    if task_overview is None:
        task_overview = await _fetch_task_overview(target_project_id)
    visible_task_overview = (
        _filter_task_overview_for_project(task_overview, target_project_id)
        if target_project_id
        else task_overview
    )
    overview_stats = (
        parse_task_overview_stats_from_payload(task_overview_payload)
        if task_overview_payload is not None
        else parse_task_overview_stats(task_overview)
    )
    sessions_section = await _fetch_active_sessions_section(
        target_project_id,
        agent_hub_state=agent_hub_state,
    )
    suppress_completed = not target_project_id and (
        overview_stats.ready > 0 and overview_stats.active == 0 and overview_stats.stale == 0
    )
    completed_section = (
        ""
        if suppress_completed
        else await _fetch_recently_completed_sessions_section(target_project_id)
    )
    sections = [s for s in (visible_task_overview, sessions_section, completed_section) if s]
    if not sections:
        logger.info("Active work summary: empty (no tasks or sessions)")
        return ""
    body = "\n\n".join(sections)
    logger.info("Active work summary: %d section(s), %d chars", len(sections), len(body))
    return f"\n<active_work>\n{body}\n</active_work>"


async def _get_cleanup_status_summary(
    target_project_id: str | None = None,
    *,
    cleanup_status_response: dict[str, object] | None = None,
) -> str:
    """Build a <cleanup_status> XML block from the canonical st cleanup summary."""
    response = cleanup_status_response
    if response is None:
        response = await _fetch_cleanup_status_response(target_project_id)
    if not response:
        return ""
    output = response.get("compact")
    compact = output.strip() if isinstance(output, str) else ""
    payload = response.get("payload")
    actionable = (
        build_actionable_cleanup_summary_from_payload(payload)
        if isinstance(payload, dict)
        else build_actionable_cleanup_summary(compact)
    )
    if not compact and not actionable:
        return ""
    body = f"{compact}\n\n{actionable}" if actionable and compact else actionable or compact
    return f"\n<cleanup_status>\n{body}\n</cleanup_status>"


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


async def _get_git_status_summary(
    target_project_id: str | None = None,
    *,
    git_status_rows: list[RepoGitStatus] | None = None,
) -> str:
    """Build a <git_state> XML block from the canonical `st git status` surface."""
    rows = git_status_rows if git_status_rows is not None else await _fetch_git_status_rows(target_project_id)
    if not rows:
        return ""
    git_status = build_compact_git_status(rows)
    actionable = build_actionable_git_summary_from_rows(rows)
    body = f"{git_status}\n\n{actionable}" if actionable else git_status
    return f"\n<git_state>\n{body}\n</git_state>"


__all__ = [
    "AgentHubHeartbeatState",
    "SummitFlowHeartbeatState",
    "_build_workstream_next_action",
    "_classify_workstream_lane",
    "_collect_agent_hub_heartbeat_state",
    "_collect_summitflow_heartbeat_state",
    "_fetch_active_sessions_section",
    "_fetch_backup_schedule",
    "_fetch_backup_status",
    "_fetch_cleanup_status",
    "_fetch_git_status_compact",
    "_fetch_recently_completed_sessions_section",
    "_fetch_task_overview",
    "_fetch_task_overview_raw",
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
    "_session_display_health",
    "_session_stale_threshold_minutes",
    "get_project_access_summary",
]
