"""Workstream lane classification and pure formatting helpers for heartbeat prompts.

All IO-bound functions (_query_recent_workstream_sessions, _get_workstream_inventory)
live in _heartbeat_data to keep test patch paths valid. This module provides
the pure classification and formatting helpers.

Contract: workstream inventory states are derived in precedence order.
Highest precedence first:
1. retired - all observed lifecycle markers are retired
2. reconciled - authoritative + superseded evidence exists for the same lane
3. superseded - all observed lifecycle markers are superseded
4. mixed - multiple active branches for the same task/lane
5. stale_active - active lane exists but exceeds the stale age threshold
6. active - live non-stale lane exists
7. completed_ready_for_closure - no active lane remains and completed evidence exists
8. orphaned - lane facts exist but do not yet justify automation

Automation boundary:
- completed_ready_for_closure: safe to reconcile/close
- stale_running_task (from ready-all): safe to reconcile stale task state
- stale_active: advisory only until explicitly verified/reconciled
- mixed / orphaned / reconciled / retired / superseded: informational only
"""

from __future__ import annotations

from datetime import datetime

from app.services.ownership_lanes import idle_minutes_from_timestamps, infer_task_id
from app.workflows._heartbeat_state import _STALE_ACTIVE_MINUTES


def _build_verify_then_close_action(task_id: str) -> str:
    """Return shell-first closeout guidance for a completed lane."""
    return (
        f'bash: st context {task_id} then st done {task_id} --admin --message '
        '"Completed work verified; task closed."'
    )


def _build_verify_then_inspect_action(task_id: str, *, reason: str) -> str:
    """Return shell-first evidence gathering guidance for a task lane."""
    return (
        f"bash: st context {task_id} then st session-events -T {task_id} --page-size 100; "
        f"{reason}"
    )


def _classify_workstream_lane(rows: list[dict[str, object]]) -> str:
    """Classify a grouped task/worktree lane into an actionable lifecycle state."""
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
        return "stale_active" if freshest_active_idle >= _STALE_ACTIVE_MINUTES else "active"
    if completed_rows:
        return "completed_ready_for_closure"
    return "orphaned"


def _build_stale_active_action(
    *,
    project_id: str,
    task_id: str | None,
    provider: str | None,
) -> str:
    """Build next-action string for a stale_active lane."""
    del project_id, provider
    if not task_id:
        return "inspect active session evidence; retire stale lane only after verification"
    return _build_verify_then_inspect_action(
        task_id,
        reason="retire stale lane only after verification",
    )


def _build_workstream_next_action(
    *,
    state: str,
    project_id: str,
    task_id: str | None,
    provider: str | None = None,
) -> str:
    """Return a concrete next action for a classified workstream lane."""
    if state == "completed_ready_for_closure" and task_id:
        del project_id, provider
        return _build_verify_then_close_action(task_id)
    if state == "completed_ready_for_closure" and not task_id:
        return "completed_no_task_id"
    if state == "stale_active":
        return _build_stale_active_action(project_id=project_id, task_id=task_id, provider=provider)
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


def _parse_stale_running_tasks(task_overview: str) -> list[dict[str, str]]:
    """Parse stale-running tasks from raw ready-all or compact ACTIONABLE-STALE output."""
    from app.workflows._heartbeat_state import _COMPACT_STALE_LINE, _STALE_READY_ALL_LINE

    stale_tasks: list[dict[str, str]] = []
    cur_project: str | None = None
    in_compact_stale_section = False
    for raw_line in task_overview.splitlines():
        line = raw_line.rstrip()
        if not line:
            continue
        if line.startswith("ACTIONABLE-STALE["):
            in_compact_stale_section = True
            continue
        if (
            line.startswith("ACTIONABLE-")
            or line.startswith("PROJECTS[")
            or line.startswith("READY-ALL[")
        ):
            in_compact_stale_section = False
        if not line.startswith(" ") and "(" in line and line.endswith(")"):
            cur_project = line.split(" ", 1)[0]
            continue
        m = _STALE_READY_ALL_LINE.match(line)
        if m and cur_project:
            stale_tasks.append({"project_id": cur_project, "task_id": m.group(1)})
            continue
        if in_compact_stale_section:
            compact_match = _COMPACT_STALE_LINE.match(line)
            if compact_match:
                stale_tasks.append({
                    "project_id": compact_match.group("project"),
                    "task_id": compact_match.group("task_id"),
                })
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
    *,
    queue_truth_available: bool,
) -> bool:
    """Return True if a lane should be excluded from the workstream inventory."""
    if lane_state == "retired" and task_id and task_id in visible_task_ids:
        return True
    if lane_state == "completed_ready_for_closure" and task_id and queue_truth_available:
        return task_id not in visible_task_ids
    return lane_state == "completed_ready_for_closure" and not task_id


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
    *,
    queue_truth_available: bool,
    provider: str | None,
) -> list[str]:
    """Build per-lane inventory lines for the workstream section."""
    lines = ["Recent workstreams:"]
    for (project_id, lane_key), lane_rows in sorted(grouped.items()):
        task_id = _infer_lane_task_id(lane_rows)
        lane_state = _classify_workstream_lane(lane_rows)
        if task_id and (project_id, task_id) in stale_keys:
            next_a = _build_verify_then_inspect_action(
                task_id,
                reason="reconcile stale task state only after verification",
            )
            lines.append(
                f"- {project_id} | {task_id} | state=stale_running_task | active=0 | next={next_a}"
            )
            stale_keys.discard((project_id, task_id))
            continue
        if _should_skip_lane(
            lane_state,
            task_id,
            lane_rows,
            visible_task_ids,
            queue_truth_available=queue_truth_available,
        ):
            continue
        lines.append(_build_lane_line(project_id, lane_key, task_id, lane_state, lane_rows, provider))
    for project_id, task_id in sorted(stale_keys):
        if (project_id, task_id) not in grouped:
            next_a = _build_verify_then_inspect_action(
                task_id,
                reason="reconcile stale task state only after verification",
            )
            lines.append(
                f"- {project_id} | {task_id} | state=stale_running_task | active=0 | next={next_a}"
            )
    return lines
