"""Ownership inventory for live project lanes and worktrees."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path, PurePosixPath
from typing import Any

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Session, SessionEvent
from app.services.tools.project_env import detect_main_repo

_LOOKBACK_HOURS = 24
_STALE_ACTIVE_MINUTES = 4 * 60
_GHOST_SESSION_MINUTES = 15
_WRITE_TOOL_NAMES = {"Write", "Edit", "write_file"}
_RETIRED_STATUSES = {"retired", "superseded"}


@dataclass(frozen=True)
class OwnershipOwner:
    """Normalized live owner row for cross-repo coordination."""

    task_id: str | None
    session_id: str
    agent_slug: str | None
    branch: str | None
    worktree_path: str | None
    session_status: str
    workstream_status: str | None
    workstream_note: str | None
    ownership_kind: str
    scope_paths: list[str]
    updated_at: datetime | None
    created_at: datetime
    age_minutes: int
    is_stale: bool


def _infer_task_id(external_id: str | None, branch: str | None) -> str | None:
    """Resolve task id from explicit external id or task branch naming."""
    if external_id and external_id.startswith("task-"):
        return external_id
    if not branch:
        return None
    prefix = branch.split("/", 1)[0]
    return prefix if prefix.startswith("task-") else None


def _parse_timestamp(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _age_minutes(created_at: datetime, updated_at: datetime | None) -> int:
    reference = _parse_timestamp(updated_at) or _parse_timestamp(created_at) or datetime.now(UTC)
    return int((datetime.now(UTC) - reference).total_seconds() / 60)


def _normalize_scope_path(raw_path: Any, worktree_path: str | None) -> str | None:
    """Normalize event file paths to repo/worktree-relative POSIX form."""
    if not isinstance(raw_path, str):
        return None
    path = raw_path.strip()
    if not path:
        return None
    while path.startswith("./"):
        path = path[2:]
    if path.startswith("/"):
        base_candidates: list[Path] = []
        if worktree_path:
            cwd = Path(worktree_path).resolve()
            base_candidates.append(cwd)
            main_repo = detect_main_repo(cwd)
            if main_repo and main_repo != cwd:
                base_candidates.append(main_repo.resolve())
        absolute = Path(path).resolve()
        for base in base_candidates:
            try:
                rel = absolute.relative_to(base)
            except ValueError:
                continue
            return _normalize_scope_path(str(rel), None)
        return None
    if "\\" in path or "//" in path or path.endswith("/"):
        return None
    parts = path.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        return None
    normalized = str(PurePosixPath(path))
    return None if normalized == "." else normalized


def _derive_ownership_kind(
    workstream_status: str | None,
    scope_paths: list[str],
    is_stale: bool,
) -> str:
    """Map session lifecycle to a normalized ownership kind."""
    if workstream_status == "retired":
        return "retired"
    if workstream_status == "superseded":
        return "superseded"
    if is_stale:
        return "stale"
    if scope_paths:
        return "scoped"
    return "unscoped"


async def _fetch_candidate_sessions(
    db: AsyncSession,
    project_id: str,
) -> list[Session]:
    """Return project sessions that might represent live/recent lanes."""
    cutoff = datetime.now(UTC) - timedelta(hours=_LOOKBACK_HOURS)
    ghost_cutoff = datetime.now(UTC) - timedelta(minutes=_GHOST_SESSION_MINUTES)

    event_count = (
        select(SessionEvent.session_id)
        .where(SessionEvent.session_id == Session.id)
        .limit(1)
        .correlate(Session)
        .exists()
    )

    query = (
        select(Session)
        .where(
            and_(
                Session.project_id == project_id,
                Session.created_at >= cutoff,
                Session.agent_slug.isnot(None),
                or_(
                    Session.status == "active",
                    Session.workstream_status.isnot(None),
                ),
                or_(
                    Session.external_id.isnot(None),
                    Session.current_branch.isnot(None),
                ),
                or_(event_count, Session.created_at >= ghost_cutoff),
            )
        )
        .order_by(Session.created_at.desc())
        .limit(100)
    )
    return list((await db.execute(query)).scalars().all())


async def _fetch_scope_events(
    db: AsyncSession,
    session_ids: list[str],
) -> dict[str, list[SessionEvent]]:
    """Return recent write/edit tool_use events keyed by session id."""
    if not session_ids:
        return {}
    rows = (
        await db.execute(
            select(SessionEvent)
            .where(
                and_(
                    SessionEvent.session_id.in_(session_ids),
                    SessionEvent.event_type == "tool_use",
                    SessionEvent.tool_name.in_(_WRITE_TOOL_NAMES),
                )
            )
            .order_by(SessionEvent.created_at.desc())
        )
    ).scalars().all()

    grouped: dict[str, list[SessionEvent]] = {session_id: [] for session_id in session_ids}
    for row in rows:
        grouped.setdefault(row.session_id, []).append(row)
    return grouped


def _extract_scope_paths(events: list[SessionEvent], worktree_path: str | None) -> list[str]:
    """Extract distinct normalized file paths from tool events."""
    paths: list[str] = []
    seen: set[str] = set()
    for event in events:
        tool_input = event.tool_input if isinstance(event.tool_input, dict) else {}
        raw = tool_input.get("file_path") or tool_input.get("path")
        normalized = _normalize_scope_path(raw, worktree_path)
        if normalized and normalized not in seen:
            seen.add(normalized)
            paths.append(normalized)
    return sorted(paths)


async def query_project_ownership(
    db: AsyncSession,
    project_id: str,
) -> list[OwnershipOwner]:
    """Return normalized live ownership rows for a project."""
    sessions = await _fetch_candidate_sessions(db, project_id)
    scope_events = await _fetch_scope_events(db, [session.id for session in sessions])

    owners: list[OwnershipOwner] = []
    for session in sessions:
        metadata = session.provider_metadata if isinstance(session.provider_metadata, dict) else {}
        worktree_path = metadata.get("cwd") if isinstance(metadata.get("cwd"), str) else None
        scope_paths = _extract_scope_paths(scope_events.get(session.id, []), worktree_path)
        age = _age_minutes(session.created_at, session.updated_at)
        is_stale = session.status == "active" and age >= _STALE_ACTIVE_MINUTES
        ownership_kind = _derive_ownership_kind(session.workstream_status, scope_paths, is_stale)
        if session.workstream_status in _RETIRED_STATUSES:
            is_stale = False
        owners.append(
            OwnershipOwner(
                task_id=_infer_task_id(session.external_id, session.current_branch),
                session_id=session.id,
                agent_slug=session.agent_slug,
                branch=session.current_branch,
                worktree_path=worktree_path,
                session_status=session.status,
                workstream_status=session.workstream_status,
                workstream_note=session.workstream_note,
                ownership_kind=ownership_kind,
                scope_paths=scope_paths,
                updated_at=_parse_timestamp(session.updated_at),
                created_at=_parse_timestamp(session.created_at) or datetime.now(UTC),
                age_minutes=age,
                is_stale=is_stale,
            )
        )

    return owners
