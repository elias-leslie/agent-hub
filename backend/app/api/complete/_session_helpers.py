"""Private helpers for session_manager: context building, sequencer sync, metadata updates."""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.adapters.base import Message
from app.models import Session as DBSession
from app.models import SessionEventType
from app.services.event_storage import get_sequencer

logger = logging.getLogger(__name__)


def build_context_messages(session: DBSession) -> list[Message]:
    """Extract ordered context messages from session events."""
    return [
        Message(role=e.role, content=e.content)
        for e in sorted(session.events, key=lambda x: (x.turn, x.sequence))
        if e.event_type in (
            SessionEventType.USER_MESSAGE,
            SessionEventType.ASSISTANT_MESSAGE,
            SessionEventType.SYSTEM_MESSAGE,
        )
        and e.role
        and e.content
    ]


def sync_sequencer(session: DBSession) -> None:
    """Synchronize the sequencer state from the session's existing events."""
    max_turn = max((e.turn for e in session.events), default=0)
    if max_turn == 0:
        return
    next_turn = max_turn + 1
    max_seq = max((e.sequence for e in session.events if e.turn == next_turn), default=0)
    get_sequencer().set_turn(session.id, next_turn, max_seq)


async def update_session_metadata(
    db: AsyncSession, session: DBSession, provider: str, model: str, agent_slug: str | None
) -> None:
    """Update models/providers used and agent_slug on an existing session."""
    models_used: list[str] = session.models_used or []
    providers_used: list[str] = session.providers_used or []
    if model not in models_used:
        session.models_used = [*models_used, model]
    if provider not in providers_used:
        session.providers_used = [*providers_used, provider]
    if agent_slug and not session.agent_slug:
        session.agent_slug = agent_slug
    await db.commit()


async def maybe_reset_persona_session(
    db: AsyncSession,
    existing: tuple[DBSession, list[Message], bool],
) -> bool:
    """Return True if the persona session was reset (caller should create a new session)."""
    from app.services.persona_service import should_reset_persona_session

    session, _, _ = existing
    if not await should_reset_persona_session(db, session):
        return False
    session.status = "completed"
    await db.commit()
    logger.info("Persona session %s auto-reset", session.id)
    return True


async def load_session(
    db: AsyncSession, session_id: str, provider: str, model: str, agent_slug: str | None
) -> tuple[DBSession, list[Message], bool] | None:
    """Load an existing session by ID; return None if not found."""
    result = await db.execute(
        select(DBSession).options(selectinload(DBSession.events)).where(DBSession.id == session_id)
    )
    session = result.scalar_one_or_none()
    if session is None:
        return None
    await update_session_metadata(db, session, provider, model, agent_slug)
    sync_sequencer(session)
    return session, build_context_messages(session), False


def _get_prev_total(existing_cache: object, key: str) -> int:
    """Safely extract an integer total from the existing cache metadata dict."""
    if not isinstance(existing_cache, dict):
        return 0
    val = existing_cache.get(key)
    return int(val) if isinstance(val, (int, float)) else 0


def merge_cache_metrics(existing: dict[str, object], metrics: dict[str, int]) -> dict[str, object]:
    """Merge new cache token counts into existing provider metadata cache entry."""
    creation = metrics.get("cache_creation_input_tokens", 0)
    read = metrics.get("cache_read_input_tokens", 0)
    prev = existing.get("cache")
    return {
        **existing,
        "cache": {
            "last_cache_creation_tokens": creation,
            "last_cache_read_tokens": read,
            "total_cache_creation_tokens": _get_prev_total(prev, "total_cache_creation_tokens") + creation,
            "total_cache_read_tokens": _get_prev_total(prev, "total_cache_read_tokens") + read,
        },
    }
