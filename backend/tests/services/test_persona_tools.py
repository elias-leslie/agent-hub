"""Tests for persona tool implementations — shrinkage protection, backups, and validation."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.persona import Persona


def _make_persona(**overrides) -> MagicMock:
    """Create a mock Persona with sensible defaults for testing."""
    defaults = {
        "id": 1,
        "personality": "A" * 300,
        "personality_previous": None,
        "user_context": "B" * 300,
        "user_context_previous": None,
        "heartbeat_instructions": "C" * 300,
        "heartbeat_instructions_previous": None,
        "version": 1,
    }
    defaults.update(overrides)
    persona = MagicMock(spec=Persona)
    for k, v in defaults.items():
        setattr(persona, k, v)
    return persona


def _patch_db_and_persona(persona: MagicMock):
    """Return patch context managers for async_session and get_or_create_persona.

    The functions import these lazily inside the function body, so we patch
    at the source modules (app.db and app.services.persona_service).
    """
    mock_db = AsyncMock()
    mock_db.commit = AsyncMock()

    session_ctx = AsyncMock()
    session_ctx.__aenter__ = AsyncMock(return_value=mock_db)
    session_ctx.__aexit__ = AsyncMock(return_value=False)

    return (
        patch("app.db.async_session", return_value=session_ctx),
        patch(
            "app.services.persona_service.get_or_create_persona",
            return_value=persona,
        ),
        mock_db,
    )


# --- write_user_context ---


class TestWriteUserContext:
    @pytest.mark.asyncio
    async def test_normal_update_succeeds(self):
        """Normal update with similar length succeeds and returns char counts."""
        persona = _make_persona(user_context="B" * 300)
        patch_session, patch_persona, mock_db = _patch_db_and_persona(persona)

        with patch_session, patch_persona:
            from app.services.tools._executor_persona import write_user_context

            result = await write_user_context("B" * 280 + " updated section")

        assert "User context updated" in result
        assert "300" in result  # old char count
        assert persona.user_context_previous == "B" * 300

    @pytest.mark.asyncio
    async def test_empty_string_rejected(self):
        """Empty string is rejected immediately without DB access."""
        from app.services.tools._executor_persona import write_user_context

        result = await write_user_context("")
        assert "Error" in result
        assert "cannot be empty" in result

    @pytest.mark.asyncio
    async def test_whitespace_only_rejected(self):
        """Whitespace-only string is rejected."""
        from app.services.tools._executor_persona import write_user_context

        result = await write_user_context("   \n\t  ")
        assert "Error" in result
        assert "cannot be empty" in result

    @pytest.mark.asyncio
    async def test_shrinkage_rejected(self):
        """50%+ shrinkage is rejected with clear error message."""
        persona = _make_persona(user_context="B" * 500)
        patch_session, patch_persona, mock_db = _patch_db_and_persona(persona)

        with patch_session, patch_persona:
            from app.services.tools._executor_persona import write_user_context

            result = await write_user_context("short garbage")

        assert "REJECTED" in result
        assert "dramatically shorter" in result
        mock_db.commit.assert_not_called()

    @pytest.mark.asyncio
    async def test_previous_context_saved(self):
        """Previous context is saved in user_context_previous before overwrite."""
        old = "Original context " * 20
        new = "Updated context " * 20
        persona = _make_persona(user_context=old)
        patch_session, patch_persona, mock_db = _patch_db_and_persona(persona)

        with patch_session, patch_persona:
            from app.services.tools._executor_persona import write_user_context

            await write_user_context(new)

        assert persona.user_context_previous == old
        assert persona.user_context == new.strip()

    @pytest.mark.asyncio
    async def test_growth_succeeds(self):
        """Adding sections (growth) succeeds — shrinkage check is one-directional."""
        persona = _make_persona(user_context="short")
        patch_session, patch_persona, mock_db = _patch_db_and_persona(persona)

        with patch_session, patch_persona:
            from app.services.tools._executor_persona import write_user_context

            result = await write_user_context("much longer context " * 50)

        assert "User context updated" in result

    @pytest.mark.asyncio
    async def test_small_existing_allows_shrinkage(self):
        """If existing context is small (<= 200 chars), shrinkage is allowed."""
        persona = _make_persona(user_context="A" * 100)
        patch_session, patch_persona, mock_db = _patch_db_and_persona(persona)

        with patch_session, patch_persona:
            from app.services.tools._executor_persona import write_user_context

            result = await write_user_context("tiny")

        assert "User context updated" in result


# --- write_personality ---


class TestWritePersonality:
    @pytest.mark.asyncio
    async def test_normal_update_succeeds(self):
        """Normal personality update with similar length succeeds."""
        persona = _make_persona(personality="P" * 300)
        patch_session, patch_persona, mock_db = _patch_db_and_persona(persona)

        with patch_session, patch_persona:
            from app.services.tools._executor_persona import write_personality

            result = await write_personality("P" * 280 + " new insight", "learned something")

        assert "Personality updated" in result
        assert persona.personality_previous == "P" * 300

    @pytest.mark.asyncio
    async def test_empty_rejected(self):
        """Empty personality is rejected."""
        from app.services.tools._executor_persona import write_personality

        result = await write_personality("", "no reason")
        assert "Error" in result
        assert "cannot be empty" in result

    @pytest.mark.asyncio
    async def test_shrinkage_rejected(self):
        """50%+ shrinkage in personality is rejected."""
        persona = _make_persona(personality="X" * 500)
        patch_session, patch_persona, mock_db = _patch_db_and_persona(persona)

        with patch_session, patch_persona:
            from app.services.tools._executor_persona import write_personality

            result = await write_personality("tiny", "oops")

        assert "REJECTED" in result


# --- write_heartbeat_instructions ---


class TestWriteHeartbeatInstructions:
    @pytest.mark.asyncio
    async def test_normal_update_succeeds(self):
        """Normal heartbeat instructions update succeeds."""
        persona = _make_persona(heartbeat_instructions="H" * 300)
        patch_session, patch_persona, mock_db = _patch_db_and_persona(persona)

        with patch_session, patch_persona:
            from app.services.tools._executor_persona import write_heartbeat_instructions

            result = await write_heartbeat_instructions(
                "H" * 280 + " new check", "discovered better workflow"
            )

        assert "Heartbeat instructions updated" in result
        assert persona.heartbeat_instructions_previous == "H" * 300

    @pytest.mark.asyncio
    async def test_empty_rejected(self):
        """Empty heartbeat instructions rejected."""
        from app.services.tools._executor_persona import write_heartbeat_instructions

        result = await write_heartbeat_instructions("", "no reason")
        assert "Error" in result
        assert "cannot be empty" in result

    @pytest.mark.asyncio
    async def test_shrinkage_rejected(self):
        """50%+ shrinkage in heartbeat instructions is rejected."""
        persona = _make_persona(heartbeat_instructions="Z" * 600)
        patch_session, patch_persona, mock_db = _patch_db_and_persona(persona)

        with patch_session, patch_persona:
            from app.services.tools._executor_persona import write_heartbeat_instructions

            result = await write_heartbeat_instructions("short", "trim")

        assert "REJECTED" in result


# --- VALID_ENTRY_TYPES ---


class TestValidEntryTypes:
    def test_evolution_entry_type_valid(self):
        """The 'evolution' entry type is valid."""
        from app.services.tools._executor_persona import VALID_ENTRY_TYPES

        assert "evolution" in VALID_ENTRY_TYPES

    def test_all_expected_types_present(self):
        """All expected entry types are present."""
        from app.services.tools._executor_persona import VALID_ENTRY_TYPES

        expected = {"observation", "decision", "learning", "user_insight", "evolution"}
        assert VALID_ENTRY_TYPES == expected
