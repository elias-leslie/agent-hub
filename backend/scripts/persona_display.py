"""Helpers for persona benchmark display-name resolution."""

from __future__ import annotations

from app.db import async_session
from app.services.persona_identity import (
    DEFAULT_PERSONA_DISPLAY_NAME,
    get_persona_display_name,
)


def normalize_persona_name(name: str | None) -> str:
    cleaned = (name or "").strip()
    return cleaned or DEFAULT_PERSONA_DISPLAY_NAME


def persona_possessive(name: str | None) -> str:
    display_name = normalize_persona_name(name)
    return f"{display_name}'" if display_name.endswith("s") else f"{display_name}'s"


async def load_persona_display_name() -> str:
    async with async_session() as db:
        return await get_persona_display_name(db, fallback=DEFAULT_PERSONA_DISPLAY_NAME)
