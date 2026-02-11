"""Tests for session summary generator."""

from __future__ import annotations

import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.memory.summary_generator import (
    MIN_TRANSCRIPT_LINES,
    SessionSummary,
    generate_session_summary,
)


@pytest.mark.unit
class TestGenerateSessionSummary:
    """Tests for generate_session_summary function."""

    @pytest.mark.asyncio
    async def test_generates_summary_with_sufficient_transcript(self) -> None:
        """Full pipeline runs when transcript has enough content."""
        mock_session = MagicMock()
        mock_session.project_id = "test-project"
        mock_session.agent_slug = "coder"

        events = [
            _mock_event("user_message", content="Fix the bug in auth.py"),
            _mock_event("assistant_message", content="I'll look at auth.py"),
            _mock_event("tool_use", tool_name="Read", tool_input={"file": "auth.py"}),
            _mock_event("tool_result", tool_output={"content": "def login(): ..."}),
            _mock_event("assistant_message", content="Found the issue, fixing now"),
        ]

        with (
            _mock_db(mock_session, events),
            patch(
                "app.services.memory.summary_generator.generate_via_llm",
                new_callable=AsyncMock,
                return_value=("Fixed auth bug", ["use bcrypt"], ["Read", "Edit"], ["auth.py"], ["auth"]),
            ) as mock_llm,
            patch(
                "app.services.memory.summary_generator.store_as_episode",
                new_callable=AsyncMock,
                return_value="episode-uuid-123",
            ) as mock_store,
        ):
            result = await generate_session_summary("test-session-id")

        assert isinstance(result, SessionSummary)
        assert result.summary == "Fixed auth bug"
        assert result.episode_uuid == "episode-uuid-123"
        assert not result.skipped
        mock_llm.assert_called_once()
        mock_store.assert_called_once()

    @pytest.mark.asyncio
    async def test_skips_when_transcript_empty(self) -> None:
        """Skips LLM and storage when transcript is empty (CC sessions)."""
        mock_session = MagicMock()
        mock_session.project_id = "test-project"
        mock_session.agent_slug = None

        # CC session: only memory_cite events, no conversation content
        events = [
            _mock_event("memory_cite", content="Cited 4 rules"),
            _mock_event("memory_inject", content="Injected context"),
        ]

        with (
            _mock_db(mock_session, events),
            patch(
                "app.services.memory.summary_generator.generate_via_llm",
                new_callable=AsyncMock,
            ) as mock_llm,
            patch(
                "app.services.memory.summary_generator.store_as_episode",
                new_callable=AsyncMock,
            ) as mock_store,
        ):
            result = await generate_session_summary("cc-session-id")

        assert result.skipped is True
        assert result.episode_uuid is None
        assert "insufficient transcript" in result.summary.lower()
        mock_llm.assert_not_called()
        mock_store.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_when_transcript_below_threshold(self) -> None:
        """Skips when transcript has fewer lines than MIN_TRANSCRIPT_LINES."""
        mock_session = MagicMock()
        mock_session.project_id = "test-project"
        mock_session.agent_slug = "coder"

        # Only 1 user message and 1 assistant — below threshold
        events = [
            _mock_event("user_message", content="hi"),
            _mock_event("assistant_message", content="hello"),
        ]

        with (
            _mock_db(mock_session, events),
            patch(
                "app.services.memory.summary_generator.generate_via_llm",
                new_callable=AsyncMock,
            ) as mock_llm,
            patch(
                "app.services.memory.summary_generator.store_as_episode",
                new_callable=AsyncMock,
            ) as mock_store,
        ):
            result = await generate_session_summary("short-session-id")

        # 2 lines < MIN_TRANSCRIPT_LINES (3)
        assert result.skipped is True
        mock_llm.assert_not_called()
        mock_store.assert_not_called()

    @pytest.mark.asyncio
    async def test_session_not_found_raises(self) -> None:
        """Raises ValueError when session doesn't exist."""
        with _mock_db(None, []):
            with pytest.raises(ValueError, match="not found"):
                await generate_session_summary("nonexistent-id")

    @pytest.mark.asyncio
    async def test_no_events_raises(self) -> None:
        """Raises ValueError when session has zero events."""
        mock_session = MagicMock()
        mock_session.project_id = "test-project"

        with _mock_db(mock_session, []):
            with pytest.raises(ValueError, match="no events"):
                await generate_session_summary("empty-session-id")

    @pytest.mark.asyncio
    async def test_project_id_fallback(self) -> None:
        """Uses provided project_id when session lacks one."""
        mock_session = MagicMock()
        mock_session.project_id = None
        mock_session.agent_slug = "coder"

        events = [_mock_event("user_message", content=f"msg {i}") for i in range(5)]

        with (
            _mock_db(mock_session, events),
            patch(
                "app.services.memory.summary_generator.generate_via_llm",
                new_callable=AsyncMock,
                return_value=("Summary", [], [], [], []),
            ) as mock_llm,
            patch(
                "app.services.memory.summary_generator.store_as_episode",
                new_callable=AsyncMock,
                return_value=None,
            ),
        ):
            result = await generate_session_summary("test-id", project_id="fallback-project")

        # Verify fallback project_id was used
        call_kwargs = mock_llm.call_args
        assert call_kwargs.kwargs["project_id"] == "fallback-project"

    @pytest.mark.asyncio
    async def test_quality_gate_logs_skip(self, caplog: pytest.LogCaptureFixture) -> None:
        """Quality gate logs when skipping a session."""
        mock_session = MagicMock()
        mock_session.project_id = "test-project"
        mock_session.agent_slug = None

        events = [_mock_event("memory_cite", content="Cited rules")]

        with (
            caplog.at_level(logging.INFO),
            _mock_db(mock_session, events),
            patch("app.services.memory.summary_generator.generate_via_llm", new_callable=AsyncMock),
            patch("app.services.memory.summary_generator.store_as_episode", new_callable=AsyncMock),
        ):
            await generate_session_summary("skip-session")

        assert any("skipping" in r.message.lower() for r in caplog.records)


def _mock_event(
    event_type: str,
    content: str | None = None,
    tool_name: str | None = None,
    tool_input: dict | None = None,
    tool_output: dict | None = None,
) -> MagicMock:
    """Create a mock SessionEvent."""
    event = MagicMock()
    event.event_type = event_type
    event.content = content
    event.tool_name = tool_name
    event.tool_input = tool_input
    event.tool_output = tool_output
    return event


def _mock_db(session: MagicMock | None, events: list[MagicMock]):
    """Context manager that mocks the DB session factory."""
    mock_db = AsyncMock()

    # First execute call: session query
    session_result = MagicMock()
    session_result.scalar_one_or_none.return_value = session

    # Second execute call: events query
    events_result = MagicMock()
    events_result.scalars.return_value.all.return_value = events

    mock_db.execute = AsyncMock(side_effect=[session_result, events_result])

    mock_factory = MagicMock()
    mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_db)
    mock_factory.return_value.__aexit__ = AsyncMock(return_value=None)

    return patch(
        "app.services.memory.summary_generator._get_session_factory",
        return_value=mock_factory,
    )
