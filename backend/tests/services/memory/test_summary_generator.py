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
from app.services.memory.summary_llm import LLMAnalysisResult


def _llm_result(
    summary: str = "",
    outcome: str = "completed",
    decisions: list[str] | None = None,
    tools: list[str] | None = None,
    files: list[str] | None = None,
    topics: list[str] | None = None,
    git_digest: str = "",
    ratings: dict[str, str] | None = None,
) -> LLMAnalysisResult:
    """Helper to build an LLMAnalysisResult with sensible defaults."""
    return LLMAnalysisResult(
        summary=summary,
        outcome=outcome,
        decisions=decisions or [],
        tools=tools or [],
        files=files or [],
        topics=topics or [],
        git_digest=git_digest,
        ratings=ratings or {},
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
                return_value=_llm_result(
                    summary="Fixed auth bug",
                    decisions=["use bcrypt"],
                    tools=["Read", "Edit"],
                    files=["auth.py"],
                    topics=["auth"],
                ),
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
            branch=None,
            git_digest="",
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
                return_value=_llm_result(summary="Permission denied error", outcome="failed"),
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
                return_value=_llm_result(summary="Summary"),
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
    async def test_passes_branch_to_store(self) -> None:
        mock_session = MagicMock()
        mock_session.project_id = "test-project"
        mock_session.agent_slug = "coder"

        events = [_mock_event("user_message", content=f"msg {i}") for i in range(25)]

        with (
            _mock_db(mock_session, events),
            patch(
                "app.services.memory.summary_generator.generate_via_llm",
                new_callable=AsyncMock,
                return_value=_llm_result(
                    summary="Checkout work", files=["feature.py"]
                ),
            ),
            patch(
                "app.services.memory.summary_generator._store_summary_on_session",
                new_callable=AsyncMock,
            ) as mock_store,
        ):
            await generate_session_summary(
                session_id="test-id",
                branch="feature/auth",
            )

        mock_store.assert_called_once_with(
            session_id="test-id",
            summary_oneliner="Checkout work",
            outcome="completed",
            files_touched=["feature.py"],
            branch="feature/auth",
            git_digest="",
        )

    @pytest.mark.asyncio
    async def test_passes_git_context_to_llm(self) -> None:
        """git_context is forwarded to generate_via_llm."""
        mock_session = MagicMock()
        mock_session.project_id = "test-project"
        mock_session.agent_slug = "coder"

        events = [_mock_event("user_message", content=f"msg {i}") for i in range(25)]

        with (
            _mock_db(mock_session, events),
            patch(
                "app.services.memory.summary_generator.generate_via_llm",
                new_callable=AsyncMock,
                return_value=_llm_result(
                    summary="Git-enriched summary",
                    git_digest="feat(auth): add login endpoint",
                ),
            ) as mock_llm,
            patch(
                "app.services.memory.summary_generator._store_summary_on_session",
                new_callable=AsyncMock,
            ) as mock_store,
        ):
            await generate_session_summary(
                "test-id", git_context="abc1234 feat(auth): add login endpoint"
            )

        assert mock_llm.call_args.kwargs["git_context"] == "abc1234 feat(auth): add login endpoint"
        assert mock_store.call_args.kwargs["git_digest"] == "feat(auth): add login endpoint"

    @pytest.mark.asyncio
    async def test_returns_ratings_from_llm(self) -> None:
        """Ratings from the combined LLM call are returned in SessionSummary."""
        mock_session = MagicMock()
        mock_session.project_id = "test-project"
        mock_session.agent_slug = "coder"

        events = [_mock_event("user_message", content=f"msg {i}") for i in range(25)]
        test_ratings = {"uuid-1-full": "helpful", "uuid-2-full": "neutral"}

        with (
            _mock_db(mock_session, events),
            patch(
                "app.services.memory.summary_generator.generate_via_llm",
                new_callable=AsyncMock,
                return_value=_llm_result(summary="With ratings", ratings=test_ratings),
            ),
            patch(
                "app.services.memory.summary_generator._store_summary_on_session",
                new_callable=AsyncMock,
            ),
        ):
            result = await generate_session_summary("test-id")

        assert result.ratings == test_ratings

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
    async def test_stores_branch_and_checkout(self) -> None:
        mock_session = MagicMock()

        with _mock_db_for_store(mock_session):
            await _store_summary_on_session(
                session_id="test-id",
                summary_oneliner="Feature work",
                outcome="completed",
                files_touched=["feature.py"],
                branch="feature/auth",
            )

        assert mock_session.summary_branch == "feature/auth"

    @pytest.mark.asyncio
    async def test_stores_git_digest(self) -> None:
        """Stores git_digest on the session row."""
        mock_session = MagicMock()

        with _mock_db_for_store(mock_session):
            await _store_summary_on_session(
                session_id="test-id",
                summary_oneliner="Committed work",
                outcome="completed",
                files_touched=["feature.py"],
                git_digest="feat(auth): add login endpoint",
            )

        assert mock_session.summary_git_digest == "feat(auth): add login endpoint"

    @pytest.mark.asyncio
    async def test_stores_none_git_digest_when_empty(self) -> None:
        """Stores None for git_digest when string is empty."""
        mock_session = MagicMock()

        with _mock_db_for_store(mock_session):
            await _store_summary_on_session(
                session_id="test-id",
                summary_oneliner="No commits",
                outcome="completed",
                files_touched=[],
                git_digest="",
            )

        assert mock_session.summary_git_digest is None

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

    @pytest.mark.asyncio
    async def test_creates_segment_row(self) -> None:
        """Creates a SessionSummarySegment alongside session column updates."""
        mock_session = MagicMock()
        mock_db = AsyncMock()

        session_result = MagicMock()
        session_result.scalar_one_or_none.return_value = mock_session
        mock_db.execute = AsyncMock(return_value=session_result)
        mock_db.commit = AsyncMock()
        mock_db.add = MagicMock()

        mock_factory = MagicMock()
        mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_db)
        mock_factory.return_value.__aexit__ = AsyncMock(return_value=None)

        with patch(
            "app.services.memory.summary_generator._get_session_factory",
            return_value=mock_factory,
        ):
            await _store_summary_on_session(
                session_id="test-id",
                summary_oneliner="Segment summary",
                outcome="completed",
                files_touched=["auth.py"],
                branch="main",
                git_digest="feat: add auth",
            )

        # Session columns updated
        assert mock_session.summary_oneliner == "Segment summary"

        # Segment row added via db.add()
        mock_db.add.assert_called_once()
        segment = mock_db.add.call_args[0][0]
        assert segment.session_id == "test-id"
        assert segment.summary_oneliner == "Segment summary"
        assert segment.summary_outcome == "completed"
        assert segment.summary_git_digest == "feat: add auth"
        assert segment.summary_branch == "main"

    @pytest.mark.asyncio
    async def test_segment_not_created_when_session_missing(self) -> None:
        """No segment created when session not found (early return)."""
        mock_db = AsyncMock()

        session_result = MagicMock()
        session_result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=session_result)
        mock_db.add = MagicMock()

        mock_factory = MagicMock()
        mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_db)
        mock_factory.return_value.__aexit__ = AsyncMock(return_value=None)

        with patch(
            "app.services.memory.summary_generator._get_session_factory",
            return_value=mock_factory,
        ):
            await _store_summary_on_session(
                session_id="missing-id",
                summary_oneliner="test",
                outcome="completed",
                files_touched=[],
            )

        mock_db.add.assert_not_called()

    @pytest.mark.asyncio
    async def test_uses_caller_owned_db_without_committing(self) -> None:
        """Caller-owned sessions stay uncommitted so outer flows keep one transaction."""
        mock_session = MagicMock()
        mock_db = AsyncMock()

        session_result = MagicMock()
        session_result.scalar_one_or_none.return_value = mock_session
        mock_db.execute = AsyncMock(return_value=session_result)
        mock_db.commit = AsyncMock()
        mock_db.add = MagicMock()

        await _store_summary_on_session(
            session_id="test-id",
            summary_oneliner="Inline summary",
            outcome="completed",
            files_touched=["auth.py"],
            db=mock_db,
        )

        assert mock_session.summary_oneliner == "Inline summary"
        mock_db.add.assert_called_once()
        mock_db.commit.assert_not_awaited()


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
