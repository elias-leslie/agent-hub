"""Data-fetching helpers for the heartbeat prompt.

Patchable IO fetchers live here; orchestration and pure helpers are in focused sub-modules:
  _heartbeat_state         — dataclasses and constants
  _heartbeat_project       — project access/index reading
  _heartbeat_sessions      — session formatting helpers and specialist inventory
  _heartbeat_workstream    — lane classification and formatting helpers
  _heartbeat_sections      — roster, feedback, agent tool summary
  _heartbeat_orchestrators — state collectors and section builders
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

import httpx

from app.services.backup_summary import (
    fetch_backup_schedule_line,
    fetch_latest_backup_status_line,
)
from app.services.git_status_summary import RepoGitStatus
from app.services.ownership_lanes import collapse_active_workstream_rows
from app.services.session_display_summary import (
    SessionDisplaySummaryCandidate,
    SessionDisplaySummaryResult,
    clean_display_summary_text,
    fetch_session_display_summary_results,
)
from app.services.task_overview_summary import (
    build_compact_task_overview,
    build_compact_task_overview_from_payload,
)
from app.services.token_counter import count_tokens

# Re-export orchestrators (these are patched via _heartbeat_prompt.* in tests)
from app.workflows._heartbeat_orchestrators import (
    _collect_agent_hub_heartbeat_state,
    _collect_summitflow_heartbeat_state,
    _get_active_specialist_inventory,
    _get_active_work_summary,
    _get_cleanup_status_summary,
    _get_git_status_summary,
    _get_protection_status_summary,
    _get_workstream_inventory,
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

# Re-export pure session formatting helpers
from app.workflows._heartbeat_sessions import (
    _format_active_session_entry,
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
    _build_workstream_next_action,
    _classify_workstream_lane,
    _map_workstream_row,
)

logger = logging.getLogger(__name__)

# ── timing & limits ───────────────────────────────────────────────────────────
_WORKSTREAM_LOOKBACK_HOURS = 24
_SUMMITFLOW_PROJECT_ID = "summitflow"
_HEARTBEAT_DIGEST_LOOKBACK_HOURS = 6
_HEARTBEAT_DIGEST_LIMIT = 4
_HEARTBEAT_DIGEST_TOKEN_BUDGET = 420
_IDLE_HISTORY_LOOKBACK_HOURS = 6
_IDLE_HISTORY_LIMIT = 4
_IDLE_HISTORY_TOKEN_BUDGET = 360
_FAILED_TASK_LOOKBACK_HOURS = 48
_FAILED_TASK_PER_PROJECT_LIMIT = 3
_FAILED_TASK_GLOBAL_LIMIT = 8

# ── magic strings ─────────────────────────────────────────────────────────────
_PERSONA_AGENT_SLUG = "persona"
_HEARTBEAT_REQUEST_SOURCE = "heartbeat"
_TASK_BRANCH_PATTERN = "task-%"
_TIMESTAMP_FORMAT = "%H:%M UTC"
_HEARTBEAT_DIGEST_TAG = "recent_heartbeat_digest"
_HEARTBEAT_DIGEST_HEADING = "Recent heartbeat recall"
_IDLE_HISTORY_TAG = "recent_idle_improvement_history"
_IDLE_HISTORY_HEADING = "Recent idle slices"

# ── marker tuples ─────────────────────────────────────────────────────────────
_IDLE_SUMMARY_MARKERS = (
    "clean and idle",
    "clean-idle",
    "no ready or cleanup work",
    "no actionable work",
    "no new scoped target",
    "no new scoped defect",
    "no new execution-ready target",
)
_IDLE_FAILURE_MARKERS = (
    "failed",
    "failure",
    "invalid",
    "blocked",
    "timed out",
    "did not exist",
    "no such file",
)
_HEARTBEAT_DIGEST_STATUSES = (
    "completed",
    "failed",
)


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
    return payload if isinstance(payload, dict) else None  # type: ignore[return-value]


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
    from app.services.git_status_summary import build_compact_git_status

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


def _parse_recent_failed_task_timestamp(value: object) -> datetime | None:
    if isinstance(value, datetime):
        dt_value = value
    else:
        text = str(value or "").strip()
        if not text:
            return None
        try:
            dt_value = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
    if dt_value.tzinfo is None:
        return dt_value.replace(tzinfo=UTC)
    return dt_value.astimezone(UTC)


def _recent_failed_task_sort_key(task: dict[str, object]) -> datetime:
    timestamp = _parse_recent_failed_task_timestamp(task.get("last_changed_at"))
    if timestamp is None:
        return datetime.min.replace(tzinfo=UTC)
    return timestamp


async def _fetch_recent_failed_tasks(
    target_project_id: str | None = None,
) -> list[dict[str, object]]:
    """Fetch recent failed tasks that heartbeat should inspect before new dispatch or clean idle."""
    try:
        from sqlalchemy import select

        from app.db import get_async_session_context
        from app.models.task import Task

        cutoff = datetime.now(UTC) - timedelta(hours=_FAILED_TASK_LOOKBACK_HOURS)
        async with get_async_session_context() as session:
            stmt = select(Task).where(
                Task.status == "failed",
                Task.updated_at >= cutoff,
            )
            if target_project_id:
                stmt = stmt.where(Task.project_id == target_project_id)
            stmt = stmt.order_by(Task.updated_at.desc()).limit(_FAILED_TASK_GLOBAL_LIMIT)
            result = await session.execute(stmt)
            tasks = list(result.scalars())

        rows: list[dict[str, object]] = []
        per_project_counts: dict[str, int] = {}
        for task in tasks:
            project_id = str(task.project_id or "")
            count = per_project_counts.get(project_id, 0)
            if count >= _FAILED_TASK_PER_PROJECT_LIMIT:
                continue
            per_project_counts[project_id] = count + 1
            rows.append(
                {
                    "id": task.id,
                    "project_id": project_id,
                    "title": task.title,
                    "current_phase": task.current_phase,
                    "error_message": task.error_message,
                    "last_changed_at": task.updated_at,
                }
            )

        rows.sort(key=_recent_failed_task_sort_key, reverse=True)
        return rows
    except Exception:
        logger.debug("Failed to fetch recent failed tasks for heartbeat prompt", exc_info=True)
        return []


async def _query_recent_workstream_sessions(
    target_project_id: str | None = None,
    *,
    now: datetime | None = None,
) -> list[dict[str, object]]:
    """Query workstream sessions from DB and collapse to deduplicated active rows."""
    from sqlalchemy import and_, func, or_, select

    from app.db import async_session
    from app.models import Session

    collected_at = now or datetime.now(UTC)
    cutoff = collected_at - timedelta(hours=_WORKSTREAM_LOOKBACK_HOURS)
    # current_branch.like("task-%/%") was the third criterion before the lease
    # migration eliminated per-task branches. Sessions are still matched via
    # workstream_status (the lease-era marker) and external_id (the canonical
    # task id when the session is task-scoped).
    lane_or_reconciled_scope = or_(
        Session.workstream_status.isnot(None),
        Session.external_id.like(_TASK_BRANCH_PATTERN),
    )
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
                    lane_or_reconciled_scope,
                    Session.project_id == target_project_id if target_project_id else True,
                ))
                .order_by(
                    func.coalesce(
                        Session.workstream_updated_at,
                        Session.updated_at,
                        Session.created_at,
                    ).desc(),
                    Session.created_at.desc(),
                )
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
    from app.workflows._heartbeat_completed_sessions import (
        _query_completed_sessions_with_summaries,
        _render_completed_session_rows,
    )

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


def _extract_live_activity_summary(provider_metadata: dict[str, object] | None) -> str | None:
    """Return the live activity summary from provider metadata when present."""
    if not isinstance(provider_metadata, dict):
        return None
    live_activity = provider_metadata.get("live_activity")
    if not isinstance(live_activity, dict):
        return None
    summary = live_activity.get("summary")
    return summary if isinstance(summary, str) else None


def _render_budgeted_rows_section(
    *,
    tag: str,
    heading: str,
    rows: list[str],
    token_budget: int,
) -> str:
    """Render a compact recall section within a prompt token budget."""
    if not rows:
        return ""

    def _build(rs: list[str]) -> str:
        return f"\n<{tag}>\n{heading}: {len(rs)}\n" + "\n".join(rs) + f"\n</{tag}>"

    selected_rows: list[str] = []
    for row in rows:
        proposed = [*selected_rows, row]
        if selected_rows and count_tokens(_build(proposed)) > token_budget:
            break
        selected_rows = proposed
        if count_tokens(_build(selected_rows)) > token_budget:
            break
    return _build(selected_rows) if selected_rows else ""


def _row_value(row: object, index: int, attr: str) -> object:
    """Read one selected-column value from a SQLAlchemy row or plain tuple."""
    if hasattr(row, attr):
        return getattr(row, attr)
    if isinstance(row, tuple):
        return row[index]
    try:
        return row[index]  # type: ignore[index]
    except Exception:
        return None


# ── heartbeat digest helpers ──────────────────────────────────────────────────


def _build_digest_candidates(rows: list[object]) -> list[SessionDisplaySummaryCandidate]:
    """Build display-summary candidates from raw heartbeat digest rows."""
    return [
        SessionDisplaySummaryCandidate(
            session_id=str(_row_value(row, 0, "id") or ""),
            summary_oneliner=(
                _row_value(row, 4, "summary_oneliner")
                if isinstance(_row_value(row, 4, "summary_oneliner"), str)
                else None
            ),
            live_summary=_extract_live_activity_summary(
                _row_value(row, 5, "provider_metadata")
                if isinstance(_row_value(row, 5, "provider_metadata"), dict)
                else None
            ),
        )
        for row in rows
        if _row_value(row, 0, "id")
    ]


async def _query_heartbeat_digest_data(
    target_project_id: str | None,
) -> tuple[list[object], dict[str, SessionDisplaySummaryResult]]:
    """Query recent heartbeat sessions and their display summaries."""
    from sqlalchemy import and_, select

    from app.db import async_session
    from app.models import Session

    cutoff = datetime.now(UTC) - timedelta(hours=_HEARTBEAT_DIGEST_LOOKBACK_HOURS)
    conditions = [
        Session.agent_slug == _PERSONA_AGENT_SLUG,
        Session.request_source == _HEARTBEAT_REQUEST_SOURCE,
        Session.status.in_(_HEARTBEAT_DIGEST_STATUSES),
        Session.created_at >= cutoff,
    ]
    if target_project_id:
        conditions.append(Session.project_id == target_project_id)

    async with async_session() as db:
        result = await db.execute(
            select(
                Session.id, Session.project_id, Session.status,
                Session.created_at, Session.summary_oneliner, Session.provider_metadata,
            )
            .where(and_(*conditions))
            .order_by(Session.created_at.desc())
            .limit(_HEARTBEAT_DIGEST_LIMIT)
        )
        rows: list[object] = list(result.all())
        display_summaries = await fetch_session_display_summary_results(
            db, _build_digest_candidates(rows)
        )
    return rows, display_summaries


def _render_heartbeat_digest_row(
    row: object,
    display_summaries: dict[str, SessionDisplaySummaryResult],
) -> str | None:
    """Render one heartbeat digest row, returning None when no summary is available."""
    session_id = str(_row_value(row, 0, "id") or "")
    if not session_id:
        return None
    project_id = str(_row_value(row, 1, "project_id") or "unknown")
    status = str(_row_value(row, 2, "status") or "unknown")
    created_at = _row_value(row, 3, "created_at")
    summary_oneliner = _row_value(row, 4, "summary_oneliner")
    provider_metadata = _row_value(row, 5, "provider_metadata")
    display_result = display_summaries.get(session_id)
    display_summary = display_result if isinstance(display_result, str) else getattr(display_result, "summary", None)
    summary = (
        clean_display_summary_text(display_summary)
        or clean_display_summary_text(summary_oneliner if isinstance(summary_oneliner, str) else None)
        or clean_display_summary_text(
            _extract_live_activity_summary(provider_metadata if isinstance(provider_metadata, dict) else None)
        )
    )
    if not summary:
        return None
    timestamp = (
        created_at.astimezone(UTC).strftime(_TIMESTAMP_FORMAT)
        if isinstance(created_at, datetime)
        else "unknown"
    )
    return f"- {timestamp} | {status} | {project_id} | {summary}"


async def _get_recent_heartbeat_digest(target_project_id: str | None = None) -> str:
    """Show a compact digest of recent heartbeat outcomes for bounded recall."""
    try:
        rows, display_summaries = await _query_heartbeat_digest_data(target_project_id)
    except Exception:
        logger.debug("Failed to fetch recent heartbeat digest", exc_info=True)
        return ""
    rendered_rows = [
        r for row in rows
        if (r := _render_heartbeat_digest_row(row, display_summaries)) is not None
    ]
    if not rendered_rows:
        return ""
    return _render_budgeted_rows_section(
        tag=_HEARTBEAT_DIGEST_TAG,
        heading=_HEARTBEAT_DIGEST_HEADING,
        rows=rendered_rows,
        token_budget=_HEARTBEAT_DIGEST_TOKEN_BUDGET,
    )


# ── idle improvement history helpers ─────────────────────────────────────────


def _extract_idle_validation_command(provider_metadata: dict[str, object] | None) -> str | None:
    """Return the compact validation command for an idle heartbeat session."""
    if not isinstance(provider_metadata, dict):
        return None
    live_activity = provider_metadata.get("live_activity")
    if not isinstance(live_activity, dict):
        return None
    raw_command = live_activity.get("last_validation_command") or live_activity.get("last_command")
    if not isinstance(raw_command, str):
        return None
    compact = raw_command.split("&&")[-1].strip()
    return compact or None


def _idle_validation_label(session: object) -> str:
    """Return whether the idle-history command was verified or only attempted."""
    summary = str(getattr(session, "summary_oneliner", "")).strip().lower()
    if any(marker in summary for marker in _IDLE_FAILURE_MARKERS):
        return "attempt"
    return "verify"


def _is_recent_idle_slice_session(session: object) -> bool:
    """Return True when the session represents a clean-idle improvement slice."""
    summary = getattr(session, "summary_oneliner", None)
    if not isinstance(summary, str):
        return False
    for attr in ("summary_files_touched", "observed_write_paths"):
        value = getattr(session, attr, None)
        if isinstance(value, (list, tuple, set, dict)) and len(value) > 0:
            return False
        if isinstance(value, str) and value.strip():
            return False
    summary_lower = summary.lower()
    return any(marker in summary_lower for marker in _IDLE_SUMMARY_MARKERS)


def _render_idle_improvement_row(session: object) -> str | None:
    """Render one idle improvement row, returning None when incomplete."""
    command = _extract_idle_validation_command(getattr(session, "provider_metadata", None))
    if not command:
        return None
    command_label = _idle_validation_label(session)
    summary = str(getattr(session, "summary_oneliner", "")).strip()
    created_at = getattr(session, "created_at", None)
    timestamp = (
        created_at.astimezone(UTC).strftime(_TIMESTAMP_FORMAT)
        if isinstance(created_at, datetime)
        else "unknown"
    )
    return f"- {timestamp} | {command_label}=`{command}` | {summary}"


async def _get_recent_idle_improvement_history(
    target_project_id: str | None = None,
) -> str:
    """Show recent clean-idle validation slices so heartbeat can avoid repeat theater."""
    from sqlalchemy import and_, select

    from app.db import async_session
    from app.models import Session

    cutoff = datetime.now(UTC) - timedelta(hours=_IDLE_HISTORY_LOOKBACK_HOURS)
    conditions = [
        Session.agent_slug == _PERSONA_AGENT_SLUG,
        Session.request_source == _HEARTBEAT_REQUEST_SOURCE,
        Session.status == "completed",
        Session.created_at >= cutoff,
    ]
    if target_project_id:
        conditions.append(Session.project_id == target_project_id)

    try:
        async with async_session() as db:
            result = await db.execute(
                select(Session)
                .where(and_(*conditions))
                .order_by(Session.created_at.desc())
                .limit(_IDLE_HISTORY_LIMIT * 3)
            )
            sessions = result.scalars().all()
    except Exception:
        logger.debug("Failed to fetch recent idle improvement history", exc_info=True)
        return ""

    rendered_rows: list[str] = []
    for session in sessions:
        if not _is_recent_idle_slice_session(session):
            continue
        rendered = _render_idle_improvement_row(session)
        if rendered:
            rendered_rows.append(rendered)
        if len(rendered_rows) >= _IDLE_HISTORY_LIMIT:
            break

    if not rendered_rows:
        return ""
    return _render_budgeted_rows_section(
        tag=_IDLE_HISTORY_TAG,
        heading=_IDLE_HISTORY_HEADING,
        rows=rendered_rows,
        token_budget=_IDLE_HISTORY_TOKEN_BUDGET,
    )


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
    "_fetch_recent_failed_tasks",
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
    "_get_recent_heartbeat_digest",
    "_get_recent_idle_improvement_history",
    "_get_workstream_inventory",
    "_query_active_sessions_for_heartbeat",
    "_query_active_specialist_sessions",
    "_query_recent_workstream_sessions",
    "_session_display_health",
    "_session_stale_threshold_minutes",
    "get_project_access_summary",
]
