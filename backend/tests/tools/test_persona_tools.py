"""Tests for persona tool handlers in direct_executor_core.py."""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, date, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.persona import Persona
from app.models.persona_journal import PersonaJournal
from app.services.tools.direct_executor_core import DirectToolExecutor


def _make_persona(**overrides) -> MagicMock:
    """Create a mock Persona with sensible defaults."""
    defaults = {
        "id": 1,
        "agent_id": 10,
        "name": "Jenny",
        "personality": "I'm a helpful assistant.",
        "heartbeat_instructions": None,
        "user_context": "User prefers concise answers.",
        "tools_guidance": None,
        "voice_id": "en-US-AriaNeural",
        "voice_enabled": False,
        "heartbeat_interval_minutes": 60,
        "avatar_url": None,
        "greeting": None,
        "onboarding_complete": True,
        "version": 2,
        "created_at": datetime.now(UTC),
        "updated_at": datetime.now(UTC),
    }
    defaults.update(overrides)
    mock = MagicMock(spec=Persona)
    for k, v in defaults.items():
        setattr(mock, k, v)
    return mock


def _make_journal(**overrides) -> MagicMock:
    """Create a mock PersonaJournal for testing."""
    defaults = {
        "id": 1,
        "persona_id": 1,
        "entry_date": date.today(),
        "content": "Observed user preference.",
        "entry_type": "observation",
        "created_at": datetime.now(UTC),
        "updated_at": datetime.now(UTC),
    }
    defaults.update(overrides)
    mock = MagicMock(spec=PersonaJournal)
    for k, v in defaults.items():
        setattr(mock, k, v)
    return mock


def _make_executor() -> DirectToolExecutor:
    """Create a DirectToolExecutor with minimal config."""
    return DirectToolExecutor(
        project_id="test-project",
    )


def _mock_async_session(persona, journal_entries=None):
    """Create a mock async_session context manager that returns a mock db.

    When get_or_create_persona is separately patched, execute is only called
    for the journal query (not the persona lookup).
    """
    mock_db = AsyncMock()

    if journal_entries is not None:
        # Only the journal query goes through execute (persona is separately patched)
        mock_result_journal = MagicMock()
        mock_result_journal.scalars.return_value.all.return_value = journal_entries
        mock_db.execute.return_value = mock_result_journal
    else:
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = persona
        mock_db.execute.return_value = mock_result

    mock_db.add = MagicMock()
    mock_db.commit = AsyncMock()
    mock_db.refresh = AsyncMock()

    @asynccontextmanager
    async def _session():
        yield mock_db

    return _session, mock_db


class TestReadPersonality:
    """Tests for read_personality tool."""

    @pytest.mark.asyncio
    async def test_returns_personality_text(self):
        executor = _make_executor()
        persona = _make_persona(personality="I'm creative and bold.")
        session_fn, _ = _mock_async_session(persona)

        with (
            patch("app.db.async_session", session_fn),
            patch(
                "app.services.persona_service.get_or_create_persona",
                new_callable=AsyncMock,
                return_value=persona,
            ),
        ):
            result = await executor.read_personality()

        assert result == "I'm creative and bold."

    @pytest.mark.asyncio
    async def test_returns_placeholder_when_empty(self):
        executor = _make_executor()
        persona = _make_persona(personality=None)
        session_fn, _ = _mock_async_session(persona)

        with (
            patch("app.db.async_session", session_fn),
            patch(
                "app.services.persona_service.get_or_create_persona",
                new_callable=AsyncMock,
                return_value=persona,
            ),
        ):
            result = await executor.read_personality()

        assert "No personality document set" in result


class TestWritePersonality:
    """Tests for write_personality tool."""

    @pytest.mark.asyncio
    async def test_updates_personality_and_version(self):
        executor = _make_executor()
        persona = _make_persona(version=3)
        session_fn, _ = _mock_async_session(persona)

        with (
            patch("app.db.async_session", session_fn),
            patch(
                "app.services.persona_service.get_or_create_persona",
                new_callable=AsyncMock,
                return_value=persona,
            ),
        ):
            result = await executor.write_personality("New personality.", "Testing")

        assert "Personality updated" in result
        assert "version 4" in result
        assert persona.personality == "New personality."
        assert persona.version == 4


class TestWriteJournal:
    """Tests for write_journal tool."""

    @pytest.mark.asyncio
    async def test_creates_entry(self):
        executor = _make_executor()
        persona = _make_persona()
        session_fn, _ = _mock_async_session(persona)

        with (
            patch("app.db.async_session", session_fn),
            patch(
                "app.services.persona_service.get_or_create_persona",
                new_callable=AsyncMock,
                return_value=persona,
            ),
        ):
            result = await executor.write_journal("Learned something.", "learning")

        assert "Journal entry recorded" in result
        assert "learning" in result

    @pytest.mark.asyncio
    async def test_default_type_is_observation(self):
        executor = _make_executor()
        persona = _make_persona()
        session_fn, _ = _mock_async_session(persona)

        with (
            patch("app.db.async_session", session_fn),
            patch(
                "app.services.persona_service.get_or_create_persona",
                new_callable=AsyncMock,
                return_value=persona,
            ),
        ):
            result = await executor.write_journal("Something happened.")

        assert "observation" in result

    @pytest.mark.asyncio
    async def test_invalid_entry_type_rejected(self):
        executor = _make_executor()
        result = await executor.write_journal("Bad entry.", "nonsense")

        assert "Invalid entry_type" in result
        assert "nonsense" in result
        assert "observation" in result

    @pytest.mark.asyncio
    async def test_all_valid_entry_types_accepted(self):
        executor = _make_executor()
        persona = _make_persona()

        for entry_type in ["observation", "decision", "learning", "user_insight"]:
            session_fn, _ = _mock_async_session(persona)
            with (
                patch("app.db.async_session", session_fn),
                patch(
                    "app.services.persona_service.get_or_create_persona",
                    new_callable=AsyncMock,
                    return_value=persona,
                ),
            ):
                result = await executor.write_journal("Test.", entry_type)
                assert "Journal entry recorded" in result


class TestReadJournal:
    """Tests for read_journal tool."""

    @pytest.mark.asyncio
    async def test_returns_formatted_entries(self):
        executor = _make_executor()
        persona = _make_persona()
        entry = _make_journal(
            entry_date=date.today(),
            content="Dark mode preferred.",
            entry_type="user_insight",
        )
        session_fn, _ = _mock_async_session(persona, journal_entries=[entry])

        with (
            patch("app.db.async_session", session_fn),
            patch(
                "app.services.persona_service.get_or_create_persona",
                new_callable=AsyncMock,
                return_value=persona,
            ),
        ):
            result = await executor.read_journal()

        assert "Dark mode preferred." in result
        assert "[user_insight]" in result

    @pytest.mark.asyncio
    async def test_empty_journal(self):
        executor = _make_executor()
        persona = _make_persona()
        session_fn, _ = _mock_async_session(persona, journal_entries=[])

        with (
            patch("app.db.async_session", session_fn),
            patch(
                "app.services.persona_service.get_or_create_persona",
                new_callable=AsyncMock,
                return_value=persona,
            ),
        ):
            result = await executor.read_journal()

        assert "No journal entries" in result

    @pytest.mark.asyncio
    async def test_custom_days_back(self):
        executor = _make_executor()
        persona = _make_persona()
        session_fn, _ = _mock_async_session(persona, journal_entries=[])

        with (
            patch("app.db.async_session", session_fn),
            patch(
                "app.services.persona_service.get_or_create_persona",
                new_callable=AsyncMock,
                return_value=persona,
            ),
        ):
            result = await executor.read_journal(days_back=30)

        assert "No journal entries in the last 30 days" in result


class TestSearchJournal:
    """Tests for search_journal tool."""

    @pytest.mark.asyncio
    async def test_returns_matching_entries(self):
        executor = _make_executor()
        persona = _make_persona()
        entry = _make_journal(content="Found a dark mode bug.", entry_type="observation")
        session_fn, _ = _mock_async_session(persona, journal_entries=[entry])

        with (
            patch("app.db.async_session", session_fn),
            patch(
                "app.services.persona_service.get_or_create_persona",
                new_callable=AsyncMock,
                return_value=persona,
            ),
        ):
            result = await executor.search_journal("dark mode")

        assert "dark mode bug" in result

    @pytest.mark.asyncio
    async def test_no_matches(self):
        executor = _make_executor()
        persona = _make_persona()
        session_fn, _ = _mock_async_session(persona, journal_entries=[])

        with (
            patch("app.db.async_session", session_fn),
            patch(
                "app.services.persona_service.get_or_create_persona",
                new_callable=AsyncMock,
                return_value=persona,
            ),
        ):
            result = await executor.search_journal("nonexistent")

        assert "No journal entries matching" in result


class TestWriteUserContext:
    """Tests for write_user_context tool."""

    @pytest.mark.asyncio
    async def test_updates_user_context(self):
        executor = _make_executor()
        persona = _make_persona(version=2)
        session_fn, _ = _mock_async_session(persona)

        with (
            patch("app.db.async_session", session_fn),
            patch(
                "app.services.persona_service.get_or_create_persona",
                new_callable=AsyncMock,
                return_value=persona,
            ),
        ):
            result = await executor.write_user_context("Prefers morning standups.")

        assert "User context updated" in result
        assert persona.user_context == "Prefers morning standups."
        assert persona.version == 3


class TestReadUserContext:
    """Tests for read_user_context tool."""

    @pytest.mark.asyncio
    async def test_returns_context_text(self):
        executor = _make_executor()
        persona = _make_persona(user_context="Likes verbose output.")
        session_fn, _ = _mock_async_session(persona)

        with (
            patch("app.db.async_session", session_fn),
            patch(
                "app.services.persona_service.get_or_create_persona",
                new_callable=AsyncMock,
                return_value=persona,
            ),
        ):
            result = await executor.read_user_context()

        assert result == "Likes verbose output."

    @pytest.mark.asyncio
    async def test_returns_placeholder_when_empty(self):
        executor = _make_executor()
        persona = _make_persona(user_context=None)
        session_fn, _ = _mock_async_session(persona)

        with (
            patch("app.db.async_session", session_fn),
            patch(
                "app.services.persona_service.get_or_create_persona",
                new_callable=AsyncMock,
                return_value=persona,
            ),
        ):
            result = await executor.read_user_context()

        assert "No user context set" in result


class TestMarkMemoryRelevant:
    """Tests for mark_memory_relevant tool."""

    @pytest.mark.asyncio
    async def test_adds_tag(self):
        executor = _make_executor()
        with (
            patch(
                "app.services.memory.episode_property_queries.get_episode_tags",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch(
                "app.services.memory.episode_property_setters.set_episode_tags",
                new_callable=AsyncMock,
                return_value=True,
            ) as mock_set,
        ):
            result = await executor.mark_memory_relevant("abc12345-uuid")

        assert "marked as persona-relevant" in result
        mock_set.assert_awaited_once_with("abc12345-uuid", ["persona-relevant"])

    @pytest.mark.asyncio
    async def test_idempotent_when_already_tagged(self):
        executor = _make_executor()
        with patch(
            "app.services.memory.episode_property_queries.get_episode_tags",
            new_callable=AsyncMock,
            return_value=["persona-relevant"],
        ):
            result = await executor.mark_memory_relevant("abc12345-uuid")

        assert "already tagged" in result

    @pytest.mark.asyncio
    async def test_error_handling(self):
        executor = _make_executor()
        with patch(
            "app.services.memory.episode_property_queries.get_episode_tags",
            new_callable=AsyncMock,
            side_effect=Exception("Neo4j down"),
        ):
            result = await executor.mark_memory_relevant("bad-uuid")

        assert "Error" in result


class TestMarkMemoryIrrelevant:
    """Tests for mark_memory_irrelevant tool."""

    @pytest.mark.asyncio
    async def test_removes_tag(self):
        executor = _make_executor()
        with (
            patch(
                "app.services.memory.episode_property_queries.get_episode_tags",
                new_callable=AsyncMock,
                return_value=["persona-relevant", "other-tag"],
            ),
            patch(
                "app.services.memory.episode_property_setters.set_episode_tags",
                new_callable=AsyncMock,
                return_value=True,
            ) as mock_set,
        ):
            result = await executor.mark_memory_irrelevant("abc12345-uuid")

        assert "Removed persona-relevant" in result
        mock_set.assert_awaited_once_with("abc12345-uuid", ["other-tag"])

    @pytest.mark.asyncio
    async def test_idempotent_when_not_tagged(self):
        executor = _make_executor()
        with patch(
            "app.services.memory.episode_property_queries.get_episode_tags",
            new_callable=AsyncMock,
            return_value=["other-tag"],
        ):
            result = await executor.mark_memory_irrelevant("abc12345-uuid")

        assert "not tagged as persona-relevant" in result

    @pytest.mark.asyncio
    async def test_error_handling(self):
        executor = _make_executor()
        with patch(
            "app.services.memory.episode_property_queries.get_episode_tags",
            new_callable=AsyncMock,
            side_effect=Exception("Connection lost"),
        ):
            result = await executor.mark_memory_irrelevant("bad-uuid")

        assert "Error" in result


class TestSendPush:
    """Tests for send_push tool."""

    @pytest.mark.asyncio
    async def test_sends_notification(self):
        executor = _make_executor()
        mock_db = AsyncMock()

        @asynccontextmanager
        async def _session():
            yield mock_db

        with (
            patch("app.db.async_session", _session),
            patch(
                "app.services.push_service.send_push",
                new_callable=AsyncMock,
                return_value=3,
            ),
        ):
            result = await executor.send_push(
                title="Alert",
                body="Something happened",
                url="https://example.com",
                severity="warning",
                tag="test-tag",
            )

        assert "3 device(s)" in result
        assert "Alert" in result

    @pytest.mark.asyncio
    async def test_sends_with_minimal_params(self):
        executor = _make_executor()
        mock_db = AsyncMock()

        @asynccontextmanager
        async def _session():
            yield mock_db

        with (
            patch("app.db.async_session", _session),
            patch(
                "app.services.push_service.send_push",
                new_callable=AsyncMock,
                return_value=1,
            ),
        ):
            result = await executor.send_push(title="Hello", body="World")

        assert "1 device(s)" in result
