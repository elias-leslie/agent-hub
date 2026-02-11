"""Tests for session summary generator."""

from __future__ import annotations

import logging
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.memory.summary_generator import (
    MIN_TRANSCRIPT_LINES,
    SessionSummary,
    _store_summary_on_session,
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

        # Need MIN_TRANSCRIPT_LINES (20) events to pass quality gate
        events = [_mock_event("user_message", content=f"msg {i}") for i in range(25)]

        with (
            _mock_db(mock_session, events),
            patch(
                "app.services.memory.summary_generator.generate_via_llm",
                new_callable=AsyncMock,
                return_value=("Fixed auth bug", ["use bcrypt"], ["Read", "Edit"], ["auth.py"], ["auth"], "completed"),
            ) as mock_llm,
            patch(
                "app.services.memory.summary_generator._store_summary_on_session",
                new_callable=AsyncMock,
            ) as mock_store,
        ):
            result = await generate_session_summary("test-session-id")

        assert isinstance(result, SessionSummary)
        assert result.summary == "Fixed auth bug"
        assert result.outcome == "completed"
        assert not result.skipped
        mock_llm.assert_called_once()
        mock_store.assert_called_once_with(
            session_id="test-session-id",
            summary_oneliner="Fixed auth bug",
            outcome="completed",
            files_touched=["auth.py"],
        )

    @pytest.mark.asyncio
    async def test_stores_outcome_from_llm(self) -> None:
        """Outcome field is extracted from LLM response and stored."""
        mock_session = MagicMock()
        mock_session.project_id = "test-project"
        mock_session.agent_slug = "coder"

        events = [_mock_event("user_message", content=f"msg {i}") for i in range(25)]

        with (
            _mock_db(mock_session, events),
            patch(
                "app.services.memory.summary_generator.generate_via_llm",
                new_callable=AsyncMock,
                return_value=("Permission denied error", [], [], [], [], "failed"),
            ),
            patch(
                "app.services.memory.summary_generator._store_summary_on_session",
                new_callable=AsyncMock,
            ) as mock_store,
        ):
            result = await generate_session_summary("test-session-id")

        assert result.outcome == "failed"
        mock_store.assert_called_once()
        assert mock_store.call_args.kwargs["outcome"] == "failed"

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
                "app.services.memory.summary_generator._store_summary_on_session",
                new_callable=AsyncMock,
            ) as mock_store,
        ):
            result = await generate_session_summary("cc-session-id")

        assert result.skipped is True
        assert "insufficient transcript" in result.summary.lower()
        mock_llm.assert_not_called()
        mock_store.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_when_transcript_below_threshold(self) -> None:
        """Skips when transcript has fewer lines than MIN_TRANSCRIPT_LINES (20)."""
        mock_session = MagicMock()
        mock_session.project_id = "test-project"
        mock_session.agent_slug = "coder"

        # 10 events < MIN_TRANSCRIPT_LINES (20)
        events = [_mock_event("user_message", content=f"msg {i}") for i in range(10)]

        with (
            _mock_db(mock_session, events),
            patch(
                "app.services.memory.summary_generator.generate_via_llm",
                new_callable=AsyncMock,
            ) as mock_llm,
            patch(
                "app.services.memory.summary_generator._store_summary_on_session",
                new_callable=AsyncMock,
            ) as mock_store,
        ):
            result = await generate_session_summary("short-session-id")

        assert result.skipped is True
        mock_llm.assert_not_called()
        mock_store.assert_not_called()

    @pytest.mark.asyncio
    async def test_quality_gate_threshold_is_20(self) -> None:
        """MIN_TRANSCRIPT_LINES is 20 — verifies threshold."""
        assert MIN_TRANSCRIPT_LINES == 20

    @pytest.mark.asyncio
    async def test_session_not_found_raises(self) -> None:
        """Raises ValueError when session doesn't exist."""
        with _mock_db(None, []), pytest.raises(ValueError, match="not found"):
            await generate_session_summary("nonexistent-id")

    @pytest.mark.asyncio
    async def test_no_events_raises(self) -> None:
        """Raises ValueError when session has zero events."""
        mock_session = MagicMock()
        mock_session.project_id = "test-project"

        with _mock_db(mock_session, []), pytest.raises(ValueError, match="no events"):
            await generate_session_summary("empty-session-id")

    @pytest.mark.asyncio
    async def test_project_id_fallback(self) -> None:
        """Uses provided project_id when session lacks one."""
        mock_session = MagicMock()
        mock_session.project_id = None
        mock_session.agent_slug = "coder"

        events = [_mock_event("user_message", content=f"msg {i}") for i in range(25)]

        with (
            _mock_db(mock_session, events),
            patch(
                "app.services.memory.summary_generator.generate_via_llm",
                new_callable=AsyncMock,
                return_value=("Summary", [], [], [], [], "completed"),
            ) as mock_llm,
            patch(
                "app.services.memory.summary_generator._store_summary_on_session",
                new_callable=AsyncMock,
            ),
        ):
            await generate_session_summary("test-id", project_id="fallback-project")

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
            patch("app.services.memory.summary_generator._store_summary_on_session", new_callable=AsyncMock),
        ):
            await generate_session_summary("skip-session")

        assert any("skipping" in r.message.lower() for r in caplog.records)


@pytest.mark.unit
class TestStoreSummaryOnSession:
    """Tests for _store_summary_on_session function."""

    @pytest.mark.asyncio
    async def test_stores_summary_fields(self) -> None:
        """Stores all summary fields on the session row."""
        mock_session = MagicMock()

        with _mock_db_for_store(mock_session):
            await _store_summary_on_session(
                session_id="test-id",
                summary_oneliner="Fixed auth bug",
                outcome="completed",
                files_touched=["auth.py", "tests/test_auth.py"],
            )

        assert mock_session.summary_oneliner == "Fixed auth bug"
        assert mock_session.summary_outcome == "completed"
        assert mock_session.summary_files_touched == ["auth.py", "tests/test_auth.py"]
        assert mock_session.summary_generated_at is not None

    @pytest.mark.asyncio
    async def test_stores_none_files_when_empty(self) -> None:
        """Stores None for files_touched when list is empty."""
        mock_session = MagicMock()

        with _mock_db_for_store(mock_session):
            await _store_summary_on_session(
                session_id="test-id",
                summary_oneliner="No files modified",
                outcome="partial",
                files_touched=[],
            )

        assert mock_session.summary_files_touched is None

    @pytest.mark.asyncio
    async def test_handles_missing_session(self, caplog: pytest.LogCaptureFixture) -> None:
        """Logs warning when session not found for summary storage."""
        with (
            caplog.at_level(logging.WARNING),
            _mock_db_for_store(None),
        ):
            await _store_summary_on_session(
                session_id="missing-id",
                summary_oneliner="test",
                outcome="completed",
                files_touched=[],
            )

        assert any("not found" in r.message.lower() for r in caplog.records)


def _mock_event(
    event_type: str,
    content: str | None = None,
    tool_name: str | None = None,
    tool_input: dict[str, Any] | None = None,
    tool_output: dict[str, Any] | None = None,
) -> MagicMock:
    """Create a mock SessionEvent."""
    event = MagicMock()
    event.event_type = event_type
    event.content = content
    event.tool_name = tool_name
    event.tool_input = tool_input
    event.tool_output = tool_output
    return event


def _mock_db(session: MagicMock | None, events: list[MagicMock]) -> Any:
    """Context manager that mocks the DB session factory for generate_session_summary."""
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


def _mock_db_for_store(session: MagicMock | None) -> Any:
    """Context manager that mocks the DB session factory for _store_summary_on_session."""
    mock_db = AsyncMock()

    session_result = MagicMock()
    session_result.scalar_one_or_none.return_value = session

    mock_db.execute = AsyncMock(return_value=session_result)
    mock_db.commit = AsyncMock()

    mock_factory = MagicMock()
    mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_db)
    mock_factory.return_value.__aexit__ = AsyncMock(return_value=None)

    return patch(
        "app.services.memory.summary_generator._get_session_factory",
        return_value=mock_factory,
    )
