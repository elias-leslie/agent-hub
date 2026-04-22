"""Session query filters and statistics."""

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import Session, SessionEvent, SessionEventType


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


async def fetch_session_statistics(
    db: AsyncSession, session_ids: list[str]
) -> tuple[dict[str, int], dict[str, int], dict[str, dict[str, int]]]:
    """Fetch message counts, event counts, and token statistics for sessions.

    Args:
        db: Database session
        session_ids: List of session IDs

    Returns:
        Tuple of (message_counts, event_counts, token_stats)
    """
    message_counts: dict[str, int] = {}
    event_counts: dict[str, int] = {}
    token_stats: dict[str, dict[str, int]] = {}

    if not session_ids:
        return message_counts, event_counts, token_stats

    from typing import cast

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
    message_counts = dict(cast(list[tuple[str, int]], message_counts_result.all()))

    event_counts_result = await db.execute(
        select(SessionEvent.session_id, func.count(SessionEvent.id))
        .where(SessionEvent.session_id.in_(session_ids))
        .group_by(SessionEvent.session_id)
    )
    event_counts = dict(cast(list[tuple[str, int]], event_counts_result.all()))

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

    return message_counts, event_counts, token_stats


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
        page: Page number (1-indexed)
        page_size: Items per page

    Returns:
        Tuple of (events, total_count, max_turn)
    """
    # Build query
    query = select(SessionEvent).where(SessionEvent.session_id == session_id)

    # Apply filters
    if event_type:
        query = query.where(SessionEvent.event_type == event_type)
    if turn is not None:
        query = query.where(SessionEvent.turn == turn)

    # Count total
    count_query = select(func.count(SessionEvent.id)).where(SessionEvent.session_id == session_id)
    if event_type:
        count_query = count_query.where(SessionEvent.event_type == event_type)
    if turn is not None:
        count_query = count_query.where(SessionEvent.turn == turn)
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    # Get max turn
    max_turn_query = select(func.max(SessionEvent.turn)).where(
        SessionEvent.session_id == session_id
    )
    max_turn_result = await db.execute(max_turn_query)
    max_turn = max_turn_result.scalar() or 0

    # Apply pagination and ordering
    offset = (page - 1) * page_size
    query = query.order_by(SessionEvent.turn, SessionEvent.sequence).offset(offset).limit(page_size)

    # Execute
    events_result = await db.execute(query)
    events: list[SessionEvent] = list(events_result.scalars().all())

    return events, total, max_turn
