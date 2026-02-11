"""Tests for session analysis service module."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.memory.session_analysis import (
    AnalysisResult,
    TaskOutcomeResult,
    analyze_session,
    find_sessions_for_task,
    process_task_outcome,
)


@pytest.mark.unit
class TestAnalyzeSession:
    """Tests for analyze_session function."""

    @pytest.mark.asyncio
    async def test_analyze_session_with_cc_prefixes_credits_resolved(self):
        """CC path: provided prefixes are resolved and credited."""
        with (
            patch(
                "app.services.memory.session_analysis.resolve_full_uuids",
                new_callable=AsyncMock,
                return_value={"abc12345": "abc12345-full-uuid-1", "def67890": "def67890-full-uuid-2"},
            ) as mock_resolve,
            patch(
                "app.services.memory.session_analysis._get_session_group_id",
                new_callable=AsyncMock,
                return_value="project-test",
            ),
            patch(
                "app.services.memory.session_analysis.track_referenced_batch",
                new_callable=AsyncMock,
            ) as mock_track,
            patch(
                "app.services.memory.session_analysis.track_helpful",
            ) as mock_helpful,
            patch(
                "app.services.memory.session_analysis._store_cite_event",
                new_callable=AsyncMock,
            ),
            patch(
                "app.services.memory.session_analysis.update_citation_metrics",
                new_callable=AsyncMock,
                return_value=1,
            ),
        ):
            result = await analyze_session(
                session_id="test-session",
                citation_prefixes=["abc12345", "def67890"],
            )

            assert isinstance(result, AnalysisResult)
            assert result.session_id == "test-session"
            assert result.citations_found == 2
            assert result.citations_credited == 2

            mock_resolve.assert_called_once_with(["abc12345", "def67890"], group_id="project-test")
            mock_track.assert_called_once()
            # Citations trigger helpful tracking
            assert mock_helpful.call_count == 2

    @pytest.mark.asyncio
    async def test_analyze_session_with_no_prefixes_scans_events(self):
        """API path: when no prefixes provided, scans session_events."""
        with (
            patch(
                "app.services.memory.session_analysis._extract_citations_from_events",
                new_callable=AsyncMock,
                return_value=["abc12345"],
            ) as mock_extract,
            patch(
                "app.services.memory.session_analysis.resolve_full_uuids",
                new_callable=AsyncMock,
                return_value={"abc12345": "abc12345-full-uuid"},
            ),
            patch(
                "app.services.memory.session_analysis._get_session_group_id",
                new_callable=AsyncMock,
                return_value="global",
            ),
            patch(
                "app.services.memory.session_analysis.track_referenced_batch",
                new_callable=AsyncMock,
            ),
            patch(
                "app.services.memory.session_analysis.track_helpful",
            ),
            patch(
                "app.services.memory.session_analysis._store_cite_event",
                new_callable=AsyncMock,
            ),
            patch(
                "app.services.memory.session_analysis.update_citation_metrics",
                new_callable=AsyncMock,
                return_value=1,
            ),
        ):
            result = await analyze_session(session_id="test-session")

            assert result.citations_found == 1
            assert result.citations_credited == 1
            mock_extract.assert_called_once_with("test-session")

    @pytest.mark.asyncio
    async def test_analyze_session_empty_prefixes_returns_zero(self):
        """Empty citation list returns zero counts."""
        result = await analyze_session(
            session_id="test-session",
            citation_prefixes=[],
        )

        assert result.citations_found == 0
        assert result.citations_credited == 0

    @pytest.mark.asyncio
    async def test_analyze_session_unresolved_prefixes_not_credited(self):
        """Prefixes that can't be resolved to full UUIDs are not credited."""
        with (
            patch(
                "app.services.memory.session_analysis.resolve_full_uuids",
                new_callable=AsyncMock,
                return_value={},  # Nothing resolved
            ),
            patch(
                "app.services.memory.session_analysis._get_session_group_id",
                new_callable=AsyncMock,
                return_value="global",
            ),
        ):
            result = await analyze_session(
                session_id="test-session",
                citation_prefixes=["deadbeef"],
            )

            assert result.citations_found == 1
            assert result.citations_credited == 0

    @pytest.mark.asyncio
    async def test_analyze_session_truncates_long_prefixes(self):
        """Prefixes longer than 8 chars are truncated to 8."""
        with (
            patch(
                "app.services.memory.session_analysis.resolve_full_uuids",
                new_callable=AsyncMock,
                return_value={"abc12345": "abc12345-full"},
            ) as mock_resolve,
            patch(
                "app.services.memory.session_analysis._get_session_group_id",
                new_callable=AsyncMock,
                return_value="global",
            ),
            patch(
                "app.services.memory.session_analysis.track_referenced_batch",
                new_callable=AsyncMock,
            ),
            patch(
                "app.services.memory.session_analysis.track_helpful",
            ),
            patch(
                "app.services.memory.session_analysis._store_cite_event",
                new_callable=AsyncMock,
            ),
            patch(
                "app.services.memory.session_analysis.update_citation_metrics",
                new_callable=AsyncMock,
                return_value=1,
            ),
        ):
            await analyze_session(
                session_id="test-session",
                citation_prefixes=["abc12345extra"],
            )

            # Should truncate to 8 chars
            mock_resolve.assert_called_once_with(["abc12345"], group_id="global")


@pytest.mark.unit
class TestProcessTaskOutcome:
    """Tests for process_task_outcome function."""

    @pytest.mark.asyncio
    async def test_process_task_outcome_success_credits_memories(self):
        """Successful task credits all loaded memories."""
        with (
            patch(
                "app.services.memory.session_analysis.update_citation_metrics",
                new_callable=AsyncMock,
                return_value=1,
            ),
            patch(
                "app.services.memory.session_analysis._get_memories_loaded",
                new_callable=AsyncMock,
                return_value=["uuid-1", "uuid-2", "uuid-3"],
            ),
            patch(
                "app.services.memory.session_analysis.track_success_batch",
                new_callable=AsyncMock,
            ) as mock_track_success,
        ):
            result = await process_task_outcome(
                session_id="test-session",
                succeeded=True,
                task_id="task-123",
            )

            assert isinstance(result, TaskOutcomeResult)
            assert result.task_succeeded is True
            assert result.metrics_updated == 1
            assert result.memories_credited == 3
            mock_track_success.assert_called_once_with(["uuid-1", "uuid-2", "uuid-3"])

    @pytest.mark.asyncio
    async def test_process_task_outcome_failure_no_credits(self):
        """Failed task does not credit memories."""
        with (
            patch(
                "app.services.memory.session_analysis.update_citation_metrics",
                new_callable=AsyncMock,
                return_value=1,
            ),
        ):
            result = await process_task_outcome(
                session_id="test-session",
                succeeded=False,
            )

            assert result.task_succeeded is False
            assert result.memories_credited == 0

    @pytest.mark.asyncio
    async def test_process_task_outcome_success_no_loaded_memories(self):
        """Successful task with no loaded memories credits nothing."""
        with (
            patch(
                "app.services.memory.session_analysis.update_citation_metrics",
                new_callable=AsyncMock,
                return_value=1,
            ),
            patch(
                "app.services.memory.session_analysis._get_memories_loaded",
                new_callable=AsyncMock,
                return_value=[],
            ),
        ):
            result = await process_task_outcome(
                session_id="test-session",
                succeeded=True,
            )

            assert result.memories_credited == 0


@pytest.mark.unit
class TestFindSessionsForTask:
    """Tests for find_sessions_for_task function."""

    @pytest.mark.asyncio
    async def test_find_sessions_for_task_returns_unique_ids(self):
        """Returns distinct session IDs matching external_id."""
        mock_result = MagicMock()
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = ["session-1", "session-2"]
        mock_result.scalars.return_value = mock_scalars

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result

        mock_factory = MagicMock()
        mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_factory.return_value.__aexit__ = AsyncMock(return_value=None)

        with patch(
            "app.services.memory.session_analysis._get_session_factory",
            return_value=mock_factory,
        ):
            result = await find_sessions_for_task("task-abc")

            assert result == ["session-1", "session-2"]


@pytest.mark.unit
class TestCitationHelpfulTracking:
    """Tests for citation-based helpful tracking in analyze_session."""

    @pytest.mark.asyncio
    async def test_cited_memories_tracked_as_helpful(self):
        """Cited memories get track_helpful called for each resolved UUID."""
        resolved = {
            "abc12345": "abc12345-full-uuid-1",
            "def67890": "def67890-full-uuid-2",
            "11223344": "11223344-full-uuid-3",
        }
        with (
            patch(
                "app.services.memory.session_analysis.resolve_full_uuids",
                new_callable=AsyncMock,
                return_value=resolved,
            ),
            patch(
                "app.services.memory.session_analysis._get_session_group_id",
                new_callable=AsyncMock,
                return_value="global",
            ),
            patch(
                "app.services.memory.session_analysis.track_referenced_batch",
                new_callable=AsyncMock,
            ),
            patch(
                "app.services.memory.session_analysis.track_helpful",
            ) as mock_helpful,
            patch(
                "app.services.memory.session_analysis._store_cite_event",
                new_callable=AsyncMock,
            ),
            patch(
                "app.services.memory.session_analysis.update_citation_metrics",
                new_callable=AsyncMock,
                return_value=1,
            ),
        ):
            result = await analyze_session(
                session_id="test-session",
                citation_prefixes=["abc12345", "def67890", "11223344"],
            )

            assert result.citations_credited == 3
            assert mock_helpful.call_count == 3
            helpful_uuids = {call.args[0] for call in mock_helpful.call_args_list}
            assert helpful_uuids == set(resolved.values())

    @pytest.mark.asyncio
    async def test_no_citations_no_helpful_tracking(self):
        """No resolved citations means no helpful tracking."""
        with (
            patch(
                "app.services.memory.session_analysis.resolve_full_uuids",
                new_callable=AsyncMock,
                return_value={},
            ),
            patch(
                "app.services.memory.session_analysis._get_session_group_id",
                new_callable=AsyncMock,
                return_value="global",
            ),
            patch(
                "app.services.memory.session_analysis.track_helpful",
            ) as mock_helpful,
        ):
            result = await analyze_session(
                session_id="test-session",
                citation_prefixes=["deadbeef"],
            )

            assert result.citations_credited == 0
            mock_helpful.assert_not_called()
