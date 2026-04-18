"""Ownership inventory for live project workstreams."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Session, SessionEvent
from app.services._session_metadata_helpers import metadata_paths
from app.services.ownership_lanes import (
    OwnershipOwner,
    collapse_ownership_owners,
    infer_task_id,
    prioritize_scope_paths,
)
from app.services.persona_identity import PERSONA_SLUG
from app.services.session_live_activity import is_session_actionably_active
from app.services.session_scope import (
    extract_tool_scope_paths,
    merge_scope_paths,
    normalize_scope_paths,
)

_LOOKBACK_HOURS = 24
_STALE_ACTIVE_MINUTES = 30
_GHOST_SESSION_MINUTES = 15
_ACTIVE_SPECIALIST_LOOKBACK_HOURS = 6


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


def _derive_ownership_kind(workstream_status: str | None, scope_paths: list[str], is_stale: bool) -> str:
    if workstream_status == "retired":
        return "retired"
    if workstream_status == "superseded":
        return "superseded"
    if is_stale:
        return "stale"
    return "scoped" if scope_paths else "unscoped"


def _derive_scope_confidence(
    stored_confidence: str | None,
    declared_scope_paths: list[str],
    observed_write_paths: list[str],
    observed_read_paths: list[str],
) -> str:
    if stored_confidence in {"declared", "observed_write", "observed_read"}:
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
    *,
    task_id: str | None,
    has_working_dir: bool,
    declared_scope_paths: list[str],
    observed_write_paths: list[str],
    observed_read_paths: list[str],
) -> bool:
    if session.agent_slug != PERSONA_SLUG:
        return (
            not task_id
            and not has_working_dir
            and bool(session.current_branch)
            and not (declared_scope_paths or observed_write_paths or observed_read_paths)
            and not is_session_actionably_active(session, has_owner_lane=True)
        )
    if session.request_source != "heartbeat":
        return False
    return not (declared_scope_paths or observed_write_paths or observed_read_paths)


def _extract_scope_paths(events: list[SessionEvent], working_dir: str | None) -> tuple[list[str], list[str]]:
    observed_reads: list[str] = []
    observed_writes: list[str] = []
    for event in events:
        tool_reads, tool_writes = extract_tool_scope_paths(
            event.tool_name,
            event.tool_input if isinstance(event.tool_input, dict) else None,
            base_path=working_dir,
        )
        observed_reads = merge_scope_paths(observed_reads, tool_reads)
        observed_writes = merge_scope_paths(observed_writes, tool_writes)
    return observed_writes, observed_reads


async def _fetch_candidate_sessions(db: AsyncSession, project_id: str) -> list[Session]:
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
                Session.status == "active",
                or_(
                    Session.agent_slug.isnot(None),
                    Session.session_type.in_(("agent", "claude_code")),
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


async def _fetch_scope_events(db: AsyncSession, session_ids: list[str]) -> dict[str, list[SessionEvent]]:
    if not session_ids:
        return {}
    rows = (
        await db.execute(
            select(SessionEvent)
            .where(
                and_(
                    SessionEvent.session_id.in_(session_ids),
                    SessionEvent.event_type == "tool_use",
                )
            )
            .order_by(SessionEvent.created_at.desc())
        )
    ).scalars().all()
    grouped: dict[str, list[SessionEvent]] = {sid: [] for sid in session_ids}
    for row in rows:
        grouped.setdefault(row.session_id, []).append(row)
    return grouped


async def _fetch_active_specialists(db: AsyncSession, project_id: str) -> list[ActiveSpecialistSession]:
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


def _working_dir_from_metadata(metadata: dict) -> str | None:
    paths = metadata_paths(metadata)
    return paths[0] if paths else None


def _build_scope_paths(session: Session, events: list[SessionEvent], working_dir: str | None) -> tuple[
    list[str], list[str], list[str], list[str]
]:
    write_event_paths, read_event_paths = _extract_scope_paths(events, working_dir)
    declared = normalize_scope_paths(getattr(session, "declared_scope_paths", None), working_dir)
    observed_write = merge_scope_paths(
        normalize_scope_paths(getattr(session, "observed_write_paths", None), working_dir),
        write_event_paths,
    )
    observed_read = merge_scope_paths(
        normalize_scope_paths(getattr(session, "observed_read_paths", None), working_dir),
        read_event_paths,
    )
    scope = prioritize_scope_paths(declared, observed_write, observed_read)
    return declared, observed_write, observed_read, scope


def _build_owner(
    session: Session,
    events: list[SessionEvent],
    working_dir: str | None,
    lane_paths: list[str],
) -> OwnershipOwner | None:
    """Build an OwnershipOwner for a session, or return None if it should be skipped."""
    has_working_dir = isinstance(working_dir, str) and bool(working_dir)
    declared, observed_write, observed_read, scope = _build_scope_paths(session, events, working_dir)
    task_id = infer_task_id(session.external_id, session.current_branch, *lane_paths)
    if not (task_id or session.current_branch or has_working_dir):
        return None
    if _should_skip_owner_session(
        session,
        task_id=task_id,
        has_working_dir=has_working_dir,
        declared_scope_paths=declared,
        observed_write_paths=observed_write,
        observed_read_paths=observed_read,
    ):
        return None
    age = _age_minutes(session.created_at, session.updated_at)
    is_stale = session.status == "active" and age >= _STALE_ACTIVE_MINUTES
    return OwnershipOwner(
        task_id=task_id,
        session_id=session.id,
        agent_slug=session.agent_slug,
        branch=session.current_branch,
        working_dir=working_dir,
        session_status=session.status,
        workstream_status=session.workstream_status,
        workstream_note=session.workstream_note,
        ownership_kind=_derive_ownership_kind(session.workstream_status, scope, is_stale),
        scope_paths=scope,
        declared_scope_paths=declared,
        observed_read_paths=observed_read,
        observed_write_paths=observed_write,
        scope_confidence=_derive_scope_confidence(
            getattr(session, "scope_confidence", None),
            declared,
            observed_write,
            observed_read,
        ),
        updated_at=_parse_timestamp(session.updated_at),
        created_at=_parse_timestamp(session.created_at) or datetime.now(UTC),
        age_minutes=age,
        is_stale=is_stale,
    )


async def query_project_ownership(db: AsyncSession, project_id: str) -> list[OwnershipOwner]:
    """Return normalized live ownership rows for a project."""
    sessions = await _fetch_candidate_sessions(db, project_id)
    scope_events = await _fetch_scope_events(db, [s.id for s in sessions])
    owners: list[OwnershipOwner] = []
    for session in sessions:
        metadata = session.provider_metadata if isinstance(session.provider_metadata, dict) else {}
        owner = _build_owner(
            session,
            scope_events.get(session.id, []),
            _working_dir_from_metadata(metadata),
            metadata_paths(metadata),
        )
        if owner is not None:
            owners.append(owner)
    return collapse_ownership_owners(owners)


async def query_project_active_specialists(db: AsyncSession, project_id: str) -> list[ActiveSpecialistSession]:
    """Return normalized active specialist sessions for a project."""
    return await _fetch_active_specialists(db, project_id)
