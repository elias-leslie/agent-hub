"""Session query filters and statistics."""

import base64
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    ColumnElement,
    Select,
    String,
    and_,
    bindparam,
    case,
    false,
    func,
    literal_column,
    or_,
    select,
    text,
    tuple_,
)
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.constants.models import UNKNOWN_MODEL
from app.models import Session, SessionEvent, SessionEventType
from app.services.session_live_activity import is_session_actionably_active

_EMPTY_EVENT_SNAPSHOT = "empty"
SESSION_TITLE_MAX_CHARS = 160
# Bound the transferred prefix; whitespace collapsing happens in Python.
_TITLE_SOURCE_PREFIX_CHARS = 4000
_EVENT_ORDERS = frozenset({"asc", "desc"})

# Coarse UI kinds over the stored session_type.
SESSION_KIND_TYPES: dict[str, tuple[str, ...]] = {
    "coding": ("agent", "claude_code"),
    "chat": ("chat",),
    "completion": ("completion",),
    "image": ("image_generation",),
}
SESSION_LIST_STATUSES = frozenset({"active", "completed", "failed", "running", "stale", "reapable"})


def encode_session_event_snapshot(created_at: datetime, event_id: str) -> str:
    """Encode the inclusive insert boundary for a stable event-page snapshot."""
    value = f"{created_at.isoformat()}\n{event_id}".encode()
    return base64.urlsafe_b64encode(value).decode().rstrip("=")


def _decode_session_event_snapshot(snapshot: str) -> tuple[datetime, str] | None:
    if snapshot == _EMPTY_EVENT_SNAPSHOT:
        return None
    try:
        padding = "=" * (-len(snapshot) % 4)
        decoded = base64.urlsafe_b64decode(snapshot + padding).decode()
        timestamp_text, event_id = decoded.split("\n", 1)
        created_at = datetime.fromisoformat(timestamp_text)
    except (ValueError, UnicodeDecodeError) as exc:
        raise ValueError("Invalid session event snapshot") from exc
    if created_at.tzinfo is None or not event_id:
        raise ValueError("Invalid session event snapshot")
    return created_at, event_id


def apply_session_filters(
    query: Select[tuple[Session]],
    count_query: Select[tuple[int]],
    project_id: str | None = None,
    status: str | None = None,
    agent_slug: str | None = None,
    session_type: str | None = None,
    parent_session_id: str | None = None,
    external_id: str | None = None,
) -> tuple[Select[tuple[Session]], Select[tuple[int]]]:
    """Apply filters to session queries.

    Args:
        query: The main select query
        count_query: The count query
        project_id: Filter by project
        status: Filter by status
        agent_slug: Filter by agent slug
        session_type: Filter by session type

    Returns:
        Tuple of (filtered_query, filtered_count_query)
    """
    if project_id:
        query = query.where(Session.project_id == project_id)
        count_query = count_query.where(Session.project_id == project_id)
    if status:
        query = query.where(Session.status == status)
        count_query = count_query.where(Session.status == status)
    if agent_slug:
        query = query.where(Session.agent_slug == agent_slug)
        count_query = count_query.where(Session.agent_slug == agent_slug)
    if session_type:
        query = query.where(Session.session_type == session_type)
        count_query = count_query.where(Session.session_type == session_type)
    if parent_session_id:
        query = query.where(Session.parent_session_id == parent_session_id)
        count_query = count_query.where(Session.parent_session_id == parent_session_id)
    if external_id:
        query = query.where(Session.external_id == external_id)
        count_query = count_query.where(Session.external_id == external_id)

    return query, count_query


def _count_map(rows: list[tuple[object, ...]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        if len(row) < 2:
            continue
        session_id = str(row[0])
        count = int(row[-1])
        counts[session_id] = count
    return counts


async def fetch_session_statistics(
    db: AsyncSession, session_ids: list[str]
) -> tuple[dict[str, int], dict[str, int], dict[str, dict[str, int]], dict[str, int], dict[str, int]]:
    """Fetch message counts, event counts, token statistics, and child-lane counts for sessions."""
    message_counts: dict[str, int] = {}
    event_counts: dict[str, int] = {}
    token_stats: dict[str, dict[str, int]] = {}
    child_counts: dict[str, int] = {}
    active_child_counts: dict[str, int] = {}

    if not session_ids:
        return message_counts, event_counts, token_stats, child_counts, active_child_counts

    message_counts_result = await db.execute(
        select(SessionEvent.session_id, func.count(SessionEvent.id))
        .where(
            SessionEvent.session_id.in_(session_ids),
            SessionEvent.event_type.in_(
                [
                    SessionEventType.USER_MESSAGE,
                    SessionEventType.ASSISTANT_MESSAGE,
                ]
            ),
        )
        .group_by(SessionEvent.session_id)
    )
    message_counts = _count_map(message_counts_result.all())

    event_counts_result = await db.execute(
        select(SessionEvent.session_id, func.count(SessionEvent.id))
        .where(SessionEvent.session_id.in_(session_ids))
        .group_by(SessionEvent.session_id)
    )
    event_counts = _count_map(event_counts_result.all())

    token_result = await db.execute(
        select(
            SessionEvent.session_id,
            SessionEvent.role,
            func.coalesce(func.sum(SessionEvent.tokens), 0),
        )
        .where(
            SessionEvent.session_id.in_(session_ids),
            SessionEvent.event_type.in_(
                [
                    SessionEventType.USER_MESSAGE,
                    SessionEventType.ASSISTANT_MESSAGE,
                ]
            ),
        )
        .group_by(SessionEvent.session_id, SessionEvent.role)
    )
    for session_id, role, tokens in token_result.all():
        if session_id not in token_stats:
            token_stats[session_id] = {"input": 0, "output": 0}
        if role == "user":
            token_stats[session_id]["input"] = tokens
        elif role == "assistant":
            token_stats[session_id]["output"] = tokens

    child_result = await db.execute(
        select(Session).where(Session.parent_session_id.in_(session_ids))
    )
    for child_session in child_result.scalars().all():
        parent_id = str(child_session.parent_session_id or "").strip()
        if not parent_id:
            continue
        child_counts[parent_id] = child_counts.get(parent_id, 0) + 1
        if is_session_actionably_active(child_session):
            active_child_counts[parent_id] = active_child_counts.get(parent_id, 0) + 1

    return message_counts, event_counts, token_stats, child_counts, active_child_counts


async def get_session_or_404(db: AsyncSession, session_id: str) -> Session:
    """Get a session by ID or raise 404.

    Args:
        db: Database session
        session_id: Session ID to fetch

    Returns:
        Session object

    Raises:
        ValueError: If session not found (caller should convert to HTTPException)
    """
    result = await db.execute(select(Session).where(Session.id == session_id))
    session = result.scalar_one_or_none()
    if not session:
        raise ValueError("Session not found")
    return session


async def get_session_with_events(db: AsyncSession, session_id: str) -> Session:
    """Get a session with all events loaded.

    Args:
        db: Database session
        session_id: Session ID to fetch

    Returns:
        Session object with events loaded

    Raises:
        ValueError: If session not found (caller should convert to HTTPException)
    """
    result = await db.execute(
        select(Session).options(selectinload(Session.events)).where(Session.id == session_id)
    )
    session = result.scalar_one_or_none()
    if not session:
        raise ValueError("Session not found")
    return session


def _like_pattern(value: str, *, prefix_only: bool = False) -> str:
    escaped = value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"{escaped}%" if prefix_only else f"%{escaped}%"


# ---------------------------------------------------------------------------
# Session list filters (shared by list, facets and keyset paging)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SessionListFilters:
    """Server-side session list filters; every field maps to a SQL predicate."""

    project_id: str | None = None
    status: str | None = None
    agent_slug: str | None = None
    session_type: str | None = None
    parent_session_id: str | None = None
    external_id: str | None = None
    q: str | None = None
    kinds: tuple[str, ...] = ()
    since: datetime | None = None
    exclude_benchmarks: bool = False
    model: str | None = None
    roots_only: bool = False


def session_last_active() -> ColumnElement[datetime]:
    """Honest activity timestamp; updated_at is bulk-touched by background jobs."""
    return func.coalesce(Session.last_activity_at, Session.created_at)


def _live_text(field_name: str) -> ColumnElement[str]:
    return Session.provider_metadata["live_activity"][field_name].as_string()


def _json_truthy(expr: ColumnElement[str]) -> ColumnElement[bool]:
    # Mirrors Python truthiness of the stored JSON value; never NULL.
    return and_(expr.isnot(None), expr.notin_(("false", "0", "", "null", "{}", "[]")))


def _live_state() -> ColumnElement[str]:
    return func.lower(
        func.coalesce(
            func.nullif(_live_text("lifecycle_state"), ""),
            func.nullif(_live_text("status"), ""),
            func.nullif(_live_text("state"), ""),
            "",
        )
    )


def _stored_stale_signal() -> ColumnElement[bool]:
    return or_(
        _json_truthy(_live_text("is_stale")),
        _json_truthy(_live_text("reapable")),
        _live_state().in_(("reapable", "stale", "stalled")),
    )


def session_running_predicate() -> ColumnElement[bool]:
    """The ``running`` alias: stored status active, unchanged for existing callers.

    Time-based staleness is computed at read time by build_live_activity_response
    and cannot be paged in SQL, so ``running`` stays the persisted active set.
    """
    return Session.status == "active"


def session_status_predicate(status: str) -> ColumnElement[bool]:
    """SQL form of the stored statuses and the live aliases running/stale/reapable.

    The aliases read the persisted ``provider_metadata.live_activity`` exactly as
    the former in-memory filter did, so totals are counted before paging.
    """
    if status == "running":
        return session_running_predicate()
    if status == "stale":
        return and_(Session.status == "active", _stored_stale_signal())
    if status == "reapable":
        return and_(
            Session.status == "active",
            or_(_json_truthy(_live_text("reapable")), _live_state() == "reapable"),
        )
    return Session.status == status


def session_kind_expression() -> ColumnElement[str | None]:
    return case(
        *[
            (Session.session_type.in_(session_types), kind)
            for kind, session_types in SESSION_KIND_TYPES.items()
        ],
        else_=None,
    )


def session_benchmark_predicate() -> ColumnElement[bool]:
    """SQL twin of ``session_attribution``'s benchmark rule (metadata session_kind)."""
    return Session.provider_metadata["session_kind"].as_string() == "benchmark"


# SQL twin of _session_metadata_helpers.requested_model(): metadata requested_model,
# else the first known entry of models_used, else the stored model.
_REQUESTED_MODEL_SQL = f"""coalesce(
    CASE WHEN json_typeof(sessions.provider_metadata -> 'requested_model') = 'string'
              AND (sessions.provider_metadata ->> 'requested_model') <> ''
         THEN sessions.provider_metadata ->> 'requested_model' END,
    (SELECT CASE WHEN json_typeof(m.value) = 'string' THEN m.value #>> '{{}}' END
       FROM json_array_elements(
              CASE WHEN json_typeof(sessions.models_used) = 'array'
                   THEN sessions.models_used ELSE '[]'::json END
            ) WITH ORDINALITY AS m(value, ord)
      WHERE NOT (json_typeof(m.value) = 'string' AND (m.value #>> '{{}}') = '{UNKNOWN_MODEL}')
      ORDER BY m.ord LIMIT 1),
    sessions.model)"""


def session_requested_model_expression() -> ColumnElement[str]:
    return literal_column(_REQUESTED_MODEL_SQL, type_=String)


def _search_predicate(q: str) -> ColumnElement[bool]:
    pattern = _like_pattern(q)
    return or_(
        Session.id.ilike(_like_pattern(q, prefix_only=True), escape="\\"),
        Session.summary_oneliner.ilike(pattern, escape="\\"),
        Session.external_id.ilike(pattern, escape="\\"),
        Session.current_branch.ilike(pattern, escape="\\"),
        Session.agent_slug.ilike(pattern, escape="\\"),
        Session.project_id.ilike(pattern, escape="\\"),
        Session.model.ilike(pattern, escape="\\"),
    )


def session_list_predicates(
    filters: SessionListFilters,
    *,
    ignore: frozenset[str] = frozenset(),
) -> list[ColumnElement[bool]]:
    """Return SQL predicates for the filters; ``ignore`` drops a facet dimension.

    Dimensions: ``project``, ``status`` and ``kind``.
    """
    predicates: list[ColumnElement[bool]] = []
    if filters.project_id and "project" not in ignore:
        predicates.append(Session.project_id == filters.project_id)
    if filters.status and "status" not in ignore:
        predicates.append(session_status_predicate(filters.status))
    if filters.kinds and "kind" not in ignore:
        session_types = [t for kind in filters.kinds for t in SESSION_KIND_TYPES[kind]]
        predicates.append(Session.session_type.in_(session_types))
    if filters.agent_slug:
        predicates.append(Session.agent_slug == filters.agent_slug)
    if filters.session_type:
        predicates.append(Session.session_type == filters.session_type)
    if filters.parent_session_id:
        predicates.append(Session.parent_session_id == filters.parent_session_id)
    if filters.external_id:
        predicates.append(Session.external_id == filters.external_id)
    if filters.roots_only:
        predicates.append(Session.parent_session_id.is_(None))
    if filters.since is not None:
        predicates.append(session_last_active() >= filters.since)
    if filters.exclude_benchmarks:
        predicates.append(~func.coalesce(session_benchmark_predicate(), false()))
    if filters.model:
        predicates.append(session_requested_model_expression() == filters.model)
    if filters.q and filters.q.strip():
        predicates.append(_search_predicate(filters.q.strip()))
    return predicates


async def fetch_session_facets(db: AsyncSession, filters: SessionListFilters) -> dict[str, Any]:
    """Grouped facet counts; each facet ignores its own dimension's filter."""
    status_rows = (
        await db.execute(
            select(
                Session.status,
                func.count(Session.id),
                func.count(Session.id).filter(session_running_predicate()),
            )
            .where(*session_list_predicates(filters, ignore=frozenset({"status"})))
            .group_by(Session.status)
        )
    ).all()
    status_counts = {"active": 0, "completed": 0, "failed": 0, "running": 0}
    for status, count, running in status_rows:
        if status in status_counts:
            status_counts[str(status)] += int(count)
        status_counts["running"] += int(running or 0)

    kind = session_kind_expression()
    kind_rows = (
        await db.execute(
            select(kind, func.count(Session.id))
            .where(*session_list_predicates(filters, ignore=frozenset({"kind"})))
            .group_by(kind)
        )
    ).all()
    kind_counts = dict.fromkeys(SESSION_KIND_TYPES, 0)
    for kind_name, count in kind_rows:
        if kind_name in kind_counts:
            kind_counts[str(kind_name)] = int(count)

    project_rows = (
        await db.execute(
            select(Session.project_id, func.count(Session.id))
            .where(*session_list_predicates(filters, ignore=frozenset({"project"})))
            .group_by(Session.project_id)
            .order_by(func.count(Session.id).desc(), Session.project_id.asc())
        )
    ).all()
    return {
        "status": status_counts,
        "kind": kind_counts,
        "projects": [
            {"project_id": str(project_id), "count": int(count)} for project_id, count in project_rows
        ],
    }


# ---------------------------------------------------------------------------
# Per-session rollups (title, native usage, event aggregates)
# ---------------------------------------------------------------------------


# Harness-injected context delivered as user messages (Codex AGENTS.md and
# <environment_context>, Claude Code <task-notification> / <pasted_content id=..>,
# sub-agent dispatch preambles); never a title.
_HARNESS_SCAFFOLD_PATTERN = (
    r"^\s*(# AGENTS\.md instructions|<[a-z][a-z0-9_-]*(\s[^>]*)?>"
    r"|Message Type: [A-Z_]+|The following is the Codex agent history)"
)


def normalize_session_title(content: str | None) -> str | None:
    if not content:
        return None
    collapsed = " ".join(content.split())
    return collapsed[:SESSION_TITLE_MAX_CHARS] or None


async def fetch_session_titles(db: AsyncSession, session_ids: Sequence[str]) -> dict[str, str]:
    """First non-blank user message per session, in one DISTINCT ON query."""
    if not session_ids:
        return {}
    rows = (
        await db.execute(
            select(
                SessionEvent.session_id,
                func.left(SessionEvent.content, _TITLE_SOURCE_PREFIX_CHARS),
            )
            .where(
                SessionEvent.session_id.in_(list(session_ids)),
                SessionEvent.event_type == SessionEventType.USER_MESSAGE,
                SessionEvent.content.op("~")(r"\S"),
                ~SessionEvent.content.op("~*")(_HARNESS_SCAFFOLD_PATTERN),
            )
            .distinct(SessionEvent.session_id)
            .order_by(SessionEvent.session_id, SessionEvent.turn, SessionEvent.sequence)
        )
    ).all()
    titles: dict[str, str] = {}
    for session_id, content in rows:
        title = normalize_session_title(content)
        if title:
            titles[str(session_id)] = title
    return titles


@dataclass(frozen=True)
class SessionUsageRollup:
    """Native response-scope usage totals; a field is None when never recorded."""

    responses: int = 0
    input_tokens: int | None = None
    output_tokens: int | None = None
    cached_input_tokens: int | None = None

    @property
    def known(self) -> bool:
        return self.responses > 0

    def as_fields(self) -> dict[str, Any]:
        return {
            "usage_known": self.known,
            "usage_input_tokens": self.input_tokens,
            "usage_output_tokens": self.output_tokens,
            "usage_cached_input_tokens": self.cached_input_tokens,
        }


def _usage_count_sql(field_name: str) -> str:
    return (
        f"CASE WHEN json_typeof(usage -> '{field_name}') = 'number' "
        f"AND (usage ->> '{field_name}') ~ '^[0-9]+$' "
        f"THEN (usage ->> '{field_name}')::bigint END"
    )


# Matches the frontend NativeUsage summary: only ``usage`` events with
# scope=response and a string source count, deduplicated by response_id
# (else source_event_id, else id). turn/thread scopes live on cumulative
# ``usage_counter`` events and are never summed, so nothing is double counted.
_USAGE_ROLLUP_SQL = text(
    f"""
    WITH responses AS (
        SELECT DISTINCT ON (e.session_id, e.identity) e.session_id, e.usage
        FROM (
            SELECT session_id, usage, turn, sequence,
                   CASE WHEN json_typeof(usage -> 'response_id') = 'string'
                             AND (usage ->> 'response_id') <> ''
                        THEN usage ->> 'response_id'
                        ELSE coalesce(nullif(source_event_id, ''), id::text) END AS identity
            FROM session_events
            WHERE session_id IN :session_ids
              AND event_type = 'usage'
              AND json_typeof(usage) = 'object'
              AND (usage ->> 'scope') = 'response'
              AND json_typeof(usage -> 'source') = 'string'
        ) e
        ORDER BY e.session_id, e.identity, e.turn, e.sequence
    )
    SELECT session_id,
           count(*) AS responses,
           sum({_usage_count_sql("input_tokens")}) AS input_tokens,
           sum({_usage_count_sql("output_tokens")}) AS output_tokens,
           sum({_usage_count_sql("cached_input_tokens")}) AS cached_input_tokens
    FROM responses
    GROUP BY session_id
    """
).bindparams(bindparam("session_ids", expanding=True))


# Sessions without native usage events: the transcript call ledger (a root session includes its
# sub-agents; a Codex child thread matches its own agent id) and completion cost logs. Input counts
# fresh, cached and cache-write tokens, matching the native events' inclusive input.
_LEDGER_USAGE_SQL = text(
    """
    SELECT sid, count(*), sum(inp), sum(outp), sum(cached)
    FROM (
        SELECT session_id AS sid, input_tokens + cached_input_tokens + cache_write_tokens AS inp,
               output_tokens AS outp, cached_input_tokens AS cached
        FROM usage_calls WHERE session_id IN :session_ids
        UNION ALL
        SELECT agent_id, input_tokens + cached_input_tokens + cache_write_tokens, output_tokens,
               cached_input_tokens
        FROM usage_calls WHERE agent_id IN :session_ids
        UNION ALL
        SELECT session_id, coalesce(input_tokens, 0) + coalesce(cache_read_tokens, 0)
                   + coalesce(cache_write_tokens, 0),
               coalesce(output_tokens, 0), coalesce(cache_read_tokens, 0)
        FROM cost_logs WHERE session_id IN :session_ids
    ) calls
    GROUP BY sid
    """
).bindparams(bindparam("session_ids", expanding=True))


def _optional_int(value: object) -> int | None:
    return None if value is None else int(value)


async def fetch_session_usage_rollups(
    db: AsyncSession, session_ids: Sequence[str]
) -> dict[str, SessionUsageRollup]:
    """Roll up native usage for many sessions in one grouped query."""
    if not session_ids:
        return {}
    rows = (await db.execute(_USAGE_ROLLUP_SQL, {"session_ids": list(session_ids)})).all()
    rollups = {
        str(session_id): SessionUsageRollup(
            responses=int(responses),
            input_tokens=_optional_int(input_tokens),
            output_tokens=_optional_int(output_tokens),
            cached_input_tokens=_optional_int(cached_input_tokens),
        )
        for session_id, responses, input_tokens, output_tokens, cached_input_tokens in rows
    }
    missing = [sid for sid in session_ids if sid not in rollups]
    if missing:
        fallback = (await db.execute(_LEDGER_USAGE_SQL, {"session_ids": missing})).all()
        for session_id, responses, input_tokens, output_tokens, cached_input_tokens in fallback:
            rollups[str(session_id)] = SessionUsageRollup(
                responses=int(responses),
                input_tokens=int(input_tokens),
                output_tokens=int(output_tokens),
                cached_input_tokens=int(cached_input_tokens),
            )
    return rollups


async def fetch_session_event_type_counts(db: AsyncSession, session_id: str) -> dict[str, int]:
    rows = (
        await db.execute(
            select(SessionEvent.event_type, func.count())
            .where(SessionEvent.session_id == session_id)
            .group_by(SessionEvent.event_type)
        )
    ).all()
    return {str(event_type): int(count) for event_type, count in rows}


@dataclass(frozen=True)
class AgentTokenAggregate:
    agent_key: str
    agent_name: str | None
    input_tokens: int
    output_tokens: int
    event_count: int


async def fetch_session_agent_token_aggregates(
    db: AsyncSession, session_id: str
) -> list[AgentTokenAggregate]:
    """SQL twin of calculate_agent_token_breakdown over all session events."""
    from sqlalchemy.dialects.postgresql import aggregate_order_by, array_agg

    agent_key = func.coalesce(func.nullif(SessionEvent.agent_id, ""), "_default")
    tokens = func.coalesce(SessionEvent.tokens, 0)
    is_user = SessionEvent.role == "user"
    # bigint: turn * 1e9 overflows int4 from turn 3 on.
    first_position = func.min(
        func.cast(SessionEvent.turn, BigInteger) * 1_000_000_000 + SessionEvent.sequence
    )
    rows = (
        await db.execute(
            select(
                agent_key,
                array_agg(
                    aggregate_order_by(
                        SessionEvent.agent_name, SessionEvent.turn.asc(), SessionEvent.sequence.asc()
                    )
                )[1],
                func.coalesce(func.sum(case((is_user, tokens), else_=0)), 0),
                func.coalesce(func.sum(case((is_user, 0), else_=tokens)), 0),
                func.count(SessionEvent.id),
            )
            .where(SessionEvent.session_id == session_id)
            .group_by(agent_key)
            .order_by(first_position)
        )
    ).all()
    return [
        AgentTokenAggregate(
            agent_key=str(key),
            agent_name=name,
            input_tokens=int(input_tokens),
            output_tokens=int(output_tokens),
            event_count=int(count),
        )
        for key, name, input_tokens, output_tokens, count in rows
    ]


@dataclass(frozen=True)
class SessionEventsSummaryData:
    total: int
    by_type: dict[str, int]
    first_user_message: str | None
    usage: SessionUsageRollup


async def fetch_session_events_summary(db: AsyncSession, session_id: str) -> SessionEventsSummaryData:
    by_type = await fetch_session_event_type_counts(db, session_id)
    titles = await fetch_session_titles(db, [session_id])
    usage = (await fetch_session_usage_rollups(db, [session_id])).get(session_id, SessionUsageRollup())
    return SessionEventsSummaryData(
        total=sum(by_type.values()),
        by_type=by_type,
        first_user_message=titles.get(session_id),
        usage=usage,
    )


# ---------------------------------------------------------------------------
# Session events window
# ---------------------------------------------------------------------------


def encode_session_event_cursor(order: str, turn: int, sequence: int) -> str:
    value = f"{order}\n{turn}\n{sequence}".encode()
    return base64.urlsafe_b64encode(value).decode().rstrip("=")


def decode_session_event_cursor(cursor: str, order: str) -> tuple[int, int]:
    try:
        padding = "=" * (-len(cursor) % 4)
        cursor_order, turn_text, sequence_text = (
            base64.urlsafe_b64decode(cursor + padding).decode().split("\n")
        )
        turn, sequence = int(turn_text), int(sequence_text)
    except (ValueError, UnicodeDecodeError) as exc:
        raise ValueError("Invalid session event cursor") from exc
    if cursor_order != order:
        raise ValueError("Session event cursor does not match the requested order")
    return turn, sequence


@dataclass
class SessionEventWindow:
    events: list[SessionEvent]
    total: int
    max_turn: int
    snapshot: str
    next_after: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


async def query_session_event_window(
    db: AsyncSession,
    session_id: str,
    *,
    event_type: str | None = None,
    turn: int | None = None,
    page: int = 1,
    page_size: int = 100,
    snapshot: str | None = None,
    exclude_types: Sequence[str] = (),
    q: str | None = None,
    after: str | None = None,
    order: str = "asc",
) -> SessionEventWindow:
    """Filtered, snapshot-bounded event window with offset or keyset paging.

    ``total`` counts the filtered set under the snapshot. ``after`` (keyset on
    turn, sequence in ``order``) replaces the page offset when given.
    """
    if order not in _EVENT_ORDERS:
        raise ValueError(f"Unsupported event order: {order}")
    after_key = decode_session_event_cursor(after, order) if after else None

    if snapshot is None:
        snapshot_result = await db.execute(
            select(SessionEvent.created_at, SessionEvent.id)
            .where(SessionEvent.session_id == session_id)
            .order_by(SessionEvent.created_at.desc(), SessionEvent.id.desc())
            .limit(1)
        )
        snapshot_row = snapshot_result.one_or_none()
        snapshot = (
            encode_session_event_snapshot(snapshot_row[0], snapshot_row[1])
            if snapshot_row is not None
            else _EMPTY_EVENT_SNAPSHOT
        )

    boundary = _decode_session_event_snapshot(snapshot)
    snapshot_predicate = (
        false()
        if boundary is None
        else or_(
            SessionEvent.created_at < boundary[0],
            and_(
                SessionEvent.created_at == boundary[0],
                SessionEvent.id <= boundary[1],
            ),
        )
    )
    predicates: list[ColumnElement[bool]] = [
        SessionEvent.session_id == session_id,
        snapshot_predicate,
    ]
    if event_type:
        predicates.append(SessionEvent.event_type == event_type)
    if exclude_types:
        predicates.append(SessionEvent.event_type.notin_(list(exclude_types)))
    if turn is not None:
        predicates.append(SessionEvent.turn == turn)
    if q and q.strip():
        pattern = _like_pattern(q.strip())
        predicates.append(
            or_(
                SessionEvent.content.ilike(pattern, escape="\\"),
                SessionEvent.tool_name.ilike(pattern, escape="\\"),
            )
        )

    total_result = await db.execute(select(func.count()).select_from(SessionEvent).where(*predicates))
    total = total_result.scalar() or 0

    max_turn_result = await db.execute(
        select(func.max(SessionEvent.turn)).where(
            SessionEvent.session_id == session_id,
            snapshot_predicate,
        )
    )
    max_turn = max_turn_result.scalar() or 0

    position = tuple_(SessionEvent.turn, SessionEvent.sequence)
    query = select(SessionEvent).where(*predicates)
    if order == "desc":
        if after_key is not None:
            query = query.where(position < tuple_(*after_key))
        query = query.order_by(
            SessionEvent.turn.desc(),
            SessionEvent.sequence.desc(),
            SessionEvent.created_at.desc(),
            SessionEvent.id.desc(),
        )
    else:
        if after_key is not None:
            query = query.where(position > tuple_(*after_key))
        query = query.order_by(
            SessionEvent.turn.asc(),
            SessionEvent.sequence.asc(),
            SessionEvent.created_at.asc(),
            SessionEvent.id.asc(),
        )
    if after_key is None:
        query = query.offset((page - 1) * page_size)
    query = query.limit(page_size + 1)

    result = await db.execute(query)
    events = list(result.scalars().all())
    next_after: str | None = None
    if len(events) > page_size:
        events = events[:page_size]
        last = events[-1]
        next_after = encode_session_event_cursor(order, int(last.turn), int(last.sequence))
    return SessionEventWindow(
        events=events,
        total=int(total),
        max_turn=int(max_turn),
        snapshot=snapshot,
        next_after=next_after,
    )


async def query_session_events(
    db: AsyncSession,
    session_id: str,
    event_type: str | None = None,
    turn: int | None = None,
    page: int = 1,
    page_size: int = 100,
    snapshot: str | None = None,
) -> tuple[list[SessionEvent], int, int, str]:
    """Query session events with filtering and offset pagination.

    Returns:
        Tuple of (events, total_count, max_turn, stable snapshot)
    """
    window = await query_session_event_window(
        db,
        session_id,
        event_type=event_type,
        turn=turn,
        page=page,
        page_size=page_size,
        snapshot=snapshot,
    )
    return window.events, window.total, window.max_turn, window.snapshot
