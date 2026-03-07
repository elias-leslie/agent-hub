"""Shared lane normalization helpers for live ownership/workstream views."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any


@dataclass(frozen=True)
class OwnershipOwner:
    """Normalized live owner row for cross-repo coordination."""

    task_id: str | None
    session_id: str
    agent_slug: str | None
    branch: str | None
    worktree_path: str | None
    is_worktree: bool
    session_status: str
    workstream_status: str | None
    workstream_note: str | None
    ownership_kind: str
    scope_paths: list[str]
    updated_at: datetime | None
    created_at: datetime
    age_minutes: int
    is_stale: bool


@dataclass(frozen=True)
class LaneFingerprint:
    """Identity for a concrete task/worktree lane."""

    task_id: str | None
    branch: str | None
    worktree_path: str | None


_WORKSTREAM_STATUS_RANK = {
    "authoritative": 3,
    "retired": 2,
    "superseded": 1,
}


def infer_task_id(external_id: str | None, branch: str | None) -> str | None:
    """Resolve task id from explicit external id or task branch naming."""
    if external_id and external_id.startswith("task-"):
        return external_id
    if not branch:
        return None
    prefix = branch.split("/", 1)[0]
    return prefix if prefix.startswith("task-") else None


def lane_fingerprint(
    *,
    task_id: str | None,
    branch: str | None,
    worktree_path: str | None,
) -> LaneFingerprint | None:
    """Build a concrete lane identity, or None when no lane evidence exists."""
    if not task_id and not branch and not worktree_path:
        return None
    return LaneFingerprint(
        task_id=task_id,
        branch=branch,
        worktree_path=worktree_path,
    )


def _timestamp_value(value: datetime | None) -> float:
    if value is None:
        return float("-inf")
    value = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    return value.timestamp()


def _owner_rank(owner: OwnershipOwner) -> tuple[int, int, int, float]:
    return (
        0 if owner.is_stale else 1,
        1 if owner.scope_paths else 0,
        _WORKSTREAM_STATUS_RANK.get(owner.workstream_status or "", 0),
        _timestamp_value(owner.updated_at or owner.created_at),
    )


def collapse_ownership_owners(owners: list[OwnershipOwner]) -> list[OwnershipOwner]:
    """Collapse duplicate active sessions that represent the same exact lane."""
    grouped: dict[LaneFingerprint, list[OwnershipOwner]] = {}
    passthrough: list[OwnershipOwner] = []

    for owner in owners:
        fingerprint = lane_fingerprint(
            task_id=owner.task_id,
            branch=owner.branch,
            worktree_path=owner.worktree_path,
        )
        if fingerprint is None:
            passthrough.append(owner)
            continue
        grouped.setdefault(fingerprint, []).append(owner)

    collapsed: list[OwnershipOwner] = []
    for fingerprint, group in grouped.items():
        representative = max(group, key=_owner_rank)
        merged_scope_paths = sorted({path for owner in group for path in owner.scope_paths})
        lane_is_stale = all(owner.is_stale for owner in group)
        freshest_age = min(owner.age_minutes for owner in group)
        latest_updated = max(
            (_timestamp_value(owner.updated_at), owner.updated_at) for owner in group
        )[1]
        collapsed.append(
            OwnershipOwner(
                task_id=fingerprint.task_id,
                session_id=representative.session_id,
                agent_slug=representative.agent_slug,
                branch=fingerprint.branch,
                worktree_path=fingerprint.worktree_path,
                is_worktree=any(owner.is_worktree for owner in group),
                session_status=representative.session_status,
                workstream_status=representative.workstream_status,
                workstream_note=representative.workstream_note,
                ownership_kind=representative.ownership_kind,
                scope_paths=merged_scope_paths,
                updated_at=latest_updated,
                created_at=representative.created_at,
                age_minutes=freshest_age,
                is_stale=lane_is_stale,
            )
        )

    return sorted(
        [*collapsed, *passthrough],
        key=lambda owner: (
            owner.task_id or "",
            owner.branch or "",
            owner.worktree_path or "",
            owner.session_id,
        ),
    )


def collapse_active_workstream_rows(
    rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Collapse duplicate active rows that share the same concrete lane."""
    grouped: dict[LaneFingerprint, list[dict[str, Any]]] = {}
    passthrough: list[dict[str, Any]] = []

    for row in rows:
        if row.get("status") != "active":
            passthrough.append(row)
            continue
        fingerprint = lane_fingerprint(
            task_id=infer_task_id(
                row.get("external_id") if isinstance(row.get("external_id"), str) else None,
                row.get("current_branch") if isinstance(row.get("current_branch"), str) else None,
            ),
            branch=row.get("current_branch") if isinstance(row.get("current_branch"), str) else None,
            worktree_path=row.get("working_dir") if isinstance(row.get("working_dir"), str) else None,
        )
        if fingerprint is None:
            passthrough.append(row)
            continue
        grouped.setdefault(fingerprint, []).append(row)

    collapsed: list[dict[str, Any]] = []
    for fingerprint, group in grouped.items():
        representative = max(
            group,
            key=lambda row: (
                0 if bool(row.get("is_stale")) else 1,
                1 if row.get("scope_paths") else 0,
                _WORKSTREAM_STATUS_RANK.get(str(row.get("workstream_status") or ""), 0),
                _timestamp_value(row.get("updated_at") if isinstance(row.get("updated_at"), datetime) else None),
            ),
        )
        merged = dict(representative)
        merged["external_id"] = fingerprint.task_id or merged.get("external_id")
        merged["current_branch"] = fingerprint.branch
        merged["working_dir"] = fingerprint.worktree_path
        merged["age_minutes"] = min(int(row.get("age_minutes", 0)) for row in group)
        collapsed.append(merged)

    return [*collapsed, *passthrough]


__all__ = [
    "LaneFingerprint",
    "OwnershipOwner",
    "collapse_active_workstream_rows",
    "collapse_ownership_owners",
    "infer_task_id",
    "lane_fingerprint",
]
