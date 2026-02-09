"""Session query filters and statistics."""

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Session, SessionEvent, SessionEventType


def apply_session_filters(
    query: Select[tuple[Session]],
    count_query: Select[tuple[int]],
    project_id: str | None = None,
    status: str | None = None,
    agent_slug: str | None = None,
    session_type: str | None = None,
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

    return query, count_query


async def fetch_session_statistics(
    db: AsyncSession, session_ids: list[str]
) -> tuple[dict[str, int], dict[str, dict[str, int]]]:
    """Fetch event counts and token statistics for sessions.

    Args:
        db: Database session
        session_ids: List of session IDs

    Returns:
        Tuple of (event_counts, token_stats)
    """
    event_counts: dict[str, int] = {}
    token_stats: dict[str, dict[str, int]] = {}

    if not session_ids:
        return event_counts, token_stats

    from typing import cast

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

    return event_counts, token_stats
