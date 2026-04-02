"""Heartbeat task overview resolution helpers.

Pure and async helpers that resolve task overview text and metadata
from structured payloads, raw text, or live API fetches.
"""

from __future__ import annotations

from app.services.task_overview_summary import (
    build_compact_task_overview_from_payload,
    collect_visible_task_ids_from_payload,
    extract_stale_task_candidates_from_payload,
)
from app.workflows._heartbeat_state import (
    _TASK_ID_PATTERN,
    SummitFlowHeartbeatState,
)

# Task overview section definitions: (header_prefix, bucket_key, output_label, always_count_one)
# Projects always renders as count=1 for single-project filters.
_TASK_SECTIONS: tuple[tuple[str, str, str, bool], ...] = (
    ("PROJECTS[",           "projects", "PROJECTS",           True),
    ("ACTIONABLE-READY[",   "ready",    "ACTIONABLE-READY",   False),
    ("ACTIONABLE-BLOCKED[", "blocked",  "ACTIONABLE-BLOCKED", False),
    ("ACTIONABLE-STALE[",   "stale",    "ACTIONABLE-STALE",   False),
)


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
