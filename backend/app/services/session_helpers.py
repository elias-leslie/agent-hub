"""Session helper utilities - Token calculations and data transformations."""

from typing import Any

from fastapi import HTTPException
from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas.sessions import (
    AgentTokenBreakdown,
    ContextUsageResponse,
    MessageResponse,
    SessionListItem,
    SessionResponse,
)
from app.models import Message, Session


def calculate_agent_token_breakdown(
    messages: list[Any],
) -> tuple[list[AgentTokenBreakdown], int, int]:
    """Calculate token breakdown by agent for multi-agent sessions.

    Args:
        messages: List of message objects

    Returns:
        Tuple of (agent_breakdown, total_input, total_output)
    """
    agent_stats: dict[str, dict[str, Any]] = {}
    total_input = 0
    total_output = 0

    # Group messages by agent_id
    for m in messages:
        agent_key = m.agent_id or "_default"
        if agent_key not in agent_stats:
            agent_stats[agent_key] = {
                "agent_id": m.agent_id or "default",
                "agent_name": m.agent_name,
                "input_tokens": 0,
                "output_tokens": 0,
                "message_count": 0,
            }
        tokens = m.tokens or 0
        if m.role == "user":
            agent_stats[agent_key]["input_tokens"] += tokens
            total_input += tokens
        else:
            agent_stats[agent_key]["output_tokens"] += tokens
            total_output += tokens
        agent_stats[agent_key]["message_count"] += 1

    # Build breakdown list (only if multiple agents or explicit agent_id)
    agent_breakdown: list[AgentTokenBreakdown] = []
    for stats in agent_stats.values():
        if stats["agent_id"] != "default" or len(agent_stats) > 1:
            agent_breakdown.append(
                AgentTokenBreakdown(
                    agent_id=stats["agent_id"],
                    agent_name=stats["agent_name"],
                    input_tokens=stats["input_tokens"],
                    output_tokens=stats["output_tokens"],
                    total_tokens=stats["input_tokens"] + stats["output_tokens"],
                    message_count=stats["message_count"],
                )
            )

    return agent_breakdown, total_input, total_output


def convert_messages_to_response(messages: list[Any]) -> list[MessageResponse]:
    """Convert message models to response schemas.

    Args:
        messages: List of message objects

    Returns:
        List of MessageResponse schemas
    """
    return [
        MessageResponse(
            id=m.id,
            role=m.role,
            content=m.content,
            tokens=m.tokens,
            agent_id=m.agent_id,
            agent_name=m.agent_name,
            model_used=m.model_used,
            created_at=m.created_at,
        )
        for m in sorted(messages, key=lambda x: x.created_at)
    ]


def calculate_fork_messages(sorted_messages: list[Any], fork_at_turn: int) -> tuple[list[Any], int]:
    """Calculate which messages to copy for a fork operation.

    Args:
        sorted_messages: Messages sorted by created_at
        fork_at_turn: Turn number to fork at

    Returns:
        Tuple of (messages_to_copy, total_turns)
    """
    total_turns = sum(1 for m in sorted_messages if m.role == "assistant")
    messages_to_copy = []
    turn_count = 0

    for m in sorted_messages:
        messages_to_copy.append(m)
        if m.role == "assistant":
            turn_count += 1
            if turn_count >= fork_at_turn:
                break

    return messages_to_copy, total_turns


def prepare_fork_data(
    sorted_messages: list[Any], fork_at_turn: int | None
) -> tuple[list[Any], int]:
    """Prepare data for forking a session.

    Args:
        sorted_messages: Messages sorted by created_at
        fork_at_turn: Turn number to fork at (None = all messages)

    Returns:
        Tuple of (messages_to_copy, fork_at)

    Raises:
        HTTPException: If fork_at_turn is invalid
    """
    if fork_at_turn is None:
        total_turns = sum(1 for m in sorted_messages if m.role == "assistant")
        return sorted_messages, total_turns

    messages_to_copy, total_turns = calculate_fork_messages(sorted_messages, fork_at_turn)

    if fork_at_turn < 0 or fork_at_turn > total_turns:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid fork_at_turn. Must be between 0 and {total_turns}",
        )

    return messages_to_copy, fork_at_turn


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
    """Fetch message counts and token statistics for sessions.

    Args:
        db: Database session
        session_ids: List of session IDs

    Returns:
        Tuple of (message_counts, token_stats)
    """
    msg_counts: dict[str, int] = {}
    token_stats: dict[str, dict[str, int]] = {}

    if not session_ids:
        return msg_counts, token_stats

    # Message counts
    msg_counts_result = await db.execute(
        select(Message.session_id, func.count(Message.id))
        .where(Message.session_id.in_(session_ids))
        .group_by(Message.session_id)
    )
    from typing import cast

    msg_counts = dict(cast(list[tuple[str, int]], msg_counts_result.all()))

    # Token sums by role
    token_result = await db.execute(
        select(
            Message.session_id,
            Message.role,
            func.coalesce(func.sum(Message.tokens), 0),
        )
        .where(Message.session_id.in_(session_ids))
        .group_by(Message.session_id, Message.role)
    )
    for session_id, role, tokens in token_result.all():
        if session_id not in token_stats:
            token_stats[session_id] = {"input": 0, "output": 0}
        if role == "user":
            token_stats[session_id]["input"] = tokens
        elif role == "assistant":
            token_stats[session_id]["output"] = tokens

    return msg_counts, token_stats


def build_session_list_items(
    sessions: list[Session],
    msg_counts: dict[str, int],
    token_stats: dict[str, dict[str, int]],
) -> list[SessionListItem]:
    """Build list of session items with statistics.

    Args:
        sessions: List of session models
        msg_counts: Message counts by session ID
        token_stats: Token statistics by session ID

    Returns:
        List of SessionListItem schemas
    """
    return [
        SessionListItem(
            id=s.id,
            project_id=s.project_id,
            provider=s.provider,
            model=s.model,
            status=s.status,
            agent_slug=s.agent_slug,
            session_type=s.session_type or "completion",
            message_count=msg_counts.get(s.id, 0),
            total_input_tokens=token_stats.get(s.id, {}).get("input", 0),
            total_output_tokens=token_stats.get(s.id, {}).get("output", 0),
            created_at=s.created_at,
            updated_at=s.updated_at,
        )
        for s in sessions
    ]


def copy_messages_to_forked_session(
    db: Any, messages_to_copy: list[Any], new_session_id: str
) -> None:
    """Copy messages to a new forked session.

    Args:
        db: Database session
        messages_to_copy: List of messages to copy
        new_session_id: ID of the new session
    """
    for orig_msg in messages_to_copy:
        new_msg = Message(
            session_id=new_session_id,
            role=orig_msg.role,
            content=orig_msg.content,
            tokens=orig_msg.tokens,
            agent_id=orig_msg.agent_id,
            agent_name=orig_msg.agent_name,
            model_used=orig_msg.model_used,
        )
        db.add(new_msg)


def create_forked_session(parent: Session, new_session_id: str, fork_at: int) -> Session:
    """Create a new forked session based on parent.

    Args:
        parent: Parent session
        new_session_id: ID for the new session
        fork_at: Turn number where fork occurred

    Returns:
        New forked Session object
    """
    return Session(
        id=new_session_id,
        project_id=parent.project_id,
        provider=parent.provider,
        model=parent.model,
        status="active",
        agent_slug=parent.agent_slug,
        session_type=parent.session_type,
        parent_session_id=parent.id,
        fork_point_turn=fork_at,
        branch_status="active",
        continuation_count=0,
        provider_metadata=parent.provider_metadata.copy() if parent.provider_metadata else None,
    )


async def discard_sibling_sessions(
    db: AsyncSession, parent_session_id: str, exclude_session_id: str
) -> list[str]:
    """Mark sibling sessions as discarded.

    Args:
        db: Database session
        parent_session_id: Parent session ID
        exclude_session_id: Session ID to exclude from discarding

    Returns:
        List of discarded session IDs
    """
    discarded_siblings: list[str] = []
    siblings_result = await db.execute(
        select(Session).where(
            Session.parent_session_id == parent_session_id,
            Session.id != exclude_session_id,
            Session.branch_status == "active",
        )
    )
    siblings = siblings_result.scalars().all()
    for sibling in siblings:
        sibling.branch_status = "discarded"
        sibling.manual_outcome = "discarded"
        discarded_siblings.append(sibling.id)
    return discarded_siblings


def validate_promotion_eligibility(session: Session) -> None:
    """Validate if a session can be promoted.

    Args:
        session: Session to validate

    Raises:
        HTTPException: If session cannot be promoted
    """
    if session.parent_session_id is None:
        raise HTTPException(status_code=400, detail="Cannot promote a non-branched session")
    if session.branch_status == "promoted":
        raise HTTPException(status_code=400, detail="Session is already promoted")
    if session.branch_status == "discarded":
        raise HTTPException(status_code=400, detail="Cannot promote a discarded session")


def build_session_response(
    session: Session,
    messages: list[MessageResponse] | None = None,
    context_usage: ContextUsageResponse | None = None,
    agent_breakdown: list[AgentTokenBreakdown] | None = None,
    total_input: int = 0,
    total_output: int = 0,
) -> SessionResponse:
    """Build a SessionResponse from session data.

    Args:
        session: Session model
        messages: Optional list of messages
        context_usage: Optional context usage info
        agent_breakdown: Optional agent token breakdown
        total_input: Total input tokens
        total_output: Total output tokens

    Returns:
        SessionResponse schema
    """
    return SessionResponse(
        id=session.id,
        project_id=session.project_id,
        provider=session.provider,
        model=session.model,
        status=session.status,
        agent_slug=session.agent_slug,
        session_type=session.session_type or "completion",
        created_at=session.created_at,
        updated_at=session.updated_at,
        messages=messages or [],
        context_usage=context_usage,
        agent_token_breakdown=agent_breakdown or [],
        total_input_tokens=total_input,
        total_output_tokens=total_output,
    )
