"""Session CRUD operations - business logic for session lifecycle."""

import base64
import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import ColumnElement, and_, asc, case, desc, func, literal, or_, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Session
from app.services.agent_routing import resolve_agent
from app.services.events import publish_session_start
from app.services.session_live_activity import mark_session_completed

logger = logging.getLogger(__name__)

_SESSION_SORT_FIELDS = frozenset({"status", "project", "agent", "time", "last_active"})
_SESSION_SORT_DIRECTIONS = frozenset({"asc", "desc"})


def _session_activity_timestamp():
    return func.coalesce(Session.last_activity_at, Session.updated_at, Session.created_at)


def _session_live_text_field(field_name: str):
    return Session.provider_metadata["live_activity"][field_name].as_string()


def _session_live_bool_field(field_name: str):
    return Session.provider_metadata["live_activity"][field_name].as_boolean()


def _session_operational_rank():
    live_state = func.lower(
        func.coalesce(
            _session_live_text_field("lifecycle_state"),
            _session_live_text_field("status"),
            _session_live_text_field("phase"),
            "",
        )
    )
    active_status = Session.status == "active"
    stalled_or_reapable = or_(
        _session_live_bool_field("reapable").is_(True),
        _session_live_bool_field("stalled").is_(True),
        live_state.in_(("reapable", "stale", "stalled")),
    )
    return case(
        (active_status, case((stalled_or_reapable, 1), else_=0)),
        (Session.status == "failed", 2),
        else_=3,
    )


def _session_sort_keys(sort_by: str, sort_direction: str) -> list[tuple[Any, bool]]:
    """Return the canonical (expression, descending) sort keys, ending in id."""
    normalized_sort = sort_by.strip().lower()
    normalized_direction = sort_direction.strip().lower()
    if normalized_sort not in _SESSION_SORT_FIELDS:
        raise ValueError(f"Unsupported session sort field: {sort_by}")
    if normalized_direction not in _SESSION_SORT_DIRECTIONS:
        raise ValueError(f"Unsupported session sort direction: {sort_direction}")

    descending = normalized_direction == "desc"
    activity = _session_activity_timestamp()

    if normalized_sort == "status":
        return [
            (_session_operational_rank(), descending),
            (activity, True),
            (Session.created_at, True),
            (Session.id, True),
        ]
    if normalized_sort == "project":
        return [
            (func.lower(Session.project_id), descending),
            (_session_operational_rank(), False),
            (activity, True),
            (Session.created_at, True),
            (Session.id, True),
        ]
    if normalized_sort == "agent":
        return [
            (func.lower(func.coalesce(Session.agent_slug, "")), descending),
            (func.lower(Session.model), descending),
            (_session_operational_rank(), False),
            (activity, True),
            (Session.created_at, True),
            (Session.id, True),
        ]
    if normalized_sort == "last_active":
        from app.services.session_queries import session_last_active

        return [(session_last_active(), descending), (Session.id, descending)]
    return [(activity, descending), (Session.created_at, True), (Session.id, True)]


def _ordered_session_query(query, sort_by: str, sort_direction: str):
    """Apply the canonical sessions table order before pagination (ties on id)."""
    keys = _session_sort_keys(sort_by, sort_direction)
    return query.order_by(*[desc(expr) if is_desc else asc(expr) for expr, is_desc in keys])


def _keyset_predicate(keys: list[tuple[Any, bool]], values: list[Any]) -> ColumnElement[bool]:
    """Rows strictly after ``values`` in the ordering defined by ``keys``."""
    values = [literal(value, type_=expr.type) for (expr, _), value in zip(keys, values, strict=True)]
    directions = {is_desc for _, is_desc in keys}
    if len(directions) == 1:
        position = tuple_(*[expr for expr, _ in keys])
        boundary = tuple_(*values)
        return position < boundary if directions.pop() else position > boundary
    clauses = []
    for index, (expr, is_desc) in enumerate(keys):
        equal_prefix = [keys[j][0] == values[j] for j in range(index)]
        step = expr < values[index] if is_desc else expr > values[index]
        clauses.append(and_(*equal_prefix, step))
    return or_(*clauses)


def _encode_cursor_value(value: Any) -> list[Any]:
    if isinstance(value, datetime):
        return ["dt", value.isoformat()]
    if isinstance(value, bool) or value is None:
        raise ValueError("Unsupported session cursor value")
    if isinstance(value, int):
        return ["i", value]
    return ["s", str(value)]


def _decode_cursor_value(item: Any) -> Any:
    if not isinstance(item, list) or len(item) != 2:
        raise ValueError("Invalid session cursor")
    tag, value = item
    if tag == "dt" and isinstance(value, str):
        return datetime.fromisoformat(value)
    if tag == "i" and isinstance(value, int) and not isinstance(value, bool):
        return value
    if tag == "s" and isinstance(value, str):
        return value
    raise ValueError("Invalid session cursor")


def encode_session_list_cursor(sort_by: str, sort_direction: str, values: list[Any]) -> str:
    """Opaque URL-safe keyset cursor over the sort key values and id."""
    payload = {
        "v": 1,
        "s": sort_by,
        "d": sort_direction,
        "k": [_encode_cursor_value(value) for value in values],
    }
    raw = json.dumps(payload, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_session_list_cursor(cursor: str, sort_by: str, sort_direction: str, key_count: int) -> list[Any]:
    try:
        padding = "=" * (-len(cursor) % 4)
        payload = json.loads(base64.urlsafe_b64decode(cursor + padding).decode())
    except (ValueError, UnicodeDecodeError) as exc:
        raise ValueError("Invalid session cursor") from exc
    if not isinstance(payload, dict) or payload.get("v") != 1:
        raise ValueError("Invalid session cursor")
    if payload.get("s") != sort_by or payload.get("d") != sort_direction:
        raise ValueError("Session cursor does not match the requested sort")
    raw_values = payload.get("k")
    if not isinstance(raw_values, list) or len(raw_values) != key_count:
        raise ValueError("Invalid session cursor")
    return [_decode_cursor_value(item) for item in raw_values]


async def _validate_project_id(project_id: str) -> None:
    """Backward-compatible delegate to the canonical project registry."""
    from app.constants.projects import validate_project_id

    await validate_project_id(project_id)


async def _resolve_provider_and_model(
    db: AsyncSession,
    agent_slug: str | None,
    provider: str,
    model: str,
) -> tuple[str, str]:
    """Resolve provider and model, optionally overriding from agent configuration.

    Args:
        db: Database session
        agent_slug: Optional agent slug to resolve
        provider: Default provider name
        model: Default model identifier

    Returns:
        Tuple of (resolved_provider, resolved_model)
    """
    if agent_slug:
        resolved = await resolve_agent(agent_slug, db)
        return resolved.provider, resolved.model
    return provider, model


async def _build_and_persist_session(
    db: AsyncSession,
    session_id: str,
    project_id: str,
    provider: str,
    model: str,
    session_type: str,
    agent_slug: str | None,
) -> Session:
    """Create, persist, and return a new session record.

    Args:
        db: Database session
        session_id: Session identifier
        project_id: Project identifier
        provider: Provider name
        model: Model identifier
        session_type: Session type
        agent_slug: Optional agent slug

    Returns:
        Persisted session object
    """
    session = Session(
        id=session_id,
        project_id=project_id,
        provider=provider,
        model=model,
        status="active",
        session_type=session_type,
        agent_slug=agent_slug,
    )
    db.add(session)
    await db.commit()
    await db.refresh(session)
    return session


async def create_new_session(
    db: AsyncSession,
    session_id: str | None,
    project_id: str,
    provider: str,
    model: str,
    session_type: str,
    agent_slug: str | None = None,
) -> Session:
    """Create a new session with resolved agent configuration.

    Args:
        db: Database session
        session_id: Optional custom session ID
        project_id: Project identifier
        provider: Provider name
        model: Model identifier
        session_type: Session type
        agent_slug: Optional agent slug to resolve

    Returns:
        Created session object

    Raises:
        ValueError: If project_id is not in VALID_PROJECT_IDS
    """
    await _validate_project_id(project_id)

    final_session_id = session_id or str(uuid.uuid4())
    final_provider, final_model = await _resolve_provider_and_model(
        db, agent_slug, provider, model
    )

    session = await _build_and_persist_session(
        db, final_session_id, project_id, final_provider, final_model, session_type, agent_slug
    )

    await publish_session_start(final_session_id, final_model, project_id)

    return session


async def close_session_if_active(db: AsyncSession, session: Session) -> tuple[str, str]:
    """Close a session if it's active.

    Args:
        db: Database session
        session: Session to close

    Returns:
        Tuple of (status, message)
    """
    if session.status == "completed":
        return "completed", "Session was already completed"

    mark_session_completed(
        session,
        summary="Session closed",
        termination_reason="session_closed_helper",
    )
    await db.commit()

    # Inline summary tags ([[S:outcome:description]]) are the sole summary mechanism.
    # CC sessions: Stop hook → /analyze stores tags.
    # API sessions: citation_tracker.track_inline_summaries() stores tags during streaming.
    # No async summarizer dispatch — removed Feb 2026.

    return "completed", "Session closed successfully"


async def promote_session_branch(
    db: AsyncSession,
    session: Session,
    discard_siblings: bool = False,
) -> tuple[list[str], int]:
    """Promote a session branch and optionally discard siblings.

    Args:
        db: Database session
        session: Session to promote
        discard_siblings: Whether to discard sibling sessions

    Returns:
        Tuple of (discarded_sibling_ids, patches_applied_count)
    """
    from app.services.session_branching import discard_sibling_sessions

    discarded_siblings: list[str] = []
    if discard_siblings and session.parent_session_id:
        discarded_siblings = await discard_sibling_sessions(
            db, session.parent_session_id, session.id
        )

    session.branch_status = "promoted"
    session.manual_outcome = "selected"

    patches_applied = 0
    if session.pending_patches:
        patches_applied = len(session.pending_patches)
        session.pending_patches = None

    await db.commit()

    return discarded_siblings, patches_applied


async def get_or_create_session(
    db: AsyncSession, session_id: str | None
) -> tuple[Session | None, bool]:
    """Get existing session by ID if it exists.

    Args:
        db: Database session
        session_id: Optional session ID to look up

    Returns:
        Tuple of (existing_session, is_existing) - (None, False) if not found
    """
    if not session_id:
        return None, False

    result = await db.execute(select(Session).where(Session.id == session_id))
    existing = result.scalar_one_or_none()
    if existing:
        return existing, True

    return None, False


@dataclass
class SessionListPage:
    sessions: list[Session]
    total: int
    next_cursor: str | None
    accounting: dict[str, dict] = field(default_factory=dict)


async def _fetch_filtered_sessions(
    db: AsyncSession,
    filters: Any,
    page: int,
    page_size: int,
    sort_by: str,
    sort_direction: str,
    cursor: str | None = None,
    accounting_start: datetime | None = None,
    accounting_end: datetime | None = None,
) -> SessionListPage:
    """Count with every filter in SQL, then page by offset or keyset cursor."""
    from app.services.session_queries import session_list_predicates

    predicates = session_list_predicates(filters)
    total_result = await db.execute(select(func.count(Session.id)).where(*predicates))
    total = total_result.scalar() or 0

    if sort_by in {"admin_share", "admin_duration"}:
        from app.services.session_accounting import accounting_sort_key, fetch_session_accounting
        from app.services.session_efficiency import duration_split

        if sort_direction not in _SESSION_SORT_DIRECTIONS:
            raise ValueError("Unsupported session sort direction")
        selected_ids = select(Session.id).where(*predicates)
        accounting = await fetch_session_accounting(db, selected_ids, start=accounting_start, end=accounting_end)
        ids = list((await db.execute(selected_ids)).scalars())
        empty = duration_split({}, calls=0, missing=0, truncated=False)
        def key(sid):
            return accounting_sort_key(sid, accounting.get(sid, empty), sort_by, sort_direction)
        ids.sort(key=key)
        if cursor:
            try:
                boundary = json.loads(base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)))
                if boundary["sort"] != sort_by or boundary["direction"] != sort_direction:
                    raise ValueError("Session cursor does not match the requested sort")
                last = tuple(boundary["key"])
                ids = [sid for sid in ids if key(sid) > last]
            except (ValueError, TypeError, KeyError) as exc:
                raise ValueError("Invalid session accounting cursor") from exc
        else:
            ids = ids[(page - 1) * page_size:]
        next_cursor = None
        if len(ids) > page_size:
            ids = ids[:page_size]
            payload = {"sort": sort_by, "direction": sort_direction, "key": key(ids[-1])}
            next_cursor = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
        sessions = list((await db.execute(select(Session).where(Session.id.in_(ids)))).scalars()) if ids else []
        sessions.sort(key=lambda session: key(session.id))
        return SessionListPage(sessions, int(total), next_cursor, {sid: accounting.get(sid, empty) for sid in ids})

    keys = _session_sort_keys(sort_by, sort_direction)
    key_exprs = [expr for expr, _ in keys]
    query = select(Session, *key_exprs).where(*predicates)
    if cursor:
        values = decode_session_list_cursor(cursor, sort_by, sort_direction, len(keys))
        query = query.where(_keyset_predicate(keys, values))
    else:
        query = query.offset((page - 1) * page_size)
    query = query.order_by(*[desc(expr) if is_desc else asc(expr) for expr, is_desc in keys])
    query = query.limit(page_size + 1)

    result = await db.execute(query)
    rows = list(result.all())
    next_cursor: str | None = None
    if len(rows) > page_size:
        rows = rows[:page_size]
        next_cursor = encode_session_list_cursor(sort_by, sort_direction, list(rows[-1][1:]))
    return SessionListPage(sessions=[row[0] for row in rows], total=int(total), next_cursor=next_cursor)


async def list_sessions_with_stats(
    db: AsyncSession,
    project_id: str | None = None,
    status: str | None = None,
    agent_slug: str | None = None,
    session_type: str | None = None,
    page: int = 1,
    page_size: int = 20,
    parent_session_id: str | None = None,
    external_id: str | None = None,
    sort_by: str = "status",
    sort_direction: str = "asc",
    *,
    filters: Any = None,
    cursor: str | None = None,
    accounting_start: datetime | None = None,
    accounting_end: datetime | None = None,
) -> tuple[Any, ...]:
    """List sessions with pagination, filtering, and batched statistics.

    ``filters`` (a SessionListFilters) supersedes the individual filter
    arguments when given.

    Returns:
        Tuple of (sessions, total_count, message_counts, event_counts, token_stats,
        child_counts, active_child_counts, next_cursor, titles, usage_rollups)
    """
    from app.services.session_queries import (
        SessionListFilters,
        fetch_session_statistics,
        fetch_session_titles,
        fetch_session_usage_rollups,
    )

    if filters is None:
        filters = SessionListFilters(
            project_id=project_id,
            status=status,
            agent_slug=agent_slug,
            session_type=session_type,
            parent_session_id=parent_session_id,
            external_id=external_id,
        )
    listing = await _fetch_filtered_sessions(
        db, filters, page, page_size, sort_by, sort_direction, cursor=cursor,
        accounting_start=accounting_start, accounting_end=accounting_end,
    )

    session_ids = [s.id for s in listing.sessions]
    if accounting_start is not None and sort_by not in {"admin_share", "admin_duration"}:
        from app.services.session_accounting import fetch_session_accounting
        from app.services.session_efficiency import duration_split
        measured = await fetch_session_accounting(db, session_ids, start=accounting_start, end=accounting_end) if session_ids else {}
        listing.accounting = {sid: measured.get(sid, duration_split({}, calls=0, missing=0, truncated=False)) for sid in session_ids}
    msg_counts, event_counts, token_stats, child_counts, active_child_counts = await fetch_session_statistics(db, session_ids)
    titles = await fetch_session_titles(db, session_ids)
    usage_rollups = await fetch_session_usage_rollups(db, session_ids)

    return (
        listing.sessions,
        listing.total,
        msg_counts,
        event_counts,
        token_stats,
        child_counts,
        active_child_counts,
        listing.next_cursor,
        titles,
        usage_rollups,
        listing.accounting,
    )


async def fork_session_at_turn(
    db: AsyncSession,
    parent: Session,
    fork_at_turn: int | None,
) -> tuple[str, int, int]:
    """Fork a session at a specific turn.

    Args:
        db: Database session
        parent: Parent session with events loaded
        fork_at_turn: Optional turn number to fork at

    Returns:
        Tuple of (new_session_id, fork_point_turn, message_count)
    """
    from app.services.session_branching import (
        copy_events_to_forked_session,
        create_forked_session,
        prepare_fork_data,
    )

    sorted_events = sorted(parent.events, key=lambda x: (x.turn, x.sequence))
    events_to_copy, fork_at = prepare_fork_data(sorted_events, fork_at_turn)

    new_session_id = str(uuid.uuid4())
    forked_session = create_forked_session(parent, new_session_id, fork_at)
    db.add(forked_session)
    copy_events_to_forked_session(db, events_to_copy, new_session_id)
    await db.commit()

    return new_session_id, fork_at, len(events_to_copy)
