"""Tests for session analysis service module."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
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
    async def test_analyze_session_with_cc_prefixes_credits_resolved(self) -> None:
        """CC path: provided prefixes are resolved and credited."""
        with (
            patch(
                "app.services.memory.session_analysis.resolve_full_uuids",
                new_callable=AsyncMock,
                return_value={"abc12345": "abc12345-full-uuid-1", "def67890": "def67890-full-uuid-2"},
            ) as mock_resolve,
            patch(
                "app.services.memory.session_analysis.get_session_group_id",
                new_callable=AsyncMock,
                return_value="project-test",
            ),
            patch(
                "app.services.memory.session_analysis.track_referenced_batch",
                new_callable=AsyncMock,
            ) as mock_track,
            patch(
                "app.services.memory.session_analysis.get_cited_memories",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch(
                "app.services.memory.session_analysis.store_cite_event",
                new_callable=AsyncMock,
            ),
            patch(
                "app.services.memory.session_analysis.update_citation_metrics",
                new_callable=AsyncMock,
                return_value=1,
            ),
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
                citation_prefixes=["abc12345", "def67890"],
            )

            assert isinstance(result, AnalysisResult)
            assert result.session_id == "test-session"
            assert result.citations_found == 2
            assert result.citations_credited == 2

            mock_resolve.assert_called_once_with(["abc12345", "def67890"], group_id="project-test")
            mock_track.assert_called_once()

    @pytest.mark.asyncio
    async def test_analyze_session_with_no_prefixes_scans_events(self) -> None:
        """API path: when no prefixes provided, scans session_events."""
        with (
            patch(
                "app.services.memory.session_analysis.extract_citations_from_events",
                new_callable=AsyncMock,
                return_value=["abc12345"],
            ) as mock_extract,
            patch(
                "app.services.memory.session_analysis.resolve_full_uuids",
                new_callable=AsyncMock,
                return_value={"abc12345": "abc12345-full-uuid"},
            ),
            patch(
                "app.services.memory.session_analysis.get_session_group_id",
                new_callable=AsyncMock,
                return_value="global",
            ),
            patch(
                "app.services.memory.session_analysis.track_referenced_batch",
                new_callable=AsyncMock,
            ),
            patch(
                "app.services.memory.session_analysis.get_cited_memories",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch(
                "app.services.memory.session_analysis.store_cite_event",
                new_callable=AsyncMock,
            ),
            patch(
                "app.services.memory.session_analysis.update_citation_metrics",
                new_callable=AsyncMock,
                return_value=1,
            ),
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
            result = await analyze_session(session_id="test-session")

            assert result.citations_found == 1
            assert result.citations_credited == 1
            mock_extract.assert_called_once_with("test-session")

    @pytest.mark.asyncio
    async def test_analyze_session_empty_prefixes_returns_zero(self) -> None:
        """Empty citation list returns zero counts."""
        with patch(
            "app.services.memory.session_analysis._process_feedback_tags",
            new_callable=AsyncMock,
            return_value=0,
        ):
            result = await analyze_session(
                session_id="test-session",
                citation_prefixes=[],
            )

            assert result.citations_found == 0
            assert result.citations_credited == 0

    @pytest.mark.asyncio
    async def test_analyze_session_unresolved_prefixes_not_credited(self) -> None:
        """Prefixes that can't be resolved to full UUIDs are not credited."""
        with (
            patch(
                "app.services.memory.session_analysis.resolve_full_uuids",
                new_callable=AsyncMock,
                return_value={},  # Nothing resolved
            ),
            patch(
                "app.services.memory.session_analysis.get_session_group_id",
                new_callable=AsyncMock,
                return_value="global",
            ),
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
                citation_prefixes=["deadbeef"],
            )

            assert result.citations_found == 1
            assert result.citations_credited == 0

    @pytest.mark.asyncio
    async def test_analyze_session_truncates_long_prefixes(self) -> None:
        """Prefixes longer than 8 chars are truncated to 8."""
        with (
            patch(
                "app.services.memory.session_analysis.resolve_full_uuids",
                new_callable=AsyncMock,
                return_value={"abc12345": "abc12345-full"},
            ) as mock_resolve,
            patch(
                "app.services.memory.session_analysis.get_session_group_id",
                new_callable=AsyncMock,
                return_value="global",
            ),
            patch(
                "app.services.memory.session_analysis.track_referenced_batch",
                new_callable=AsyncMock,
            ),
            patch(
                "app.services.memory.session_analysis.get_cited_memories",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch(
                "app.services.memory.session_analysis.store_cite_event",
                new_callable=AsyncMock,
            ),
            patch(
                "app.services.memory.session_analysis.update_citation_metrics",
                new_callable=AsyncMock,
                return_value=1,
            ),
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
            await analyze_session(
                session_id="test-session",
                citation_prefixes=["abc12345extra"],
            )

            # Should truncate to 8 chars
            mock_resolve.assert_called_once_with(["abc12345"], group_id="global")

    @pytest.mark.asyncio
    async def test_analyze_session_skips_already_credited_citations(self) -> None:
        """Re-analyzing a session should not double-credit existing citations."""
        with (
            patch(
                "app.services.memory.session_analysis.resolve_full_uuids",
                new_callable=AsyncMock,
                return_value={
                    "abc12345": "abc12345-full-uuid-1",
                    "def67890": "def67890-full-uuid-2",
                },
            ),
            patch(
                "app.services.memory.session_analysis.get_session_group_id",
                new_callable=AsyncMock,
                return_value="project-test",
            ),
            patch(
                "app.services.memory.session_analysis.get_cited_memories",
                new_callable=AsyncMock,
                return_value=["abc12345-full-uuid-1"],
            ),
            patch(
                "app.services.memory.session_analysis.track_referenced_batch",
                new_callable=AsyncMock,
            ) as mock_track,
            patch(
                "app.services.memory.session_analysis.store_cite_event",
                new_callable=AsyncMock,
            ) as mock_store,
            patch(
                "app.services.memory.session_analysis.update_citation_metrics",
                new_callable=AsyncMock,
                return_value=1,
            ) as mock_metrics,
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
                citation_prefixes=["abc12345", "def67890"],
            )

            assert result.citations_found == 2
            assert result.citations_credited == 1
            mock_track.assert_awaited_once_with(["def67890-full-uuid-2"])
            mock_store.assert_awaited_once_with(
                "test-session", ["def67890-full-uuid-2"]
            )
            mock_metrics.assert_awaited_once_with(
                session_id="test-session",
                memories_cited=["abc12345-full-uuid-1", "def67890-full-uuid-2"],
            )

    @pytest.mark.asyncio
    async def test_analyze_session_extracts_artifacts_from_transcript_path(self, tmp_path: Path) -> None:
        """transcript_path fallback extracts citations, feedback, and summary tags."""
        transcript = tmp_path / "codex-session.jsonl"
        transcript.write_text(
            "\n".join(
                [
                    (
                        '{"type":"response_item","payload":{"type":"message","role":"assistant",'
                        '"content":[{"type":"output_text","text":"Applied: [M:abc12345] '
                        '[[F:idea:ah.hooks:add codex transcript support]]"}]}}'
                    ),
                    (
                        '{"type":"response_item","payload":{"type":"message","role":"assistant",'
                        '"content":[{"type":"output_text","text":"[[S:completed:wired codex transcript parsing]]"}]}}'
                    ),
                ]
            )
        )

        with (
            patch(
                "app.services.memory.session_analysis.resolve_full_uuids",
                new_callable=AsyncMock,
                return_value={"abc12345": "abc12345-full"},
            ) as mock_resolve,
            patch(
                "app.services.memory.session_analysis.get_session_group_id",
                new_callable=AsyncMock,
                return_value="global",
            ),
            patch(
                "app.services.memory.session_analysis.track_referenced_batch",
                new_callable=AsyncMock,
            ),
            patch(
                "app.services.memory.session_analysis.store_cite_event",
                new_callable=AsyncMock,
            ),
            patch(
                "app.services.memory.session_analysis.update_citation_metrics",
                new_callable=AsyncMock,
                return_value=1,
            ),
            patch(
                "app.services.memory.session_analysis._process_feedback_tags",
                new_callable=AsyncMock,
                return_value=1,
            ) as mock_feedback,
            patch(
                "app.services.memory.session_analysis._process_summary_tags",
                new_callable=AsyncMock,
                return_value=True,
            ) as mock_summary,
        ):
            result = await analyze_session(
                session_id="test-session",
                transcript_path=str(transcript),
            )

        assert result.citations_found == 1
        assert result.feedback_created == 1
        assert result.summary_stored is True
        mock_resolve.assert_called_once_with(["abc12345"], group_id="global")
        mock_feedback.assert_called_once_with(
            "test-session",
            ["[[F:idea:ah.hooks:add codex transcript support]]"],
        )
        mock_summary.assert_called_once_with(
            "test-session",
            ["[[S:completed:wired codex transcript parsing]]"],
            None,
            None,
            False,
        )

    @pytest.mark.asyncio
    async def test_analyze_session_extracts_summary_tags_from_events(self) -> None:
        """Event-backed analysis can persist inline summary tags without transcript rescans."""
        with (
            patch(
                "app.services.memory.session_analysis.extract_citations_from_events",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch(
                "app.services.memory.session_analysis.extract_summary_tags_from_events",
                new_callable=AsyncMock,
                return_value=["[[S:completed:normalized events finalized cleanly]]"],
            ),
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
            result = await analyze_session(session_id="test-session")

        assert result.citations_found == 0
        assert result.summary_stored is True
        mock_summary.assert_called_once_with(
            "test-session",
            ["[[S:completed:normalized events finalized cleanly]]"],
            None,
            None,
            False,
        )

    @pytest.mark.asyncio
    async def test_analyze_session_uses_persisted_summary_context(self, tmp_path: Path) -> None:
        """Stored summary_context lets replay analysis recover transcript artifacts."""
        transcript = tmp_path / "codex-session.jsonl"
        transcript.write_text(
            '{"type":"response_item","payload":{"type":"message","role":"assistant",'
            '"content":[{"type":"output_text","text":"Applied: [M:abc12345] '
            '[[F:praise:ah.memory:replay worked]] [[S:completed:replayed analysis]]"}]}}'
        )

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = {
            "summary_context": {
                "transcript_path": str(transcript),
                "git_context": "abc1234 feat: replay",
                "branch": "main",
            }
        }
        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result
        mock_factory = MagicMock()
        mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_factory.return_value.__aexit__ = AsyncMock(return_value=None)

        with (
            patch(
                "app.services.memory.session_analysis._get_session_factory",
                return_value=mock_factory,
            ),
            patch(
                "app.services.memory.session_analysis.resolve_full_uuids",
                new_callable=AsyncMock,
                return_value={"abc12345": "abc12345-full"},
            ),
            patch(
                "app.services.memory.session_analysis.get_session_group_id",
                new_callable=AsyncMock,
                return_value="global",
            ),
            patch(
                "app.services.memory.session_analysis.track_referenced_batch",
                new_callable=AsyncMock,
            ),
            patch(
                "app.services.memory.session_analysis.store_cite_event",
                new_callable=AsyncMock,
            ),
            patch(
                "app.services.memory.session_analysis.update_citation_metrics",
                new_callable=AsyncMock,
                return_value=1,
            ),
            patch(
                "app.services.memory.session_analysis._process_feedback_tags",
                new_callable=AsyncMock,
                return_value=1,
            ) as mock_feedback,
            patch(
                "app.services.memory.session_analysis._process_summary_tags",
                new_callable=AsyncMock,
                return_value=True,
            ) as mock_summary,
        ):
            result = await analyze_session(session_id="test-session")

        assert result.citations_found == 1
        assert result.feedback_created == 1
        assert result.summary_stored is True
        mock_feedback.assert_called_once_with(
            "test-session",
            ["[[F:praise:ah.memory:replay worked]]"],
        )
        mock_summary.assert_called_once_with(
            "test-session",
            ["[[S:completed:replayed analysis]]"],
            "abc1234 feat: replay",
            "main",
            True,
        )


@pytest.mark.unit
class TestProcessTaskOutcome:
    """Tests for process_task_outcome function."""

    @pytest.mark.asyncio
    async def test_process_task_outcome_success_credits_memories(self) -> None:
        """Successful task credits all loaded memories."""
        with (
            patch(
                "app.services.memory.session_analysis.update_citation_metrics",
                new_callable=AsyncMock,
                return_value=1,
            ),
            patch(
                "app.services.memory.session_analysis.get_memories_loaded",
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
    async def test_process_task_outcome_failure_no_credits(self) -> None:
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
    async def test_process_task_outcome_success_no_loaded_memories(self) -> None:
        """Successful task with no loaded memories credits nothing."""
        with (
            patch(
                "app.services.memory.session_analysis.update_citation_metrics",
                new_callable=AsyncMock,
                return_value=1,
            ),
            patch(
                "app.services.memory.session_analysis.get_memories_loaded",
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
    async def test_find_sessions_for_task_returns_unique_ids(self) -> None:
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
            "app.services.memory.session_queries._get_session_factory",
            return_value=mock_factory,
        ):
            result = await find_sessions_for_task("task-abc")

            assert result == ["session-1", "session-2"]

    @pytest.mark.asyncio
    async def test_find_sessions_fallback_by_project_and_time(self) -> None:
        """Falls back to session lane matching when external_id returns empty."""
        empty_result = MagicMock()
        empty_scalars = MagicMock()
        empty_scalars.all.return_value = []
        empty_result.scalars.return_value = empty_scalars

        fallback_result = MagicMock()
        fallback_scalars = MagicMock()
        fallback_scalars.all.return_value = [
            SimpleNamespace(
                id="session-3",
                external_id=None,
                current_branch=None,
                session_type="claude_code",
                provider_metadata={"repo_root": "/srv/workspaces/lanes/agent-hub/task-abc"},
            ),
            SimpleNamespace(
                id="session-4",
                external_id=None,
                current_branch=None,
                session_type="agent",
                provider_metadata={"cwd": "/srv/workspaces/lanes/agent-hub/task-abc-follow-up"},
            ),
        ]
        fallback_result.scalars.return_value = fallback_scalars

        mock_session = AsyncMock()
        mock_session.execute.side_effect = [empty_result, fallback_result]

        mock_factory = MagicMock()
        mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_factory.return_value.__aexit__ = AsyncMock(return_value=None)

        with patch(
            "app.services.memory.session_queries._get_session_factory",
            return_value=mock_factory,
        ):
            result = await find_sessions_for_task(
                "task-abc",
                project_id="agent-hub",
                started_at="2026-02-10T12:00:00+00:00",
            )

            assert result == ["session-3", "session-4"]
            assert mock_session.execute.call_count == 2

    @pytest.mark.asyncio
    async def test_find_sessions_no_fallback_without_started_at(self) -> None:
        """No fallback when started_at not provided (even with project_id)."""
        empty_result = MagicMock()
        empty_scalars = MagicMock()
        empty_scalars.all.return_value = []
        empty_result.scalars.return_value = empty_scalars

        mock_session = AsyncMock()
        mock_session.execute.return_value = empty_result

        mock_factory = MagicMock()
        mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_factory.return_value.__aexit__ = AsyncMock(return_value=None)

        with patch(
            "app.services.memory.session_queries._get_session_factory",
            return_value=mock_factory,
        ):
            result = await find_sessions_for_task(
                "task-abc", project_id="agent-hub"
            )

            assert result == []
            # Only one query (external_id), no fallback without started_at
            assert mock_session.execute.call_count == 1

    @pytest.mark.asyncio
    async def test_find_sessions_no_fallback_without_project_id(self) -> None:
        """No fallback when project_id not provided."""
        empty_result = MagicMock()
        empty_scalars = MagicMock()
        empty_scalars.all.return_value = []
        empty_result.scalars.return_value = empty_scalars

        mock_session = AsyncMock()
        mock_session.execute.return_value = empty_result

        mock_factory = MagicMock()
        mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_factory.return_value.__aexit__ = AsyncMock(return_value=None)

        with patch(
            "app.services.memory.session_queries._get_session_factory",
            return_value=mock_factory,
        ):
            result = await find_sessions_for_task("task-abc")

            assert result == []
            # Only one query (external_id), no fallback
            assert mock_session.execute.call_count == 1

    @pytest.mark.asyncio
    async def test_find_sessions_skips_fallback_when_external_id_found(self) -> None:
        """Skips fallback when external_id query returns sessions."""
        primary_result = MagicMock()
        primary_scalars = MagicMock()
        primary_scalars.all.return_value = ["session-1"]
        primary_result.scalars.return_value = primary_scalars

        mock_session = AsyncMock()
        mock_session.execute.return_value = primary_result

        mock_factory = MagicMock()
        mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_factory.return_value.__aexit__ = AsyncMock(return_value=None)

        with patch(
            "app.services.memory.session_queries._get_session_factory",
            return_value=mock_factory,
        ):
            result = await find_sessions_for_task(
                "task-abc", project_id="agent-hub"
            )

            assert result == ["session-1"]
            # Only primary query, no fallback needed
            assert mock_session.execute.call_count == 1


@pytest.mark.unit
class TestCitationTracking:
    """Tests for citation tracking in analyze_session.

    Citations only increment referenced_count, not helpful_count.
    Helpful/harmful are reserved for explicit user feedback.
    """

    @pytest.mark.asyncio
    async def test_citations_only_track_referenced_not_helpful(self) -> None:
        """Citations increment referenced_count but NOT helpful_count."""
        resolved = {
            "abc12345": "abc12345-full-uuid-1",
            "def67890": "def67890-full-uuid-2",
        }
        with (
            patch(
                "app.services.memory.session_analysis.resolve_full_uuids",
                new_callable=AsyncMock,
                return_value=resolved,
            ),
            patch(
                "app.services.memory.session_analysis.get_session_group_id",
                new_callable=AsyncMock,
                return_value="global",
            ),
            patch(
                "app.services.memory.session_analysis.track_referenced_batch",
                new_callable=AsyncMock,
            ) as mock_referenced,
            patch(
                "app.services.memory.session_analysis.store_cite_event",
                new_callable=AsyncMock,
            ),
            patch(
                "app.services.memory.session_analysis.update_citation_metrics",
                new_callable=AsyncMock,
                return_value=1,
            ),
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
                citation_prefixes=["abc12345", "def67890"],
            )

            assert result.citations_credited == 2
            mock_referenced.assert_called_once_with(list(resolved.values()))
