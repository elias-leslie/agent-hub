"""Heartbeat orchestrator functions — high-level assembly and state collection.

These functions compose lower-level fetchers (in _heartbeat_data) and pure helpers
(in _heartbeat_workstream, _heartbeat_sessions, etc.) into heartbeat sections.

IO-bound fetchers patched in tests live in _heartbeat_data to keep patch paths valid.
This module handles orchestration logic that is NOT directly patched.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime

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
from app.services.task_overview_summary import (
    parse_task_overview_stats,
    parse_task_overview_stats_from_payload,
)
from app.workflows._heartbeat_project import get_permitted_project_ids

# Re-export helpers consumed by callers outside this module
from app.workflows._heartbeat_state import (
    AgentHubHeartbeatState,
    SummitFlowHeartbeatState,
)
from app.workflows._heartbeat_task_overview import (
    _coerce_task_overview,
    _filter_task_overview_for_project,
    _resolve_workstream_task_context,
)

logger = logging.getLogger(__name__)

_CLEANUP_KEY_COMPACT = "compact"
_CLEANUP_KEY_PAYLOAD = "payload"
_SPECIALIST_SESSIONS_HEADER = "Active specialist sessions:"
_LANE_RECONCILED = "reconciled"
_QUEUE_TRUTH_SKIPPABLE_LANE_STATES = frozenset({"active", "mixed", "stale_active"})
_WORKSTREAM_INVENTORY_TAG = "workstream_inventory"
_ACTIVE_SPECIALIST_INVENTORY_TAG = "active_specialist_inventory"
_ACTIVE_WORK_TAG = "active_work"
_CLEANUP_STATUS_TAG = "cleanup_status"
_PROTECTION_STATUS_TAG = "protection_status"
_GIT_STATE_TAG = "git_state"
_SECTION_SEPARATOR = "\n---\n"
_BLOCK_SEPARATOR = "\n\n"


async def _get_recent_failed_tasks_summary(
    target_project_id: str | None = None,
    *,
    heartbeat_state: SummitFlowHeartbeatState | None = None,
) -> str:
    """Delegate recent-failed-task rendering through the stable orchestrator seam."""
    from app.workflows._heartbeat_failed_tasks import (
        _get_recent_failed_tasks_summary as _impl,
    )

    return await _impl(
        target_project_id,
        heartbeat_state=heartbeat_state,
    )


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

    task_overview_response, cleanup_status_response, git_status_rows, recent_failed_tasks = (
        await asyncio.gather(
            _fetch_task_overview_response(),
            _fetch_cleanup_status_response(target_project_id),
            _fetch_git_status_rows(target_project_id),
            _fetch_recent_failed_tasks(target_project_id),
        )
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


def _wrap_section(tag: str, body: str) -> str:
    return f"\n<{tag}>\n{body}\n</{tag}>"


def _join_present(sections: tuple[str, ...] | list[str], separator: str) -> str:
    return separator.join(section for section in sections if section)


def _group_specialist_rows(
    rows: list[dict[str, object]],
) -> dict[tuple[str, str], list[dict[str, object]]]:
    grouped: dict[tuple[str, str], list[dict[str, object]]] = {}
    for row in rows:
        key = (str(row["project_id"]), str(row["agent_slug"]))
        grouped.setdefault(key, []).append(row)
    return grouped


def _should_resolve_queue_truth(
    rows: list[dict[str, object]],
    lane_states: set[str],
    *,
    task_overview: str | None,
    task_overview_payload: dict[str, object] | None,
    heartbeat_state: SummitFlowHeartbeatState | None,
) -> bool:
    return (
        task_overview is not None
        or task_overview_payload is not None
        or heartbeat_state is not None
        or not rows
        or not lane_states
        or not lane_states.issubset(_QUEUE_TRUTH_SKIPPABLE_LANE_STATES)
    )


def _extract_cleanup_items(
    response: dict[str, object],
) -> tuple[str, list[CleanupActionItem]]:
    output = response.get(_CLEANUP_KEY_COMPACT)
    compact = output.strip() if isinstance(output, str) else ""
    payload = response.get(_CLEANUP_KEY_PAYLOAD)
    items = (
        extract_cleanup_action_items_from_payload(payload)
        if isinstance(payload, dict)
        else extract_cleanup_action_items(compact)
    )
    return compact, items


def _build_cleanup_body(
    compact: str,
    items: list[CleanupActionItem],
    workstream_rows: list[dict[str, object]] | None,
) -> str:
    filtered_items = _filter_reconciled_cleanup_items(items, workstream_rows)
    actionable = (
        build_actionable_cleanup_summary_from_items(filtered_items)
        or build_filtered_reconciled_cleanup_note(items, filtered_items)
    )
    return _join_present([compact, actionable], _BLOCK_SEPARATOR)


def _filter_git_rows(
    rows: list[RepoGitStatus],
    allowed_project_ids: set[str] | None,
) -> list[RepoGitStatus]:
    if allowed_project_ids is None:
        return rows
    return [row for row in rows if row.project_id in allowed_project_ids]


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
    from app.workflows._heartbeat_workstream import (
        _build_workstream_lines,
        _classify_workstream_lane,
        _group_rows_by_lane,
    )

    try:
        rows = (
            agent_hub_state.workstream_rows
            if agent_hub_state is not None
            else await _query_recent_workstream_sessions(target_project_id)
        )
        grouped = _group_rows_by_lane(rows)
        lane_states = {
            _classify_workstream_lane(lane_rows)
            for lane_rows in grouped.values()
        }

        if _should_resolve_queue_truth(
            rows,
            lane_states,
            task_overview=task_overview,
            task_overview_payload=task_overview_payload,
            heartbeat_state=heartbeat_state,
        ):
            queue_truth_available, stale_tasks, visible_task_ids, _ = (
                await _resolve_workstream_task_context(
                    task_overview=task_overview,
                    task_overview_payload=task_overview_payload,
                    heartbeat_state=heartbeat_state,
                    target_project_id=target_project_id,
                )
            )
        else:
            queue_truth_available = False
            stale_tasks = []
            visible_task_ids = set()

        if not grouped and not stale_tasks:
            return ""
        stale_keys = {(item["project_id"], item["task_id"]) for item in stale_tasks}
        lines = _build_workstream_lines(
            grouped,
            stale_keys,
            visible_task_ids,
            queue_truth_available=queue_truth_available,
            provider=provider,
        )
        if len(lines) == 1:
            return ""
        return _wrap_section(_WORKSTREAM_INVENTORY_TAG, "\n".join(lines))
    except Exception:
        logger.debug("Failed to build workstream inventory for heartbeat", exc_info=True)
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
        lines = [_SPECIALIST_SESSIONS_HEADER]
        for (project_id, agent_slug), group_rows in sorted(_group_specialist_rows(rows).items()):
            lines.append(_format_specialist_group_line(project_id, agent_slug, group_rows))
        return _wrap_section(_ACTIVE_SPECIALIST_INVENTORY_TAG, "\n".join(lines))
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
    body = _join_present(
        [visible_task_overview, sessions_section, completed_section],
        _BLOCK_SEPARATOR,
    )
    if not body:
        logger.info("Active work summary: empty (no tasks or sessions)")
        return ""
    logger.info(
        "Active work summary: %d section(s), %d chars",
        len([section for section in (visible_task_overview, sessions_section, completed_section) if section]),
        len(body),
    )
    return _wrap_section(_ACTIVE_WORK_TAG, body)


async def _get_cleanup_status_summary(
    target_project_id: str | None = None,
    *,
    cleanup_status_response: dict[str, object] | None = None,
    workstream_rows: list[dict[str, object]] | None = None,
) -> str:
    """Build a <cleanup_status> XML block from the canonical st cleanup summary."""
    from app.workflows._heartbeat_data import _fetch_cleanup_status_response

    response = cleanup_status_response or await _fetch_cleanup_status_response(target_project_id)
    if not response:
        return ""
    compact, items = _extract_cleanup_items(response)
    body = _build_cleanup_body(compact, items, workstream_rows)
    if not body:
        return ""
    return _wrap_section(_CLEANUP_STATUS_TAG, body)


async def _get_protection_status_summary(target_project_id: str | None = None) -> str:
    """Build a <protection_status> XML block from canonical backup surfaces."""
    from app.workflows._heartbeat_data import _fetch_backup_schedule, _fetch_backup_status

    latest, schedule = await asyncio.gather(
        _fetch_backup_status(target_project_id),
        _fetch_backup_schedule(target_project_id),
    )
    body = _join_present([latest, schedule], _SECTION_SEPARATOR)
    if not body:
        return ""
    return _wrap_section(_PROTECTION_STATUS_TAG, body)


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
    allowed_project_ids = {target_project_id} if target_project_id else await get_permitted_project_ids()
    rows = _filter_git_rows(rows, allowed_project_ids)
    if not rows:
        return ""
    git_status = build_compact_git_status(rows)
    actionable = build_actionable_git_summary_from_rows(rows)
    body = _join_present([git_status, actionable], _BLOCK_SEPARATOR)
    return _wrap_section(_GIT_STATE_TAG, body)
