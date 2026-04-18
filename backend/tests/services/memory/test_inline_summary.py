"""Tests for inline summary tag processing."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.services.memory.citation_parser import parse_summary_tags
from app.services.memory.session_analysis import _process_summary_tags, analyze_session

# Both citation_tracker.track_inline_summaries and session_analysis._process_summary_tags
# import _store_summary_on_session and _enforce_oneliner inside their function bodies from
# app.services.memory.summary_generator. We must mock at the source module.
_STORE_PATCH = "app.services.memory.summary_generator._store_summary_on_session"
_ENFORCE_PATCH = "app.services.memory.summary_generator._enforce_oneliner"


@pytest.mark.unit
class TestTrackInlineSummaries:
    """Tests for API-path inline summary tracking via citation_tracker."""

    @pytest.mark.asyncio
    async def test_stores_summary_from_content(self) -> None:
        """track_inline_summaries stores summary from [[S:...]] tag in content."""
        from app.api.complete.citation_tracker import track_inline_summaries

        mock_db = AsyncMock()

        with (
            patch(_STORE_PATCH, new_callable=AsyncMock) as mock_store,
            patch(_ENFORCE_PATCH, side_effect=lambda x: x),
        ):
            result = await track_inline_summaries(
                "Done! [[S:completed:Implemented the auth feature]]",
                mock_db,
                "session-123",
                agent_id="coder",
            )

            assert result is True
            mock_store.assert_called_once_with(
                session_id="session-123",
                summary_oneliner="Implemented the auth feature",
                outcome="completed",
                files_touched=[],
                git_digest="",
                db=mock_db,
            )

    @pytest.mark.asyncio
    async def test_takes_last_tag(self) -> None:
        """When multiple summary tags exist, the last one (most complete) is used."""
        from app.api.complete.citation_tracker import track_inline_summaries

        mock_db = AsyncMock()

        with (
            patch(_STORE_PATCH, new_callable=AsyncMock) as mock_store,
            patch(_ENFORCE_PATCH, side_effect=lambda x: x),
        ):
            content = (
                "[[S:partial:Started the work]]\n"
                "More work...\n"
                "[[S:completed:Finished everything]]"
            )
            result = await track_inline_summaries(content, mock_db, "session-123")

            assert result is True
            mock_store.assert_called_once()
            call_kwargs = mock_store.call_args[1]
            assert call_kwargs["summary_oneliner"] == "Finished everything"
            assert call_kwargs["outcome"] == "completed"
            assert call_kwargs["db"] is mock_db

    @pytest.mark.asyncio
    async def test_no_tags_returns_false(self) -> None:
        """Content without summary tags returns False without storing."""
        from app.api.complete.citation_tracker import track_inline_summaries

        mock_db = AsyncMock()

        result = await track_inline_summaries(
            "Just normal text without any summary tags",
            mock_db,
            "session-123",
        )

        assert result is False

    @pytest.mark.asyncio
    async def test_enforces_150_char_limit(self) -> None:
        """Summary descriptions are enforced to 150 char limit via _enforce_oneliner."""
        from app.api.complete.citation_tracker import track_inline_summaries

        mock_db = AsyncMock()

        with (
            patch(_STORE_PATCH, new_callable=AsyncMock),
            patch(_ENFORCE_PATCH) as mock_enforce,
        ):
            mock_enforce.return_value = "truncated"
            long_desc = "x" * 200
            await track_inline_summaries(
                f"[[S:completed:{long_desc}]]",
                mock_db,
                "session-123",
            )

            mock_enforce.assert_called_once_with(long_desc)


@pytest.mark.unit
class TestProcessSummaryTags:
    """Tests for CC-path summary tag processing in session_analysis."""

    @pytest.mark.asyncio
    async def test_processes_raw_strings(self) -> None:
        """_process_summary_tags parses raw [[S:...]] strings and stores summary."""
        with (
            patch(_STORE_PATCH, new_callable=AsyncMock) as mock_store,
            patch(_ENFORCE_PATCH, side_effect=lambda x: x),
        ):
            result = await _process_summary_tags(
                "session-123",
                summary_tags=["[[S:completed:Fixed the auth bug]]"],
            )

            assert result is True
            mock_store.assert_called_once()
            call_kwargs = mock_store.call_args[1]
            assert call_kwargs["summary_oneliner"] == "Fixed the auth bug"
            assert call_kwargs["outcome"] == "completed"
            assert call_kwargs["session_id"] == "session-123"

    @pytest.mark.asyncio
    async def test_merges_git_context(self) -> None:
        """_process_summary_tags builds git_digest from git_context."""
        with (
            patch(_STORE_PATCH, new_callable=AsyncMock) as mock_store,
            patch(_ENFORCE_PATCH, side_effect=lambda x: x),
        ):
            await _process_summary_tags(
                "session-123",
                summary_tags=["[[S:completed:Fixed auth]]"],
                git_context="abc1234 feat: add auth\ndef5678 fix: typo",
            )

            call_kwargs = mock_store.call_args[1]
            assert "feat: add auth" in call_kwargs["git_digest"]
            assert "fix: typo" in call_kwargs["git_digest"]

    @pytest.mark.asyncio
    async def test_passes_branch_and_checkout(self) -> None:
        with (
            patch(_STORE_PATCH, new_callable=AsyncMock) as mock_store,
            patch(_ENFORCE_PATCH, side_effect=lambda x: x),
        ):
            await _process_summary_tags(
                "session-123",
                summary_tags=["[[S:partial:In progress]]"],
                branch="feature/auth",
            )

            call_kwargs = mock_store.call_args[1]
            assert call_kwargs["branch"] == "feature/auth"

    @pytest.mark.asyncio
    async def test_no_tags_returns_false(self) -> None:
        """Empty summary_tags list returns False."""
        result = await _process_summary_tags("session-123", summary_tags=[])
        assert result is False

    @pytest.mark.asyncio
    async def test_none_tags_returns_false(self) -> None:
        """None summary_tags returns False."""
        result = await _process_summary_tags("session-123", summary_tags=None)
        assert result is False


@pytest.mark.unit
class TestAnalyzeSessionSummaryIntegration:
    """Tests for summary tag integration in analyze_session."""

    @pytest.mark.asyncio
    async def test_analyze_session_with_summary_tags(self) -> None:
        """analyze_session forwards summary_tags and returns summary_stored."""
        with (
            patch(
                "app.services.memory.session_analysis._process_feedback_tags",
                new_callable=AsyncMock,
                return_value=0,
            ),
            patch(
                "app.services.memory.session_analysis._process_summary_tags",
                new_callable=AsyncMock,
                return_value=True,
            ) as mock_summary,
        ):
            result = await analyze_session(
                session_id="test-session",
                citation_prefixes=[],
                summary_tags=["[[S:completed:Did the thing]]"],
                git_context="abc1234 feat: thing",
                branch="main",
            )

            assert result.summary_stored is True
            mock_summary.assert_called_once_with(
                "test-session",
                ["[[S:completed:Did the thing]]"],
                "abc1234 feat: thing",
                "main",
                False,
            )

    @pytest.mark.asyncio
    async def test_analyze_session_without_summary_tags(self) -> None:
        """analyze_session works without summary_tags (backward compat)."""
        with (
            patch(
                "app.services.memory.session_analysis._process_feedback_tags",
                new_callable=AsyncMock,
                return_value=0,
            ),
            patch(
                "app.services.memory.session_analysis._process_summary_tags",
                new_callable=AsyncMock,
                return_value=False,
            ),
        ):
            result = await analyze_session(
                session_id="test-session",
                citation_prefixes=[],
            )

            assert result.summary_stored is False


@pytest.mark.unit
class TestSummaryParserEdgeCases:
    """Edge case tests for summary tag parsing."""

    def test_description_with_colons(self) -> None:
        """Summary description can contain colons."""
        result = parse_summary_tags("[[S:completed:Fixed: the auth bug: resolved]]")
        assert len(result.tags) == 1
        assert result.tags[0].description == "Fixed: the auth bug: resolved"

    def test_empty_description(self) -> None:
        """Summary with empty description."""
        result = parse_summary_tags("[[S:completed:]]")
        assert len(result.tags) == 1
        assert result.tags[0].description == ""

    def test_description_with_special_chars(self) -> None:
        """Summary description with special characters."""
        result = parse_summary_tags("[[S:completed:Added `async` support & error handling]]")
        assert len(result.tags) == 1
        assert "`async`" in result.tags[0].description
