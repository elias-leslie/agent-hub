"""Session query filters and statistics."""

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import Session, SessionEvent, SessionEventType
from app.services.session_live_activity import is_session_actionably_active


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


async def query_session_events(
    db: AsyncSession,
    session_id: str,
    event_type: str | None = None,
    turn: int | None = None,
    page: int = 1,
    page_size: int = 100,
) -> tuple[list[SessionEvent], int, int]:
    """Query session events with filtering and pagination.

    Args:
        db: Database session
        session_id: Session ID
        event_type: Optional event type filter
        turn: Optional turn number filter
        page: Page number (1-based)
        page_size: Results per page

    Returns:
        Tuple of (events, total_count, total_pages)
    """
    query = select(SessionEvent).where(SessionEvent.session_id == session_id)
    count_query = select(func.count(SessionEvent.id)).where(SessionEvent.session_id == session_id)

    if event_type:
        query = query.where(SessionEvent.event_type == event_type)
        count_query = count_query.where(SessionEvent.event_type == event_type)
    if turn is not None:
        query = query.where(SessionEvent.turn == turn)
        count_query = count_query.where(SessionEvent.turn == turn)

    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    total_pages = (total + page_size - 1) // page_size if total > 0 else 0
    offset = (page - 1) * page_size

    query = (
        query.order_by(SessionEvent.turn.asc(), SessionEvent.sequence.asc())
        .offset(offset)
        .limit(page_size)
    )

    result = await db.execute(query)
    events = list(result.scalars().all())

    return events, total, total_pages
