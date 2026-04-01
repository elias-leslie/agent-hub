"""Heartbeat orchestrator functions — high-level assembly and state collection.

These functions compose lower-level fetchers (in _heartbeat_data) and pure helpers
(in _heartbeat_workstream, _heartbeat_sessions, etc.) into heartbeat sections.

IO-bound fetchers patched in tests live in _heartbeat_data to keep patch paths valid.
This module handles orchestration logic that is NOT directly patched.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta

from app.services.cleanup_summary import (
    CleanupActionItem,
    build_actionable_cleanup_summary_from_items,
    build_filtered_reconciled_cleanup_note,
    extract_cleanup_action_items,
    extract_cleanup_action_items_from_payload,
)
from app.services.git_status_summary import (
    RepoGitStatus,
    build_actionable_git_summary_from_rows,
    build_compact_git_status,
)
from app.services.session_display_summary import SessionDisplaySummaryCandidate
from app.services.task_overview_summary import (
    build_compact_task_overview_from_payload,
    collect_visible_task_ids_from_payload,
    extract_stale_task_candidates_from_payload,
    parse_task_overview_stats,
    parse_task_overview_stats_from_payload,
)
from app.workflows._heartbeat_state import (
    _BENCHMARK_EXTERNAL_ID_PREFIXES,
    _TASK_ID_PATTERN,
    AgentHubHeartbeatState,
    SummitFlowHeartbeatState,
)

logger = logging.getLogger(__name__)

# Time window constants
_COMPLETED_SESSION_LOOKBACK_HOURS = 2
_COMPLETED_SESSION_LIMIT = 10

# Task overview section definitions: (header_prefix, bucket_key, output_label, always_count_one)
# Projects always renders as count=1 for single-project filters.
_TASK_SECTIONS: tuple[tuple[str, str, str, bool], ...] = (
    ("PROJECTS[",          "projects", "PROJECTS",          True),
    ("ACTIONABLE-READY[",  "ready",    "ACTIONABLE-READY",  False),
    ("ACTIONABLE-BLOCKED[","blocked",  "ACTIONABLE-BLOCKED", False),
    ("ACTIONABLE-STALE[",  "stale",    "ACTIONABLE-STALE",  False),
)

# Session / lane classification constants
_SESSION_STATUS_COMPLETED = "completed"
_PERSONA_AGENT_SLUG = "persona"
_LANE_RECONCILED = "reconciled"

# Cleanup response payload keys
_CLEANUP_KEY_COMPACT = "compact"
_CLEANUP_KEY_PAYLOAD = "payload"

# Display labels
_SPECIALIST_SESSIONS_HEADER = "Active specialist sessions:"


# --- Task overview resolution helpers ---


def _filter_task_overview_for_project(task_overview: str, project_id: str) -> str:
    """Return the compact task overview narrowed to one project."""
    if not task_overview or not project_id:
        return task_overview
    buckets: dict[str, list[str]] = {key: [] for _, key, _, _ in _TASK_SECTIONS}
    current_key: str | None = None
    project_prefix = f"- {project_id} |"
    for raw_line in task_overview.splitlines():
        line = raw_line.rstrip()
        if not line:
            continue
        matched = next((key for pfx, key, _, _ in _TASK_SECTIONS if line.startswith(pfx)), None)
        if matched is not None:
            current_key = matched
            continue
        if current_key and line.startswith(project_prefix):
            buckets[current_key].append(line)
    sections: list[str] = []
    for _, key, label, is_single in _TASK_SECTIONS:
        if buckets[key]:
            count = 1 if is_single else len(buckets[key])
            sections.append(f"{label}[{count}]\n" + "\n".join(buckets[key]))
    return "\n\n".join(sections)


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
    from app.workflows._heartbeat_data import _fetch_task_overview_raw
    from app.workflows._heartbeat_workstream import _parse_stale_running_tasks

    if task_overview is None:
        task_overview = await _fetch_task_overview_raw(target_project_id)
    stale_tasks = [
        task
        for task in _parse_stale_running_tasks(task_overview)
        if not target_project_id or task["project_id"] == target_project_id
    ]
    visible_task_ids = {m.group(0) for m in _TASK_ID_PATTERN.finditer(task_overview)}
    return bool(task_overview), stale_tasks, visible_task_ids, task_overview


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


async def _coerce_task_overview(
    task_overview: str | None,
    task_overview_payload: dict[str, object] | None,
    heartbeat_state: SummitFlowHeartbeatState | None,
    target_project_id: str | None,
) -> str:
    """Resolve task overview text from state, payload, or raw fetch."""
    from app.workflows._heartbeat_data import _fetch_task_overview, _fetch_task_overview_raw

    if task_overview_payload is None and heartbeat_state is not None:
        task_overview_payload = heartbeat_state.task_overview_payload
    if task_overview is None and heartbeat_state is not None and task_overview_payload is None:
        task_overview = heartbeat_state.task_overview_raw
    if task_overview is None and task_overview_payload is not None:
        task_overview = build_compact_task_overview_from_payload(task_overview_payload)
    if task_overview is None:
        task_overview = await _fetch_task_overview(target_project_id)
        if not task_overview:
            task_overview = await _fetch_task_overview_raw(target_project_id)
    return task_overview or ""


# --- Completed session helpers ---


async def _query_completed_sessions_with_summaries(
    target_project_id: str | None,
    *,
    now: datetime,
) -> tuple[list[object], object]:
    """Query completed sessions and their display summaries from DB."""
    from sqlalchemy import and_, select

    from app.db import async_session
    from app.models import Session
    from app.workflows._heartbeat_data import fetch_session_display_summary_results

    cutoff = now - timedelta(hours=_COMPLETED_SESSION_LOOKBACK_HOURS)
    async with async_session() as db:
        result = await db.execute(
            select(
                Session.id, Session.agent_slug, Session.project_id,
                Session.external_id, Session.summary_oneliner, Session.created_at,
            )
            .where(and_(
                Session.status == _SESSION_STATUS_COMPLETED,
                Session.created_at >= cutoff,
                Session.summary_oneliner.isnot(None),
                Session.agent_slug != _PERSONA_AGENT_SLUG,
                Session.project_id == target_project_id if target_project_id else True,
            ))
            .order_by(Session.created_at.desc())
            .limit(_COMPLETED_SESSION_LIMIT)
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
    return rows, display_summaries  # type: ignore[return-value]


def _is_valid_summary_result(summary_result: object) -> bool:
    """Return True if a summary result is valid for heartbeat display."""
    if not summary_result:
        return False
    return bool(
        getattr(summary_result, "summary", None)
        and getattr(summary_result, "has_summary_tag", False)
        and getattr(summary_result, "summary_outcome", None) == _SESSION_STATUS_COMPLETED
        and not getattr(summary_result, "has_unresolved_blocker", False)
    )


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


# --- State collectors ---


async def _collect_summitflow_heartbeat_state(
    target_project_id: str | None = None,
) -> SummitFlowHeartbeatState:
    """Collect canonical SummitFlow truth once for heartbeat prompt assembly."""
    from app.workflows._heartbeat_data import (
        _fetch_cleanup_status_response,
        _fetch_git_status_rows,
        _fetch_recent_failed_tasks,
        _fetch_task_overview_response,
    )

    task_overview_response, cleanup_status_response, git_status_rows, recent_failed_tasks = await asyncio.gather(
        _fetch_task_overview_response(),
        _fetch_cleanup_status_response(target_project_id),
        _fetch_git_status_rows(target_project_id),
        _fetch_recent_failed_tasks(target_project_id),
    )
    return SummitFlowHeartbeatState(
        task_overview_response=task_overview_response,
        cleanup_status_response=cleanup_status_response,
        git_status_rows=git_status_rows,
        recent_failed_tasks=recent_failed_tasks,
    )


async def _collect_agent_hub_heartbeat_state(
    target_project_id: str | None = None,
) -> AgentHubHeartbeatState:
    """Collect canonical Agent Hub truth once for heartbeat prompt assembly."""
    from app.workflows._heartbeat_data import (
        _query_active_sessions_for_heartbeat,
        _query_active_specialist_sessions,
        _query_recent_workstream_sessions,
    )

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


# --- Heartbeat section builders ---


def _filter_reconciled_cleanup_items(
    items: list[CleanupActionItem],
    workstream_rows: list[dict[str, object]] | None,
) -> list[CleanupActionItem]:
    """Drop cleanup actions for tasks already classified as reconciled lanes."""
    from app.workflows._heartbeat_workstream import (
        _classify_workstream_lane,
        _group_rows_by_lane,
        _infer_lane_task_id,
    )

    if not items or not workstream_rows:
        return items
    reconciled_task_keys: set[tuple[str, str]] = set()
    for (project_id, _lane_key), lane_rows in _group_rows_by_lane(workstream_rows).items():
        if _classify_workstream_lane(lane_rows) != _LANE_RECONCILED:
            continue
        task_id = _infer_lane_task_id(lane_rows)
        if task_id:
            reconciled_task_keys.add((project_id, task_id))
    if not reconciled_task_keys:
        return items
    return [
        item for item in items
        if (item.project_id, item.task_id) not in reconciled_task_keys
    ]


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
    from app.workflows._heartbeat_data import _query_recent_workstream_sessions
    from app.workflows._heartbeat_workstream import _build_workstream_lines, _group_rows_by_lane

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
        top_task = failed_tasks[0]
        top_project_id = str(top_task.get("project_id") or "unknown")
        top_task_id = str(top_task.get("id") or "unknown")
        top_title = str(top_task.get("title") or "Untitled task")
        top_phase = str(top_task.get("current_phase") or "").strip()
        top_details = [
            top_project_id,
            top_task_id,
            "failed",
            _format_recent_failed_task_age(top_task.get("last_changed_at"), now=now),
        ]
        if top_phase:
            top_details.append(f"phase={top_phase}")
        lines.append(f"Follow first: {' | '.join(top_details)} | {top_title}")
        for task in failed_tasks:
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
            lines.append(line)
        return f"\n<recent_failed_tasks>\n{chr(10).join(lines)}\n</recent_failed_tasks>"
    except Exception:
        logger.debug("Failed to build recent failed tasks summary for heartbeat", exc_info=True)
        return ""


async def _get_active_specialist_inventory(
    target_project_id: str | None = None,
    *,
    agent_hub_state: AgentHubHeartbeatState | None = None,
) -> str:
    """Build a heartbeat section for active read-only/planning specialist sessions."""
    from app.workflows._heartbeat_data import _query_active_specialist_sessions
    from app.workflows._heartbeat_sessions import _format_specialist_group_line

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
        lines = [_SPECIALIST_SESSIONS_HEADER]
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
    from app.workflows._heartbeat_data import (
        _fetch_active_sessions_section,
        _fetch_recently_completed_sessions_section,
    )

    task_overview = await _coerce_task_overview(
        task_overview, task_overview_payload, heartbeat_state, target_project_id
    )
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
    workstream_rows: list[dict[str, object]] | None = None,
) -> str:
    """Build a <cleanup_status> XML block from the canonical st cleanup summary."""
    from app.workflows._heartbeat_data import _fetch_cleanup_status_response

    response = cleanup_status_response
    if response is None:
        response = await _fetch_cleanup_status_response(target_project_id)
    if not response:
        return ""
    output = response.get(_CLEANUP_KEY_COMPACT)
    compact = output.strip() if isinstance(output, str) else ""
    payload = response.get(_CLEANUP_KEY_PAYLOAD)
    items = (
        extract_cleanup_action_items_from_payload(payload)
        if isinstance(payload, dict)
        else extract_cleanup_action_items(compact)
    )
    filtered_items = _filter_reconciled_cleanup_items(items, workstream_rows)
    actionable = (
        build_actionable_cleanup_summary_from_items(filtered_items)
        or build_filtered_reconciled_cleanup_note(items, filtered_items)
    )
    if not compact and not actionable:
        return ""
    body = f"{compact}\n\n{actionable}" if actionable and compact else actionable or compact
    return f"\n<cleanup_status>\n{body}\n</cleanup_status>"


async def _get_protection_status_summary(target_project_id: str | None = None) -> str:
    """Build a <protection_status> XML block from canonical backup surfaces."""
    from app.workflows._heartbeat_data import _fetch_backup_schedule, _fetch_backup_status

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
    from app.workflows._heartbeat_data import _fetch_git_status_rows

    rows = git_status_rows if git_status_rows is not None else await _fetch_git_status_rows(target_project_id)
    if not rows:
        return ""
    git_status = build_compact_git_status(rows)
    actionable = build_actionable_git_summary_from_rows(rows)
    body = f"{git_status}\n\n{actionable}" if actionable else git_status
    return f"\n<git_state>\n{body}\n</git_state>"
