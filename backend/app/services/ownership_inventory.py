"""Ownership inventory for live project lanes and worktrees."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Session, SessionEvent
from app.services.ownership_lanes import (
    OwnershipOwner,
    collapse_ownership_owners,
    infer_task_id,
)
from app.services.persona_identity import PERSONA_SLUG
from app.services.session_live_activity import is_session_actionably_active
from app.services.session_scope import merge_scope_paths, normalize_scope_paths
from app.services.tools.project_env import is_worktree_path

_LOOKBACK_HOURS = 24
# Align live-lane stale classification with completion-session cleanup so downstream
# coordinators can reconcile abandoned lanes shortly after Agent Hub would auto-complete them.
_STALE_ACTIVE_MINUTES = 30
_GHOST_SESSION_MINUTES = 15
_ACTIVE_SPECIALIST_LOOKBACK_HOURS = 6
_WRITE_TOOL_NAMES = {"Write", "Edit", "write_file"}
_READ_TOOL_NAMES = {"Read", "read_file"}


@dataclass(frozen=True)
class ActiveSpecialistSession:
    """Normalized active non-owner specialist session for live coordination."""

    session_id: str
    agent_slug: str | None
    project_id: str
    parent_session_id: str | None
    request_source: str | None
    created_at: datetime
    age_minutes: int


def _parse_timestamp(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _age_minutes(created_at: datetime, updated_at: datetime | None) -> int:
    reference = _parse_timestamp(updated_at) or _parse_timestamp(created_at) or datetime.now(UTC)
    return int((datetime.now(UTC) - reference).total_seconds() / 60)


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


_is_worktree = is_worktree_path


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
                Session.status == "active",
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
                    SessionEvent.tool_name.in_(_WRITE_TOOL_NAMES | _READ_TOOL_NAMES),
                )
            )
            .order_by(SessionEvent.created_at.desc())
        )
    ).scalars().all()

    grouped: dict[str, list[SessionEvent]] = {session_id: [] for session_id in session_ids}
    for row in rows:
        grouped.setdefault(row.session_id, []).append(row)
    return grouped


async def _fetch_active_specialists(
    db: AsyncSession,
    project_id: str,
) -> list[ActiveSpecialistSession]:
    """Return active sessions without owner-lane identity for a project."""
    cutoff = datetime.now(UTC) - timedelta(hours=_ACTIVE_SPECIALIST_LOOKBACK_HOURS)
    rows = (
        await db.execute(
            select(Session)
            .where(
                and_(
                    Session.project_id == project_id,
                    Session.status == "active",
                    Session.agent_slug.isnot(None),
                    Session.agent_slug != PERSONA_SLUG,
                    Session.created_at >= cutoff,
                    Session.external_id.is_(None),
                    Session.current_branch.is_(None),
                )
            )
            .order_by(Session.created_at.desc())
            .limit(50)
        )
    ).scalars().all()

    specialists: list[ActiveSpecialistSession] = []
    for session in rows:
        if session.agent_slug == PERSONA_SLUG:
            continue
        if not is_session_actionably_active(session, has_specialist_lane=True):
            continue
        specialists.append(
            ActiveSpecialistSession(
                session_id=session.id,
                agent_slug=session.agent_slug,
                project_id=session.project_id,
                parent_session_id=session.parent_session_id,
                request_source=session.request_source,
                created_at=_parse_timestamp(session.created_at) or datetime.now(UTC),
                age_minutes=_age_minutes(session.created_at, session.updated_at),
            )
        )
    return specialists


def _extract_scope_paths(
    events: list[SessionEvent],
    worktree_path: str | None,
    tool_names: set[str],
) -> list[str]:
    """Extract distinct normalized file paths from matching tool events."""
    paths: list[str] = []
    seen: set[str] = set()
    for event in events:
        if event.tool_name not in tool_names:
            continue
        tool_input = event.tool_input if isinstance(event.tool_input, dict) else {}
        raw = tool_input.get("file_path") or tool_input.get("path")
        normalized = normalize_scope_paths([raw], worktree_path)
        path = normalized[0] if normalized else None
        if path and path not in seen:
            seen.add(path)
            paths.append(path)
    return sorted(paths)


def _derive_scope_confidence(
    stored_confidence: str | None,
    declared_scope_paths: list[str],
    observed_write_paths: list[str],
    observed_read_paths: list[str],
) -> str:
    if stored_confidence in {"declared", "observed_write", "observed_read", "unknown"}:
        return stored_confidence
    if declared_scope_paths:
        return "declared"
    if observed_write_paths:
        return "observed_write"
    if observed_read_paths:
        return "observed_read"
    return "unknown"


def _should_skip_owner_session(
    session: Session,
    worktree_path: str | None,
    scope_paths: list[str],
) -> bool:
    """Return True when a session is control-plane observer work, not a live owner lane."""
    if session.agent_slug != PERSONA_SLUG:
        return False
    if session.request_source != "heartbeat":
        return False
    if isinstance(session.current_branch, str) and session.current_branch:
        return False
    if _is_worktree(worktree_path):
        return False
    return not scope_paths


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
        worktree_path = None
        for key in ("worktree_path", "cwd"):
            value = metadata.get(key)
            if isinstance(value, str) and value:
                worktree_path = value
                break
        write_event_paths = _extract_scope_paths(
            scope_events.get(session.id, []),
            worktree_path,
            _WRITE_TOOL_NAMES,
        )
        read_event_paths = _extract_scope_paths(
            scope_events.get(session.id, []),
            worktree_path,
            _READ_TOOL_NAMES,
        )
        declared_scope_paths = normalize_scope_paths(
            getattr(session, "declared_scope_paths", None),
            worktree_path,
        )
        observed_write_paths = merge_scope_paths(
            normalize_scope_paths(getattr(session, "observed_write_paths", None), worktree_path),
            write_event_paths,
        )
        observed_read_paths = merge_scope_paths(
            normalize_scope_paths(getattr(session, "observed_read_paths", None), worktree_path),
            read_event_paths,
        )
        scope_paths = merge_scope_paths(
            declared_scope_paths,
            observed_write_paths,
            observed_read_paths,
        )
        if _should_skip_owner_session(session, worktree_path, scope_paths):
            continue
        age = _age_minutes(session.created_at, session.updated_at)
        is_stale = session.status == "active" and age >= _STALE_ACTIVE_MINUTES
        ownership_kind = _derive_ownership_kind(session.workstream_status, scope_paths, is_stale)
        owners.append(
            OwnershipOwner(
                task_id=infer_task_id(session.external_id, session.current_branch),
                session_id=session.id,
                agent_slug=session.agent_slug,
                branch=session.current_branch,
                worktree_path=worktree_path,
                is_worktree=_is_worktree(worktree_path),
                session_status=session.status,
                workstream_status=session.workstream_status,
                workstream_note=session.workstream_note,
                ownership_kind=ownership_kind,
                scope_paths=scope_paths,
                declared_scope_paths=declared_scope_paths,
                observed_read_paths=observed_read_paths,
                observed_write_paths=observed_write_paths,
                scope_confidence=_derive_scope_confidence(
                    getattr(session, "scope_confidence", None),
                    declared_scope_paths,
                    observed_write_paths,
                    observed_read_paths,
                ),
                updated_at=_parse_timestamp(session.updated_at),
                created_at=_parse_timestamp(session.created_at) or datetime.now(UTC),
                age_minutes=age,
                is_stale=is_stale,
            )
        )

    return collapse_ownership_owners(owners)


async def query_project_active_specialists(
    db: AsyncSession,
    project_id: str,
) -> list[ActiveSpecialistSession]:
    """Return normalized active specialist sessions for a project."""
    return await _fetch_active_specialists(db, project_id)
