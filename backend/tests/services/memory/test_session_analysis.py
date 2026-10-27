"""Tests for session analysis service module."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
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

_MODULE = "app.services.memory.session_analysis"
_DEFAULTS: dict[str, object] = {
    "get_session_group_id": "global",
    "get_cited_memories": [],
    "track_referenced_batch": None,
    "store_cite_event": None,
    "update_citation_metrics": 1,
    "_process_summary_tags": False,
}


@contextmanager
def _patched(**returns: object) -> Iterator[dict[str, AsyncMock]]:
    """Patch analyze_session collaborators with AsyncMocks; yield them by name."""
    with ExitStack() as stack:
        mocks = {
            name: stack.enter_context(
                patch(f"{_MODULE}.{name}", new_callable=AsyncMock, return_value=value)
            )
            for name, value in {**_DEFAULTS, **returns}.items()
        }
        yield mocks


@pytest.mark.unit
class TestAnalyzeSession:
    """Tests for analyze_session function."""

    @pytest.mark.asyncio
    async def test_analyze_session_with_cc_prefixes_credits_resolved(self) -> None:
        """CC path: provided prefixes are resolved and credited."""
        with _patched(
            resolve_full_uuids={"abc12345": "abc12345-full-uuid-1", "def67890": "def67890-full-uuid-2"},
            get_session_group_id="project-test",
        ) as mocks:
            mock_resolve = mocks["resolve_full_uuids"]
            mock_track = mocks["track_referenced_batch"]
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
        with _patched(
            extract_citations_from_events=["abc12345"],
            resolve_full_uuids={"abc12345": "abc12345-full-uuid"},
        ) as mocks:
            mock_extract = mocks["extract_citations_from_events"]
            result = await analyze_session(session_id="test-session")

            assert result.citations_found == 1
            assert result.citations_credited == 1
            mock_extract.assert_called_once_with("test-session")

    @pytest.mark.asyncio
    async def test_analyze_session_empty_prefixes_returns_zero(self) -> None:
        """Empty citation list returns zero counts."""
        with patch(
            "app.services.memory.session_analysis._process_summary_tags",
            new_callable=AsyncMock,
            return_value=False,
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
        with _patched(resolve_full_uuids={}):
            result = await analyze_session(
                session_id="test-session",
                citation_prefixes=["deadbeef"],
            )

            assert result.citations_found == 1
            assert result.citations_credited == 0

    @pytest.mark.asyncio
    async def test_analyze_session_truncates_long_prefixes(self) -> None:
        """Prefixes longer than 8 chars are truncated to 8."""
        with _patched(resolve_full_uuids={"abc12345": "abc12345-full"}) as mocks:
            mock_resolve = mocks["resolve_full_uuids"]
            await analyze_session(
                session_id="test-session",
                citation_prefixes=["abc12345extra"],
            )

            # Should truncate to 8 chars
            mock_resolve.assert_called_once_with(["abc12345"], group_id="global")

    @pytest.mark.asyncio
    async def test_analyze_session_skips_already_credited_citations(self) -> None:
        """Re-analyzing a session should not double-credit existing citations."""
        with _patched(
            resolve_full_uuids={
                "abc12345": "abc12345-full-uuid-1",
                "def67890": "def67890-full-uuid-2",
            },
            get_session_group_id="project-test",
            get_cited_memories=["abc12345-full-uuid-1"],
        ) as mocks:
            mock_track = mocks["track_referenced_batch"]
            mock_store = mocks["store_cite_event"]
            mock_metrics = mocks["update_citation_metrics"]
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
        """transcript_path fallback extracts citations and summary tags."""
        transcript = tmp_path / "codex-session.jsonl"
        transcript.write_text(
            "\n".join(
                [
                    (
                        '{"type":"response_item","payload":{"type":"message","role":"assistant",'
                        '"content":[{"type":"output_text","text":"Applied: [M:abc12345]"}]}}'
                    ),
                    (
                        '{"type":"response_item","payload":{"type":"message","role":"assistant",'
                        '"content":[{"type":"output_text","text":"[[S:completed:wired codex transcript parsing]]"}]}}'
                    ),
                ]
            )
        )

        with _patched(
            resolve_full_uuids={"abc12345": "abc12345-full"},
            _process_summary_tags=True,
        ) as mocks:
            mock_resolve = mocks["resolve_full_uuids"]
            mock_summary = mocks["_process_summary_tags"]
            result = await analyze_session(
                session_id="test-session",
                transcript_path=str(transcript),
            )

        assert result.citations_found == 1
        assert result.summary_stored is True
        mock_resolve.assert_called_once_with(["abc12345"], group_id="global")
        mock_summary.assert_called_once_with(
            "test-session",
            ["[[S:completed:wired codex transcript parsing]]"],
            None,
            None,
        )

    @pytest.mark.asyncio
    async def test_analyze_session_uses_persisted_summary_context(self, tmp_path: Path) -> None:
        """Stored summary_context lets replay analysis recover transcript artifacts."""
        transcript = tmp_path / "codex-session.jsonl"
        transcript.write_text(
            '{"type":"response_item","payload":{"type":"message","role":"assistant",'
            '"content":[{"type":"output_text","text":"Applied: [M:abc12345] '
            '[[S:completed:replayed analysis]]"}]}}'
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
            patch(f"{_MODULE}._get_session_factory", return_value=mock_factory),
            _patched(
                resolve_full_uuids={"abc12345": "abc12345-full"},
                _process_summary_tags=True,
            ) as mocks,
        ):
            mock_summary = mocks["_process_summary_tags"]
            result = await analyze_session(session_id="test-session")

        assert result.citations_found == 1
        assert result.summary_stored is True
        mock_summary.assert_called_once_with(
            "test-session",
            ["[[S:completed:replayed analysis]]"],
            "abc1234 feat: replay",
            "main",
        )


@pytest.mark.unit
class TestProcessTaskOutcome:
    """Tests for process_task_outcome function."""

    @pytest.mark.asyncio
    async def test_process_task_outcome_success_credits_memories(self) -> None:
        """Successful task credits all loaded memories."""
        with _patched(
            get_memories_loaded=["uuid-1", "uuid-2", "uuid-3"], track_success_batch=None
        ) as mocks:
            mock_track_success = mocks["track_success_batch"]
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
        with _patched():
            result = await process_task_outcome(
                session_id="test-session",
                succeeded=False,
            )

            assert result.task_succeeded is False
            assert result.memories_credited == 0

    @pytest.mark.asyncio
    async def test_process_task_outcome_success_no_loaded_memories(self) -> None:
        """Successful task with no loaded memories credits nothing."""
        with _patched(get_memories_loaded=[]):
            result = await process_task_outcome(
                session_id="test-session",
                succeeded=True,
            )

            assert result.memories_credited == 0


@pytest.mark.unit
class TestFindSessionsForTask:
    """Tests for find_sessions_for_task function."""

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
                provider_metadata={"repo_root": "/srv/workspaces/projects/agent-hub/task-abc"},
            ),
            SimpleNamespace(
                id="session-4",
                external_id=None,
                current_branch=None,
                session_type="agent",
                provider_metadata={"cwd": "/srv/workspaces/projects/agent-hub/task-abc-follow-up"},
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


