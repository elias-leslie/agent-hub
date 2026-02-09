"""Session branching operations - forking and promotion."""

from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Session, SessionEvent


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


def copy_events_to_forked_session(db: Any, events_to_copy: list[Any], new_session_id: str) -> None:
    """Copy events to a new forked session.

    Args:
        db: Database session
        events_to_copy: List of events to copy
        new_session_id: ID of the new session
    """
    for orig_event in events_to_copy:
        new_event = SessionEvent(
            session_id=new_session_id,
            turn=orig_event.turn,
            sequence=orig_event.sequence,
            event_type=orig_event.event_type,
            role=orig_event.role,
            content=orig_event.content,
            tool_name=orig_event.tool_name,
            tool_input=orig_event.tool_input,
            tool_output=orig_event.tool_output,
            tokens=orig_event.tokens,
            duration_ms=orig_event.duration_ms,
            model_used=orig_event.model_used,
            agent_id=orig_event.agent_id,
            agent_name=orig_event.agent_name,
        )
        db.add(new_event)


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
