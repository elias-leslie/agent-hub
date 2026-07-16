"""Persona CRUD helpers — query and session-reset logic."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.persona import Persona

logger = logging.getLogger(__name__)

# Default limits — only max_turns is user-configurable.
DEFAULT_LIMITS: dict[str, int] = {
    "max_turns": 500,
}


def get_persona_limit(persona: Persona | None, key: str) -> int:
    """Get a configurable limit, falling back to defaults."""
    default = DEFAULT_LIMITS.get(key, 0)
    if persona and persona.limits and key in persona.limits:
        raw_value = persona.limits[key]
        try:
            value = int(raw_value)
        except (TypeError, ValueError):
            return default
        if key == "max_turns" and value < 1:
            return default
        return value
    return default


async def get_persona(db: AsyncSession) -> Persona | None:
    """Get the singleton persona row (there's only one)."""
    result = await db.execute(select(Persona).limit(1))
    return result.scalar_one_or_none()


async def get_persona_for_agent(db: AsyncSession, agent_id: int) -> Persona | None:
    """Get persona for a specific agent ID."""
    result = await db.execute(select(Persona).where(Persona.agent_id == agent_id))
    return result.scalar_one_or_none()


async def get_persona_personality_for_agent(db: AsyncSession, agent_id: int) -> str | None:
    """Get just the personality text for an agent's persona."""
    persona = await get_persona_for_agent(db, agent_id)
    if not persona:
        return None
    personality = (persona.personality or "").strip()
    return personality or None


def _compute_daily_reset_time(now: datetime, reset_hour: int) -> datetime:
    """Return the most recent daily reset datetime for the given hour."""
    reset_time = now.replace(hour=reset_hour, minute=0, second=0, microsecond=0)
    if now < reset_time:
        reset_time -= timedelta(days=1)
    return reset_time


async def should_reset_persona_session(db: AsyncSession, session: object) -> bool:
    """Return True if the persona session should be closed and a new one created."""
    persona = await get_persona(db)
    if not persona or persona.session_reset_mode == "off":
        return False

    session_updated = None
    session_dict = getattr(session, "__dict__", None)
    if isinstance(session_dict, dict):
        session_updated = session_dict.get("updated_at")
    if session_updated is None:
        session_id = getattr(session, "id", None)
        if session_id:
            from app.models.session import Session

            result = await db.execute(select(Session.updated_at).where(Session.id == session_id))
            session_updated = result.scalar_one_or_none()
    if not session_updated:
        return False

    if session_updated.tzinfo is None:
        session_updated = session_updated.replace(tzinfo=UTC)

    now = datetime.now(UTC)

    if persona.session_reset_mode == "daily":
        reset_time = _compute_daily_reset_time(now, persona.session_reset_hour)
        return session_updated < reset_time

    if persona.session_reset_mode == "idle":
        elapsed_minutes = (now - session_updated).total_seconds() / 60
        return elapsed_minutes >= persona.session_reset_idle_minutes

    return False
