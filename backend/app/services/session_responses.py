"""Session response building - construct API responses from domain models."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Session, SessionEvent

if TYPE_CHECKING:
    from app.api.schemas.sessions import (
        SessionEventResponse,
        SessionResponse,
    )
from app.services.context_tracker import calculate_context_usage
from app.services.ownership_inventory import (
    query_project_active_specialists,
    query_project_ownership,
)
from app.services.persona_identity import PERSONA_SLUG, get_persona_display_name
from app.services.session_tokens import calculate_agent_token_breakdown
from app.services.session_transforms import (
    _effective_model,
    _message_count,
    build_session_response,
    convert_messages_to_response,
)


def _row_slug_and_name(row: Any) -> tuple[str | None, str | None]:
    slug = getattr(row, "slug", None)
    name = getattr(row, "name", None)
    if slug is not None or name is not None:
        return slug, name
    if hasattr(row, "_mapping"):
        mapping = row._mapping
        return mapping.get("slug"), mapping.get("name")
    if isinstance(row, tuple) and len(row) >= 2:
        return row[0], row[1]
    return None, None


async def _resolve_agent_display_names(
    db: AsyncSession, events: list[SessionEvent],
) -> dict[str, str]:
    """Build agent_id/slug → display name map from agents table.

    Uses single WHERE slug IN (...) query instead of one query per slug.
    """
    from sqlalchemy import select

    from app.models.agent import Agent

    slugs = {e.agent_id for e in events if e.agent_id}
    slugs |= {e.agent_name for e in events if e.agent_name}
    if not slugs:
        return {}

    result = await db.execute(
        select(Agent.slug, Agent.name).where(Agent.slug.in_(slugs))
    )
    names: dict[str, str] = {}
    for row in result.all():
        slug, name = _row_slug_and_name(row)
        if slug and name:
            names[slug] = name
    if PERSONA_SLUG in slugs:
        names[PERSONA_SLUG] = await get_persona_display_name(
            db,
            fallback=names.get(PERSONA_SLUG),
        )
    return names


async def build_project_lane_session_ids(
    db: AsyncSession,
    project_ids: set[str],
) -> tuple[set[str], set[str]]:
    """Return (owner_session_ids, specialist_session_ids) for given projects."""
    owner_session_ids: set[str] = set()
    specialist_session_ids: set[str] = set()
    for project_id in sorted(project_id for project_id in project_ids if project_id):
        owner_session_ids.update(
            str(owner.session_id)
            for owner in await query_project_ownership(db, project_id)
            if getattr(owner, "session_id", None)
        )
        specialist_session_ids.update(
            str(session.session_id)
            for session in await query_project_active_specialists(db, project_id)
            if getattr(session, "session_id", None)
        )
    return owner_session_ids, specialist_session_ids


async def build_full_session_response(
    db: AsyncSession, session: Session
) -> SessionResponse:
    """Build complete session response with context usage and token breakdown."""
    # Deferred import to avoid circular import via app.api.__init__
    from app.api.schemas.sessions import ContextUsageResponse

    ctx_usage = await calculate_context_usage(db, session.id, _effective_model(session))
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

    agent_names = await _resolve_agent_display_names(db, session.events)
    owner_session_ids, specialist_session_ids = await build_project_lane_session_ids(
        db,
        {session.project_id},
    )

    return build_session_response(
        session,
        convert_messages_to_response(session.events, agent_display_names=agent_names),
        context_usage_response,
        agent_breakdown,
        total_input,
        total_output,
        message_count=_message_count(session.events),
        event_count=len(session.events),
        owner_session_ids=owner_session_ids,
        specialist_session_ids=specialist_session_ids,
    )


def build_event_responses(events: list[SessionEvent]) -> list[SessionEventResponse]:
    """Convert session events to API response models."""
    # Deferred import to avoid circular import via app.api.__init__
    from app.api.schemas.sessions import SessionEventResponse

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
