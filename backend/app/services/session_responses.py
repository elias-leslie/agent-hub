"""Session response building - construct API responses from domain models."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Session, SessionEvent, SessionEventType
from app.services.event_storage import known_model
from app.services.session_live_activity import is_session_actionably_active

if TYPE_CHECKING:
    from app.api.schemas.sessions import (
        AgentTokenBreakdown,
        SessionEventResponse,
        SessionListItem,
        SessionResponse,
    )
from app.services.context_tracker import calculate_context_usage
from app.services.ownership_inventory import (
    query_project_active_specialists,
    query_project_ownership,
)
from app.services.session_queries import (
    AgentTokenAggregate,
    SessionUsageRollup,
    fetch_session_agent_token_aggregates,
    fetch_session_event_type_counts,
    fetch_session_titles,
    fetch_session_usage_rollups,
)
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


def identity_title(session: Session) -> str | None:
    """Sub-agent task path and display name when the transcript has no usable prompt."""
    metadata = session.provider_metadata if isinstance(session.provider_metadata, dict) else {}
    identity = metadata.get("external_identity")
    if not isinstance(identity, dict):
        return None
    agent_path = identity.get("agent_path")
    task = agent_path.rsplit("/", 1)[-1] if isinstance(agent_path, str) and agent_path != "/root" else ""
    display = identity.get("display_identity")
    parts = [part for part in (task, display if isinstance(display, str) else "") if part.strip()]
    return " · ".join(parts) or None


def apply_session_rollups(
    item: SessionListItem | SessionResponse,
    session: Session,
    *,
    title: str | None,
    usage: SessionUsageRollup | None,
) -> SessionListItem | SessionResponse:
    """Attach title, native usage and last-active fields to a built response."""
    rollup = usage or SessionUsageRollup()
    item.title = title or identity_title(session)
    item.usage_known = rollup.known
    item.usage_input_tokens = rollup.input_tokens
    item.usage_output_tokens = rollup.output_tokens
    item.usage_cached_input_tokens = rollup.cached_input_tokens
    item.last_active_at = session.last_activity_at or session.created_at
    return item


def _agent_breakdown_from_aggregates(
    aggregates: list[AgentTokenAggregate],
) -> tuple[list[AgentTokenBreakdown], int, int]:
    """Same shape and inclusion rule as calculate_agent_token_breakdown."""
    from app.api.schemas.sessions import AgentTokenBreakdown

    total_input = sum(row.input_tokens for row in aggregates)
    total_output = sum(row.output_tokens for row in aggregates)
    breakdown: list[AgentTokenBreakdown] = []
    for row in aggregates:
        agent_id = "default" if row.agent_key == "_default" else row.agent_key
        if agent_id != "default" or len(aggregates) > 1:
            breakdown.append(
                AgentTokenBreakdown(
                    agent_id=agent_id,
                    agent_name=row.agent_name,
                    input_tokens=row.input_tokens,
                    output_tokens=row.output_tokens,
                    total_tokens=row.input_tokens + row.output_tokens,
                    message_count=row.event_count,
                )
            )
    return breakdown, total_input, total_output


async def build_full_session_response(
    db: AsyncSession,
    session: Session,
    *,
    include_events: bool = True,
) -> SessionResponse:
    """Build complete session response with context usage and token breakdown.

    With ``include_events`` the session must have ``events`` loaded and the
    response carries messages. Without it, nothing touches ``session.events``;
    counts and the agent token breakdown come from SQL aggregates.
    """
    # Deferred import to avoid circular import via app.api.__init__
    from app.api.schemas.sessions import ContextUsageResponse

    ctx_usage = await calculate_context_usage(db, session.id, _effective_model(session))
    context_usage_response = ContextUsageResponse(
        used_tokens=ctx_usage.used_tokens,
        limit_tokens=ctx_usage.limit_tokens,
        percent_used=ctx_usage.percent_used,
        remaining_tokens=ctx_usage.remaining_tokens,
        warning=ctx_usage.warning,
        measured=ctx_usage.measured,
    )

    if include_events:
        agent_breakdown, total_input, total_output = calculate_agent_token_breakdown(
            session.events
        )
        agent_names = await _resolve_agent_display_names(db, session.events)
        messages = convert_messages_to_response(session.events, agent_display_names=agent_names)
        message_count = _message_count(session.events)
        event_count = len(session.events)
    else:
        by_type = await fetch_session_event_type_counts(db, session.id)
        message_count = by_type.get(SessionEventType.USER_MESSAGE, 0) + by_type.get(
            SessionEventType.ASSISTANT_MESSAGE, 0
        )
        event_count = sum(by_type.values())
        agent_breakdown, total_input, total_output = _agent_breakdown_from_aggregates(
            await fetch_session_agent_token_aggregates(db, session.id)
        )
        messages = []

    owner_session_ids, specialist_session_ids = await build_project_lane_session_ids(
        db,
        {session.project_id},
    )
    child_result = await db.execute(select(Session).where(Session.parent_session_id == session.id))
    child_sessions = list(child_result.scalars().all())
    child_session_count = len(child_sessions)
    active_child_session_count = sum(
        1 for child_session in child_sessions if is_session_actionably_active(child_session)
    )

    response = build_session_response(
        session,
        messages,
        context_usage_response,
        agent_breakdown,
        total_input,
        total_output,
        message_count=message_count,
        event_count=event_count,
        child_session_count=child_session_count,
        active_child_session_count=active_child_session_count,
        owner_session_ids=owner_session_ids,
        specialist_session_ids=specialist_session_ids,
    )
    titles = await fetch_session_titles(db, [session.id])
    usage = await fetch_session_usage_rollups(db, [session.id])
    apply_session_rollups(
        response,
        session,
        title=titles.get(session.id),
        usage=usage.get(session.id),
    )
    return response


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
            call_id=e.call_id,
            tool_input=e.tool_input,
            tool_output=e.tool_output,
            tokens=e.tokens,
            duration_ms=e.duration_ms,
            model_used=known_model(e.model_used),
            agent_id=e.agent_id,
            agent_name=e.agent_name,
            transport=e.transport,
            surface=e.surface,
            chat_id=e.chat_id,
            message_id=e.message_id,
            pane_id=e.pane_id,
            source_client=e.source_client,
            source_event_id=e.source_event_id,
            source_timestamp=e.source_timestamp,
            usage=e.usage,
            created_at=e.created_at,
        )
        for e in events
    ]
