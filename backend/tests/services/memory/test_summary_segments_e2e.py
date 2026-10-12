"""E2E integration tests for the summary segment pipeline.

Tests the flow from summary generation to segment storage; continuity rendering of
segments is covered in test_continuity_injection.py.
Uses mocked DB and LLM to avoid production dependencies.

Per [G:8a45b8a8]: uses 'test-project', no production project IDs.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.memory.summary_generator import SessionSummary, generate_session_summary
from app.services.memory.summary_llm import LLMAnalysisResult
from app.services.memory.summary_transcript import (
    build_condensed_transcript_from_jsonl,
)
from app.services.session_operations import close_session_if_active


def _llm_result(**kwargs: Any) -> LLMAnalysisResult:
    """Build an LLMAnalysisResult with sensible defaults."""
    return LLMAnalysisResult(
        summary=kwargs.get("summary", "Test summary"),
        outcome=kwargs.get("outcome", "completed"),
        decisions=kwargs.get("decisions", []),
        tools=kwargs.get("tools", []),
        files=kwargs.get("files", []),
        topics=kwargs.get("topics", []),
        git_digest=kwargs.get("git_digest", ""),
        ratings=kwargs.get("ratings", {}),
    )


def _mock_event(event_type: str, content: str) -> MagicMock:
    """Create a mock SessionEvent."""
    event = MagicMock()
    event.event_type = event_type
    event.content = content
    event.tool_name = None
    event.tool_input = None
    event.tool_output = None
    return event


@pytest.mark.unit
class TestSummarySegmentE2E:
    """End-to-end tests for the summary segment pipeline."""

    @pytest.mark.asyncio
    async def test_fresh_session_creates_segment_and_updates_session(self) -> None:
        """Full pipeline: generate summary → segment created + session columns updated."""
        mock_session = MagicMock()
        mock_session.project_id = "test-project"
        mock_session.agent_slug = "coder"

        events = [_mock_event("user_message", content=f"msg {i}") for i in range(25)]

        # Track what gets added to DB
        added_objects: list[Any] = []

        mock_db_gen = AsyncMock()
        session_result = MagicMock()
        session_result.scalar_one_or_none.return_value = mock_session
        events_result = MagicMock()
        events_result.scalars.return_value.all.return_value = events
        mock_db_gen.execute = AsyncMock(side_effect=[session_result, events_result])

        mock_db_store = AsyncMock()
        store_session_result = MagicMock()
        store_session_result.scalar_one_or_none.return_value = mock_session
        mock_db_store.execute = AsyncMock(return_value=store_session_result)
        mock_db_store.commit = AsyncMock()
        mock_db_store.add = MagicMock(side_effect=lambda obj: added_objects.append(obj))

        # Factory returns different db sessions for the two calls
        call_count = 0

        def make_context() -> MagicMock:
            nonlocal call_count
            call_count += 1
            ctx = MagicMock()
            ctx.__aenter__ = AsyncMock(
                return_value=mock_db_gen if call_count == 1 else mock_db_store
            )
            ctx.__aexit__ = AsyncMock(return_value=None)
            return ctx

        mock_factory = MagicMock(side_effect=make_context)

        with (
            patch(
                "app.services.memory.summary_generator._get_session_factory",
                return_value=mock_factory,
            ),
            patch(
                "app.services.memory.summary_generator.generate_via_llm",
                new_callable=AsyncMock,
                return_value=_llm_result(
                    summary="Implemented auth flow",
                    outcome="completed",
                    files=["auth.py"],
                    git_digest="feat(auth): add login",
                ),
            ),
        ):
            result = await generate_session_summary(
                "test-session-1",
                branch="main",
            )

        # Verify the result
        assert isinstance(result, SessionSummary)
        assert result.summary == "Implemented auth flow"
        assert not result.skipped

        # Verify session columns updated
        assert mock_session.summary_oneliner == "Implemented auth flow"
        assert mock_session.summary_outcome == "completed"

        # Verify segment was created
        assert len(added_objects) == 1
        segment = added_objects[0]
        assert segment.session_id == "test-session-1"
        assert segment.summary_oneliner == "Implemented auth flow"
        assert segment.summary_outcome == "completed"
        assert segment.summary_git_digest == "feat(auth): add login"

    @pytest.mark.asyncio
    async def test_resumed_session_creates_two_segments(self) -> None:
        """Resuming a session creates a NEW segment, not overwriting the first.

        Simulates: morning work → Stop hook → afternoon /resume → Stop hook again.
        Both Stop hooks call generate_session_summary for the same session_id.
        """
        mock_session = MagicMock()
        mock_session.project_id = "test-project"
        mock_session.agent_slug = "coder"

        events = [_mock_event("user_message", content=f"msg {i}") for i in range(25)]
        all_segments: list[Any] = []

        async def _run_summary(summary_text: str, git_digest: str) -> SessionSummary:
            """Run generate_session_summary with specific LLM output."""
            mock_db_gen = AsyncMock()
            session_result = MagicMock()
            session_result.scalar_one_or_none.return_value = mock_session
            events_result = MagicMock()
            events_result.scalars.return_value.all.return_value = events
            mock_db_gen.execute = AsyncMock(side_effect=[session_result, events_result])

            mock_db_store = AsyncMock()
            store_session_result = MagicMock()
            store_session_result.scalar_one_or_none.return_value = mock_session
            mock_db_store.execute = AsyncMock(return_value=store_session_result)
            mock_db_store.commit = AsyncMock()
            mock_db_store.add = MagicMock(side_effect=lambda obj: all_segments.append(obj))

            call_count_inner = 0

            def make_context() -> MagicMock:
                nonlocal call_count_inner
                call_count_inner += 1
                ctx = MagicMock()
                ctx.__aenter__ = AsyncMock(
                    return_value=mock_db_gen if call_count_inner == 1 else mock_db_store
                )
                ctx.__aexit__ = AsyncMock(return_value=None)
                return ctx

            mock_factory = MagicMock(side_effect=make_context)

            with (
                patch(
                    "app.services.memory.summary_generator._get_session_factory",
                    return_value=mock_factory,
                ),
                patch(
                    "app.services.memory.summary_generator.generate_via_llm",
                    new_callable=AsyncMock,
                    return_value=_llm_result(
                        summary=summary_text,
                        git_digest=git_digest,
                    ),
                ),
            ):
                return await generate_session_summary(
                    "resumed-session-1",
                    branch="main",
                )

        # Morning work
        await _run_summary("Morning: set up auth scaffolding", "feat: auth scaffold")
        # Afternoon work (resumed session, same session_id)
        await _run_summary("Afternoon: completed auth tests", "test: auth tests")

        # Two segments created for the SAME session
        assert len(all_segments) == 2
        assert all_segments[0].summary_oneliner == "Morning: set up auth scaffolding"
        assert all_segments[1].summary_oneliner == "Afternoon: completed auth tests"
        assert all_segments[0].session_id == all_segments[1].session_id == "resumed-session-1"

        # Session columns reflect LATEST summary (overwritten)
        assert mock_session.summary_oneliner == "Afternoon: completed auth tests"

@pytest.mark.unit
class TestRecencyBiasedTranscriptE2E:
    """E2E test for recency-biased transcript producing relevant summaries."""

    def test_long_transcript_biases_toward_recent_content(self) -> None:
        """Long transcript with distinct early/late topics biases toward recent."""
        # Build 200 JSONL lines: first 150 about "testing", last 50 about "tool-registry"
        jsonl_lines = []
        for i in range(150):
            jsonl_lines.append(
                f'{{"type": "user", "message": {{"role": "user", "content": "testing msg {i}"}}}}'
            )
        for i in range(50):
            jsonl_lines.append(
                f'{{"type": "user", "message": {{"role": "user", "content": "tool-registry change {i}"}}}}'
            )

        result = build_condensed_transcript_from_jsonl(jsonl_lines)
        lines = result.split("\n")

        # Should contain recency separator
        assert "--- [recent work below] ---" in result

        # Recent section should be dominated by "tool-registry" content
        sep_idx = lines.index("--- [recent work below] ---")
        recent_lines = lines[sep_idx + 1 :]
        tool_registry_count = sum(1 for ln in recent_lines if "tool-registry" in ln)
        testing_count = sum(1 for ln in recent_lines if "testing" in ln)

        # tool-registry lines (from the last 50 of 200) should dominate recent section
        assert tool_registry_count > testing_count

    def test_short_transcript_no_windowing(self) -> None:
        """Short transcripts pass through without windowing or separator."""
        jsonl_lines = [
            f'{{"type": "user", "message": {{"role": "user", "content": "msg {i}"}}}}'
            for i in range(30)
        ]
        result = build_condensed_transcript_from_jsonl(jsonl_lines)

        assert "--- [recent work below] ---" not in result
        assert len(result.split("\n")) == 30


@pytest.mark.unit
class TestSessionClose:
    """close_session_if_active marks active sessions completed exactly once."""

    @pytest.mark.asyncio
    async def test_close_marks_active_session_completed(self) -> None:
        session = MagicMock()
        session.status = "active"
        db = AsyncMock()

        status, message = await close_session_if_active(db, session)

        assert (status, message) == ("completed", "Session closed successfully")
        assert session.status == "completed"
        db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_close_already_completed(self) -> None:
        """Already-completed sessions return early."""
        mock_session = MagicMock()
        mock_session.status = "completed"

        mock_db = AsyncMock()

        status, _ = await close_session_if_active(mock_db, mock_session)

        assert status == "completed"
        mock_db.commit.assert_not_awaited()
