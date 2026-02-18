"""Session management for completion API."""

from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.adapters.base import Message
from app.models import Session as DBSession
from app.models import SessionEventType
from app.services.event_storage import get_sequencer

logger = logging.getLogger(__name__)


def _build_context_messages(session: DBSession) -> list[Message]:
    """Extract ordered context messages from session events."""
    return [
        Message(role=e.role, content=e.content)
        for e in sorted(session.events, key=lambda x: (x.turn, x.sequence))
        if e.event_type
        in (
            SessionEventType.USER_MESSAGE,
            SessionEventType.ASSISTANT_MESSAGE,
            SessionEventType.SYSTEM_MESSAGE,
        )
        and e.role
        and e.content
    ]


def _sync_sequencer_from_events(session: DBSession) -> None:
    """Synchronize the sequencer state from the session's existing events."""
    max_turn = max((e.turn for e in session.events), default=0)
    if max_turn > 0:
        next_turn = max_turn + 1
        max_seq_at_next = max(
            (e.sequence for e in session.events if e.turn == next_turn),
            default=0,
        )
        get_sequencer().set_turn(session.id, next_turn, max_seq_at_next)


async def _update_session_metadata(
    db: AsyncSession,
    session: DBSession,
    provider: str,
    model: str,
    agent_slug: str | None,
) -> None:
    """Update models/providers used and agent_slug on an existing session."""
    models_used = session.models_used or []
    providers_used = session.providers_used or []
    if model not in models_used:
        models_used.append(model)
        session.models_used = models_used
    if provider not in providers_used:
        providers_used.append(provider)
        session.providers_used = providers_used
    if agent_slug and not session.agent_slug:
        session.agent_slug = agent_slug
    await db.commit()


async def _load_existing_session(
    db: AsyncSession,
    session_id: str,
    provider: str,
    model: str,
    agent_slug: str | None,
) -> tuple[DBSession, list[Message], bool] | None:
    """Load an existing session by ID and return (session, messages, is_new).

    Returns None if no session is found for the given session_id.
    """
    result = await db.execute(
        select(DBSession)
        .options(selectinload(DBSession.events))
        .where(DBSession.id == session_id)
    )
    session = result.scalar_one_or_none()
    if session is None:
        return None

    await _update_session_metadata(db, session, provider, model, agent_slug)
    context_messages = _build_context_messages(session)
    _sync_sequencer_from_events(session)
    return session, context_messages, False


async def _create_new_session(
    db: AsyncSession,
    session_id: str | None,
    project_id: str,
    provider: str,
    model: str,
    session_type: str,
    external_id: str | None,
    client_id: str | None,
    request_source: str | None,
    agent_slug: str | None,
    current_branch: str | None,
) -> tuple[DBSession, list[Message], bool]:
    """Create and persist a new session, returning (session, [], True)."""
    new_session_id = session_id or str(uuid.uuid4())
    session = DBSession(
        id=new_session_id,
        project_id=project_id,
        provider=provider,
        model=model,
        status="active",
        session_type=session_type,
        external_id=external_id,
        client_id=client_id,
        request_source=request_source,
        agent_slug=agent_slug,
        current_branch=current_branch,
        models_used=[model],
        providers_used=[provider],
    )
    db.add(session)
    await db.commit()
    await db.refresh(session)
    return session, [], True


async def get_or_create_session(
    db: AsyncSession,
    session_id: str | None,
    project_id: str,
    provider: str,
    model: str,
    session_type: str = "completion",
    external_id: str | None = None,
    client_id: str | None = None,
    request_source: str | None = None,
    agent_slug: str | None = None,
    current_branch: str | None = None,
) -> tuple[DBSession, list[Message], bool]:
    """Get existing session or create new one. Returns (session, messages, is_new)."""
    from app.constants import VALID_PROJECT_IDS

    if project_id not in VALID_PROJECT_IDS:
        raise ValueError(
            f"Unknown project_id '{project_id}'. "
            f"Valid projects: {sorted(VALID_PROJECT_IDS)}"
        )

    if session_id:
        existing = await _load_existing_session(
            db, session_id, provider, model, agent_slug
        )
        if existing is not None:
            return existing

    return await _create_new_session(
        db,
        session_id,
        project_id,
        provider,
        model,
        session_type,
        external_id,
        client_id,
        request_source,
        agent_slug,
        current_branch,
    )


async def update_provider_metadata(
    db: AsyncSession,
    session: DBSession,
    cache_metrics: dict[str, Any] | None,
) -> None:
    """Update session with provider-specific metadata like cache info."""
    if not cache_metrics:
        return

    # Merge with existing metadata
    existing = session.provider_metadata or {}
    existing["cache"] = {
        "last_cache_creation_tokens": cache_metrics.get("cache_creation_input_tokens", 0),
        "last_cache_read_tokens": cache_metrics.get("cache_read_input_tokens", 0),
        "total_cache_creation_tokens": existing.get("cache", {}).get(
            "total_cache_creation_tokens", 0
        )
        + cache_metrics.get("cache_creation_input_tokens", 0),
        "total_cache_read_tokens": existing.get("cache", {}).get("total_cache_read_tokens", 0)
        + cache_metrics.get("cache_read_input_tokens", 0),
    }
    session.provider_metadata = existing
    await db.commit()
