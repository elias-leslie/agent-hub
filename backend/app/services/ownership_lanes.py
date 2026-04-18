"""Shared ownership normalization helpers for live ownership/workstream views."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

STALE_WORKSTREAM_IDLE_MINUTES = 10
_TASK_ID_PATH_RE = re.compile(r"(?:^|[\\/])(task-[A-Za-z0-9]+)(?=[^A-Za-z0-9]|$)")


@dataclass(frozen=True)
class OwnershipOwner:
    """Normalized live owner row for cross-repo coordination."""

    task_id: str | None
    session_id: str
    agent_slug: str | None
    branch: str | None
    working_dir: str | None
    session_status: str
    workstream_status: str | None
    workstream_note: str | None
    ownership_kind: str
    scope_paths: list[str]
    declared_scope_paths: list[str] = field(default_factory=list)
    observed_read_paths: list[str] = field(default_factory=list)
    observed_write_paths: list[str] = field(default_factory=list)
    scope_confidence: str | None = None
    updated_at: datetime | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    age_minutes: int = 0
    is_stale: bool = False


@dataclass(frozen=True)
class LaneFingerprint:
    """Identity for a concrete task checkpoint/session."""

    task_id: str | None
    branch: str | None
    working_dir: str | None


_WORKSTREAM_STATUS_RANK = {
    "authoritative": 3,
    "retired": 2,
    "superseded": 1,
}


def _task_id_from_path(path: str | None) -> str | None:
    if not path:
        return None
    match = _TASK_ID_PATH_RE.search(path)
    if not match:
        return None
    return match.group(1)


def infer_task_id(external_id: str | None, branch: str | None, *paths: str | None) -> str | None:
    """Resolve task id from explicit external id or task branch naming."""
    if external_id and external_id.startswith("task-"):
        return external_id
    if not branch:
        prefix = None
    else:
        prefix = branch.split("/", 1)[0]
        if prefix.startswith("task-"):
            return prefix
    for path in paths:
        task_id = _task_id_from_path(path)
        if task_id:
            return task_id
    return None


def lane_fingerprint(
    *,
    task_id: str | None,
    branch: str | None,
    working_dir: str | None,
) -> LaneFingerprint | None:
    """Build a concrete task-session identity, or None when no session evidence exists."""
    if not task_id and not branch and not working_dir:
        return None
    return LaneFingerprint(
        task_id=task_id,
        branch=branch,
        working_dir=working_dir,
    )


def _timestamp_value(value: datetime | None) -> float:
    if value is None:
        return float("-inf")
    value = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    return value.timestamp()


def idle_minutes_from_timestamps(
    *,
    created_at: datetime,
    updated_at: datetime | None = None,
    workstream_updated_at: datetime | None = None,
    now: datetime | None = None,
) -> int:
    """Return idle minutes from the freshest known task-session activity timestamp."""
    latest = workstream_updated_at or updated_at or created_at
    baseline = now or datetime.now(UTC)
    latest = latest.replace(tzinfo=UTC) if latest.tzinfo is None else latest.astimezone(UTC)
    baseline = (
        baseline.replace(tzinfo=UTC)
        if baseline.tzinfo is None
        else baseline.astimezone(UTC)
    )
    return int((baseline - latest).total_seconds() / 60)


def _owner_rank(owner: OwnershipOwner) -> tuple[int, int, int, float]:
    return (
        0 if owner.is_stale else 1,
        1 if owner.scope_paths else 0,
        _WORKSTREAM_STATUS_RANK.get(owner.workstream_status or "", 0),
        _timestamp_value(owner.updated_at or owner.created_at),
    )


def prioritize_scope_paths(*groups: list[str] | None) -> list[str]:
    """Merge scope paths while preserving write/declared priority over reads."""
    ordered: list[str] = []
    for group in groups:
        for path in group or []:
            if isinstance(path, str) and path and path not in ordered:
                ordered.append(path)
    return ordered


def collapse_ownership_owners(owners: list[OwnershipOwner]) -> list[OwnershipOwner]:
    """Collapse duplicate active sessions that represent the same exact lane."""
    grouped: dict[LaneFingerprint, list[OwnershipOwner]] = {}
    passthrough: list[OwnershipOwner] = []

    for owner in owners:
        fingerprint = lane_fingerprint(
            task_id=owner.task_id,
            branch=owner.branch,
            working_dir=owner.working_dir,
        )
        if fingerprint is None:
            passthrough.append(owner)
            continue
        grouped.setdefault(fingerprint, []).append(owner)

    collapsed: list[OwnershipOwner] = []
    for fingerprint, group in grouped.items():
        representative = max(group, key=_owner_rank)
        legacy_scope_paths = sorted({path for owner in group for path in owner.scope_paths})
        merged_declared_paths = sorted({path for owner in group for path in owner.declared_scope_paths})
        merged_read_paths = sorted({path for owner in group for path in owner.observed_read_paths})
        merged_write_paths = sorted({path for owner in group for path in owner.observed_write_paths})
        merged_scope_paths = prioritize_scope_paths(
            merged_declared_paths,
            merged_write_paths,
            merged_read_paths,
            legacy_scope_paths,
        )
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
                working_dir=fingerprint.working_dir,
                session_status=representative.session_status,
                workstream_status=representative.workstream_status,
                workstream_note=representative.workstream_note,
                ownership_kind=representative.ownership_kind,
                scope_paths=merged_scope_paths,
                declared_scope_paths=merged_declared_paths,
                observed_read_paths=merged_read_paths,
                observed_write_paths=merged_write_paths,
                scope_confidence=representative.scope_confidence,
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
            owner.working_dir or "",
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
                row.get("working_dir") if isinstance(row.get("working_dir"), str) else None,
            ),
            branch=row.get("current_branch") if isinstance(row.get("current_branch"), str) else None,
            working_dir=row.get("working_dir") if isinstance(row.get("working_dir"), str) else None,
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
        merged["working_dir"] = fingerprint.working_dir
        merged["age_minutes"] = min(int(row.get("age_minutes", 0)) for row in group)
        collapsed.append(merged)

    return [*collapsed, *passthrough]


__all__ = [
    "STALE_WORKSTREAM_IDLE_MINUTES",
    "LaneFingerprint",
    "OwnershipOwner",
    "collapse_active_workstream_rows",
    "collapse_ownership_owners",
    "idle_minutes_from_timestamps",
    "infer_task_id",
    "lane_fingerprint",
    "prioritize_scope_paths",
]
