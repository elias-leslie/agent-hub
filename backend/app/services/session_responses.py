"""Session response building - construct API responses from domain models."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas.sessions import (
    ContextUsageResponse,
    SessionEventResponse,
    SessionResponse,
)
from app.models import Session, SessionEvent
from app.services.context_tracker import calculate_context_usage
from app.services.session_transforms import (
    build_session_response,
    convert_messages_to_response,
)
from app.services.session_tokens import calculate_agent_token_breakdown


async def build_full_session_response(
    db: AsyncSession, session: Session
) -> SessionResponse:
    """Build a complete session response with context usage and token breakdown.

    Args:
        db: Database session
        session: Session object with events loaded

    Returns:
        Complete SessionResponse with all metadata
    """
    ctx_usage = await calculate_context_usage(db, session.id, session.model)
    context_usage_response = ContextUsageResponse(
        used_tokens=ctx_usage.used_tokens,
        limit_tokens=ctx_usage.limit_tokens,
        percent_used=ctx_usage.percent_used,
        remaining_tokens=ctx_usage.remaining_tokens,
        warning=ctx_usage.warning,
    )

    agent_breakdown, total_input, total_output = calculate_agent_token_breakdown(
        session.events
    )

    return build_session_response(
        session,
        convert_messages_to_response(session.events),
        context_usage_response,
        agent_breakdown,
        total_input,
        total_output,
    )


def build_event_responses(events: list[SessionEvent]) -> list[SessionEventResponse]:
    """Convert session events to API response models.

    Args:
        events: List of SessionEvent objects

    Returns:
        List of SessionEventResponse objects
    """
    return [
        SessionEventResponse(
            id=str(e.id),
            turn=e.turn,
            sequence=e.sequence,
            event_type=e.event_type,
            role=e.role,
            content=e.content,
            tool_name=e.tool_name,
            tool_input=e.tool_input,
            tool_output=e.tool_output,
            tokens=e.tokens,
            duration_ms=e.duration_ms,
            model_used=e.model_used,
            agent_id=e.agent_id,
            agent_name=e.agent_name,
            created_at=e.created_at,
        )
        for e in events
    ]
