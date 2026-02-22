"""Session data transformations."""

from typing import Any

from app.api.schemas.sessions import (
    AgentTokenBreakdown,
    ContextUsageResponse,
    MessageResponse,
    SessionListItem,
    SessionResponse,
)
from app.models import Session


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
            summary_oneliner=s.summary_oneliner,
            message_count=msg_counts.get(s.id, 0),
            total_input_tokens=token_stats.get(s.id, {}).get("input", 0),
            total_output_tokens=token_stats.get(s.id, {}).get("output", 0),
            created_at=s.created_at,
            updated_at=s.updated_at,
        )
        for s in sessions
    ]


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
