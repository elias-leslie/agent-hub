"""Tests for persona_service.py — singleton fetch, context building, and creation."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.persona import Persona
from app.models.persona_journal import PersonaJournal
from app.services.persona_service import (
    get_or_create_persona,
    get_persona,
    get_persona_context_for_agent,
    get_persona_for_agent,
    get_persona_personality_for_agent,
)
from tests.conftest import create_mock_db_session


def _make_persona(**overrides) -> MagicMock:
    """Create a mock Persona with sensible defaults for testing."""
    defaults = {
        "id": 1,
        "agent_id": 10,
        "name": "Jenny",
        "personality": "I am a helpful assistant.",
        "heartbeat_instructions": "Check system health.",
        "user_context": "User prefers concise answers.",
        "tools_guidance": "Use tools sparingly.",
        "voice_id": "en-US-AriaNeural",
        "voice_enabled": False,
        "heartbeat_interval_minutes": 60,
        "avatar_url": None,
        "greeting": "Hello!",
        "onboarding_complete": True,
        "version": 3,
        "created_at": datetime.now(UTC),
        "updated_at": datetime.now(UTC),
    }
    defaults.update(overrides)
    mock = MagicMock(spec=Persona)
    for k, v in defaults.items():
        setattr(mock, k, v)
    return mock


def _make_journal_entry(**overrides) -> MagicMock:
    """Create a mock PersonaJournal for testing."""
    defaults = {
        "id": 1,
        "persona_id": 1,
        "entry_date": date.today(),
        "content": "Observed user prefers dark mode.",
        "entry_type": "observation",
        "created_at": datetime.now(UTC),
        "updated_at": datetime.now(UTC),
    }
    defaults.update(overrides)
    mock = MagicMock(spec=PersonaJournal)
    for k, v in defaults.items():
        setattr(mock, k, v)
    return mock


class TestGetPersona:
    """Tests for get_persona() — singleton fetch."""

    @pytest.mark.asyncio
    async def test_returns_persona_when_exists(self):
        persona = _make_persona()
        db = create_mock_db_session()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = persona
        db.execute.return_value = mock_result

        result = await get_persona(db)

        assert result is persona
        assert result.name == "Jenny"

    @pytest.mark.asyncio
    async def test_returns_none_when_empty(self):
        db = create_mock_db_session()

        result = await get_persona(db)

        assert result is None


class TestGetPersonaForAgent:
    """Tests for get_persona_for_agent() — match by agent_id."""

    @pytest.mark.asyncio
    async def test_returns_persona_matching_agent(self):
        persona = _make_persona(agent_id=42)
        db = create_mock_db_session()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = persona
        db.execute.return_value = mock_result

        result = await get_persona_for_agent(db, agent_id=42)

        assert result is persona
        assert result.agent_id == 42

    @pytest.mark.asyncio
    async def test_returns_none_when_no_match(self):
        db = create_mock_db_session()

        result = await get_persona_for_agent(db, agent_id=999)

        assert result is None


class TestGetPersonaPersonalityForAgent:
    """Tests for get_persona_personality_for_agent()."""

    @pytest.mark.asyncio
    async def test_returns_personality_text(self):
        persona = _make_persona(personality="I'm a creative coder.")
        db = create_mock_db_session()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = persona
        db.execute.return_value = mock_result

        result = await get_persona_personality_for_agent(db, agent_id=10)

        assert result == "I'm a creative coder."

    @pytest.mark.asyncio
    async def test_returns_none_when_no_persona(self):
        db = create_mock_db_session()

        result = await get_persona_personality_for_agent(db, agent_id=999)

        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_when_personality_is_null(self):
        persona = _make_persona(personality=None)
        db = create_mock_db_session()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = persona
        db.execute.return_value = mock_result

        result = await get_persona_personality_for_agent(db, agent_id=10)

        assert result is None


class TestGetPersonaContextForAgent:
    """Tests for get_persona_context_for_agent() — core context injection."""

    @pytest.mark.asyncio
    async def test_identity_tag_always_present(self):
        persona = _make_persona(
            personality=None,
            heartbeat_instructions=None,
            user_context=None,
            tools_guidance=None,
        )
        db = create_mock_db_session()
        # First call returns persona, second call returns empty journal
        mock_result_persona = MagicMock()
        mock_result_persona.scalar_one_or_none.return_value = persona
        mock_result_journal = MagicMock()
        mock_result_journal.scalars.return_value.all.return_value = []
        db.execute.side_effect = [mock_result_persona, mock_result_journal]

        result = await get_persona_context_for_agent(db, agent_id=10)

        assert result is not None
        assert '<identity name="Jenny" />' in result

    @pytest.mark.asyncio
    async def test_personality_section_present_when_set(self):
        persona = _make_persona(personality="I love coding.")
        db = create_mock_db_session()
        mock_result_persona = MagicMock()
        mock_result_persona.scalar_one_or_none.return_value = persona
        mock_result_journal = MagicMock()
        mock_result_journal.scalars.return_value.all.return_value = []
        db.execute.side_effect = [mock_result_persona, mock_result_journal]

        result = await get_persona_context_for_agent(db, agent_id=10)

        assert "<personality>" in result
        assert "I love coding." in result

    @pytest.mark.asyncio
    async def test_personality_section_absent_when_null(self):
        persona = _make_persona(personality=None)
        db = create_mock_db_session()
        mock_result_persona = MagicMock()
        mock_result_persona.scalar_one_or_none.return_value = persona
        mock_result_journal = MagicMock()
        mock_result_journal.scalars.return_value.all.return_value = []
        db.execute.side_effect = [mock_result_persona, mock_result_journal]

        result = await get_persona_context_for_agent(db, agent_id=10)

        assert "<personality>" not in result

    @pytest.mark.asyncio
    async def test_heartbeat_instructions_present_when_set(self):
        persona = _make_persona(heartbeat_instructions="Check task queue.")
        db = create_mock_db_session()
        mock_result_persona = MagicMock()
        mock_result_persona.scalar_one_or_none.return_value = persona
        mock_result_journal = MagicMock()
        mock_result_journal.scalars.return_value.all.return_value = []
        db.execute.side_effect = [mock_result_persona, mock_result_journal]

        result = await get_persona_context_for_agent(db, agent_id=10)

        assert "<heartbeat_instructions>" in result
        assert "Check task queue." in result

    @pytest.mark.asyncio
    async def test_heartbeat_instructions_absent_when_null(self):
        persona = _make_persona(heartbeat_instructions=None)
        db = create_mock_db_session()
        mock_result_persona = MagicMock()
        mock_result_persona.scalar_one_or_none.return_value = persona
        mock_result_journal = MagicMock()
        mock_result_journal.scalars.return_value.all.return_value = []
        db.execute.side_effect = [mock_result_persona, mock_result_journal]

        result = await get_persona_context_for_agent(db, agent_id=10)

        assert "<heartbeat_instructions>" not in result

    @pytest.mark.asyncio
    async def test_user_context_present_when_set(self):
        persona = _make_persona(user_context="Prefers dark mode.")
        db = create_mock_db_session()
        mock_result_persona = MagicMock()
        mock_result_persona.scalar_one_or_none.return_value = persona
        mock_result_journal = MagicMock()
        mock_result_journal.scalars.return_value.all.return_value = []
        db.execute.side_effect = [mock_result_persona, mock_result_journal]

        result = await get_persona_context_for_agent(db, agent_id=10)

        assert "<user_context>" in result
        assert "Prefers dark mode." in result

    @pytest.mark.asyncio
    async def test_tools_guidance_present_when_set(self):
        persona = _make_persona(tools_guidance="Be careful with tools.")
        db = create_mock_db_session()
        mock_result_persona = MagicMock()
        mock_result_persona.scalar_one_or_none.return_value = persona
        mock_result_journal = MagicMock()
        mock_result_journal.scalars.return_value.all.return_value = []
        db.execute.side_effect = [mock_result_persona, mock_result_journal]

        result = await get_persona_context_for_agent(db, agent_id=10)

        assert "<tools_guidance>" in result
        assert "Be careful with tools." in result

    @pytest.mark.asyncio
    async def test_journal_entries_included_within_7_days(self):
        persona = _make_persona()
        entry = _make_journal_entry(
            entry_date=date.today() - timedelta(days=2),
            content="User asked about dark mode.",
            entry_type="user_insight",
        )
        db = create_mock_db_session()
        mock_result_persona = MagicMock()
        mock_result_persona.scalar_one_or_none.return_value = persona
        mock_result_journal = MagicMock()
        mock_result_journal.scalars.return_value.all.return_value = [entry]
        db.execute.side_effect = [mock_result_persona, mock_result_journal]

        result = await get_persona_context_for_agent(db, agent_id=10)

        assert "<recent_journal>" in result
        assert "User asked about dark mode." in result
        assert "[user_insight]" in result

    @pytest.mark.asyncio
    async def test_old_journal_entries_excluded(self):
        """Entries older than journal_days should not appear (mocked at query level)."""
        persona = _make_persona()
        db = create_mock_db_session()
        mock_result_persona = MagicMock()
        mock_result_persona.scalar_one_or_none.return_value = persona
        # Simulate the DB returning no results for old entries
        mock_result_journal = MagicMock()
        mock_result_journal.scalars.return_value.all.return_value = []
        db.execute.side_effect = [mock_result_persona, mock_result_journal]

        result = await get_persona_context_for_agent(db, agent_id=10, journal_days=7)

        assert "<recent_journal>" not in result

    @pytest.mark.asyncio
    async def test_evolution_guidelines_always_present(self):
        persona = _make_persona(
            personality=None,
            heartbeat_instructions=None,
            user_context=None,
            tools_guidance=None,
        )
        db = create_mock_db_session()
        mock_result_persona = MagicMock()
        mock_result_persona.scalar_one_or_none.return_value = persona
        mock_result_journal = MagicMock()
        mock_result_journal.scalars.return_value.all.return_value = []
        db.execute.side_effect = [mock_result_persona, mock_result_journal]

        result = await get_persona_context_for_agent(db, agent_id=10)

        assert "<evolution_guidelines>" in result
        assert "Self-Evolution Guidelines" in result

    @pytest.mark.asyncio
    async def test_onboarding_bootstrap_injected_when_not_complete(self):
        persona = _make_persona(onboarding_complete=False)
        db = create_mock_db_session()
        mock_result_persona = MagicMock()
        mock_result_persona.scalar_one_or_none.return_value = persona
        mock_result_journal = MagicMock()
        mock_result_journal.scalars.return_value.all.return_value = []
        db.execute.side_effect = [mock_result_persona, mock_result_journal]

        result = await get_persona_context_for_agent(db, agent_id=10)

        assert "<onboarding>" in result
        assert "First Interaction Bootstrap" in result
        # Should mark onboarding complete
        assert persona.onboarding_complete is True

    @pytest.mark.asyncio
    async def test_onboarding_bootstrap_skipped_when_complete(self):
        persona = _make_persona(onboarding_complete=True)
        db = create_mock_db_session()
        mock_result_persona = MagicMock()
        mock_result_persona.scalar_one_or_none.return_value = persona
        mock_result_journal = MagicMock()
        mock_result_journal.scalars.return_value.all.return_value = []
        db.execute.side_effect = [mock_result_persona, mock_result_journal]

        result = await get_persona_context_for_agent(db, agent_id=10)

        assert "<onboarding>" not in result

    @pytest.mark.asyncio
    async def test_returns_none_when_no_persona(self):
        db = create_mock_db_session()

        result = await get_persona_context_for_agent(db, agent_id=999)

        assert result is None


class TestGetOrCreatePersona:
    """Tests for get_or_create_persona() — singleton creation."""

    @pytest.mark.asyncio
    async def test_returns_existing_persona(self):
        persona = _make_persona()
        db = create_mock_db_session()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = persona
        db.execute.return_value = mock_result

        result = await get_or_create_persona(db)

        assert result is persona

    @pytest.mark.asyncio
    async def test_creates_default_when_missing(self):
        db = create_mock_db_session()

        mock_agent = MagicMock()
        mock_agent.id = 10
        mock_agent.name = "Jenny"
        mock_agent.slug = "persona"

        with patch("app.services.agent_service.get_agent_service") as mock_get_svc:
            mock_svc = MagicMock()
            mock_svc.get_by_slug = AsyncMock(return_value=mock_agent)
            mock_get_svc.return_value = mock_svc

            result = await get_or_create_persona(db)

            assert isinstance(result, Persona)
            assert result.agent_id == 10
            db.add.assert_called_once()
            db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_raises_when_no_agent(self):
        db = create_mock_db_session()

        with patch("app.services.agent_service.get_agent_service") as mock_get_svc:
            mock_svc = MagicMock()
            mock_svc.get_by_slug = AsyncMock(return_value=None)
            mock_get_svc.return_value = mock_svc

            with pytest.raises(RuntimeError, match="Persona agent not found"):
                await get_or_create_persona(db)
