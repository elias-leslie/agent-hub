"""Workstream session queries and lane classification shared by cleanup tooling.

Workstream lane states are derived in precedence order, highest first:
1. retired - all observed lifecycle markers are retired
2. reconciled - authoritative + superseded evidence exists for the same task session
3. superseded - all observed lifecycle markers are superseded
4. mixed - multiple active lanes/sessions for the same task
5. stale_active - active session exists but exceeds the stale age threshold
6. active - live non-stale session exists
7. completed_ready_for_closure - no active session remains and completed evidence exists
8. orphaned - session facts exist but do not yet justify automation
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.services.ownership_lanes import (
    STALE_WORKSTREAM_IDLE_MINUTES,
    collapse_active_workstream_rows,
    idle_minutes_from_timestamps,
    infer_task_id,
)

WORKSTREAM_LOOKBACK_HOURS = 24
_TASK_EXTERNAL_ID_PATTERN = "task-%"
_WORKSTREAM_QUERY_LIMIT = 50


def classify_workstream_lane(rows: list[dict[str, object]]) -> str:
    """Classify a grouped task session into an actionable lifecycle state."""
    statuses = {str(row["workstream_status"]) for row in rows if row.get("workstream_status")}
    active_rows = [row for row in rows if row.get("status") == "active"]
    completed_rows = [row for row in rows if row.get("status") == "completed"]
    session_ids = {str(row["session_id"]) for row in rows if row.get("session_id")}

    if statuses == {"retired"}:
        return "retired"
    if "authoritative" in statuses and "superseded" in statuses:
        return "reconciled"
    if statuses == {"superseded"}:
        return "superseded"
    if len(active_rows) > 1 and len(session_ids) > 1:
        return "mixed"
    if active_rows:
        freshest_active_idle = min(
            int(row.get("idle_minutes", STALE_WORKSTREAM_IDLE_MINUTES + 1))
            for row in active_rows
        )
        return "stale_active" if freshest_active_idle >= STALE_WORKSTREAM_IDLE_MINUTES else "active"
    if completed_rows:
        return "completed_ready_for_closure"
    return "orphaned"


def group_rows_by_lane(
    rows: list[dict[str, object]],
) -> dict[tuple[str, str], list[dict[str, object]]]:
    """Group workstream rows by (project_id, session_key)."""
    grouped: dict[tuple[str, str], list[dict[str, object]]] = {}
    for row in rows:
        ei = row.get("external_id") if isinstance(row.get("external_id"), str) else None
        br = row.get("current_branch") if isinstance(row.get("current_branch"), str) else None
        tid = infer_task_id(ei, br) or ""
        lane_key = tid or str(row.get("current_branch") or row.get("session_id") or "")
        if lane_key:
            grouped.setdefault((str(row["project_id"]), lane_key), []).append(row)
    return grouped


def infer_lane_task_id(lane_rows: list[dict[str, object]]) -> str | None:
    """Return the first resolvable task_id from a set of session rows."""
    for lr in lane_rows:
        ei = lr.get("external_id") if isinstance(lr.get("external_id"), str) else None
        br = lr.get("current_branch") if isinstance(lr.get("current_branch"), str) else None
        task_id = infer_task_id(ei, br)
        if task_id:
            return task_id
    return None


def map_workstream_row(row: object, *, now: datetime) -> dict[str, object]:
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


async def query_recent_workstream_sessions(
    target_project_id: str | None = None,
    *,
    now: datetime | None = None,
) -> list[dict[str, object]]:
    """Query workstream sessions from DB and collapse to deduplicated active rows."""
    from sqlalchemy import and_, func, or_, select

    from app.db import async_session
    from app.models import Session

    collected_at = now or datetime.now(UTC)
    cutoff = collected_at - timedelta(hours=WORKSTREAM_LOOKBACK_HOURS)
    # Sessions are matched via workstream_status (the lease-era marker) and
    # external_id (the canonical task id when the session is task-scoped).
    lane_or_reconciled_scope = or_(
        Session.workstream_status.isnot(None),
        Session.external_id.like(_TASK_EXTERNAL_ID_PATTERN),
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
                .limit(_WORKSTREAM_QUERY_LIMIT)
            )
        ).all()
    return collapse_active_workstream_rows(
        [map_workstream_row(r, now=collected_at) for r in raw_rows]
    )
