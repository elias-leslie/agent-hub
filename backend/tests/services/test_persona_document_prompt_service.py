"""Tests for canonical persona-row identity and state documents."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.models.persona import Persona
from app.services.persona_document_prompt_service import (
    clear_persona_user_context_document,
    get_persona_personality_document,
    get_persona_user_context_document,
    set_persona_personality_document,
    set_persona_user_context_document,
)
from tests.conftest import create_mock_db_session


def _persona(**values: object) -> MagicMock:
    persona = MagicMock(spec=Persona)
    defaults: dict[str, object | None] = {
        "personality": "Direct and concise.",
        "personality_previous": None,
        "user_context": "Current workspace state.",
        "user_context_previous": None,
    }
    defaults.update(values)
    for key, value in defaults.items():
        setattr(persona, key, value)
    return persona


def _db_with_persona(persona: MagicMock):
    db = create_mock_db_session()
    result = MagicMock()
    result.scalar_one_or_none.return_value = persona
    db.execute.return_value = result
    return db


class TestPersonaRowDocuments:
    @pytest.mark.asyncio
    async def test_getters_read_persona_row(self) -> None:
        persona = _persona()
        db = _db_with_persona(persona)

        assert await get_persona_personality_document(db) == "Direct and concise."
        assert await get_persona_user_context_document(db) == "Current workspace state."

    @pytest.mark.asyncio
    async def test_personality_update_preserves_previous_value(self) -> None:
        persona = _persona()
        db = _db_with_persona(persona)

        old_len, new_len = await set_persona_personality_document(db, "Warm but direct.")

        assert (old_len, new_len) == (len("Direct and concise."), len("Warm but direct."))
        assert persona.personality_previous == "Direct and concise."
        assert persona.personality == "Warm but direct."
        db.flush.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_user_context_update_and_clear_preserve_previous_value(self) -> None:
        persona = _persona()
        db = _db_with_persona(persona)

        await set_persona_user_context_document(db, "New operator state.")
        assert persona.user_context_previous == "Current workspace state."
        assert persona.user_context == "New operator state."

        await clear_persona_user_context_document(db)
        assert persona.user_context_previous == "New operator state."
        assert persona.user_context is None
        assert db.flush.await_count == 2
