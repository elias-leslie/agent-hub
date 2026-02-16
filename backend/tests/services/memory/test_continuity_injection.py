"""Tests for continuity injection with branch scoping, outcome filtering, and staleness."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.memory.continuity_format import format_recent_activity
from app.services.memory.continuity_injector import build_continuity_context
from app.services.memory.continuity_query import query_recent_summaries


def _make_summary(
    session_id: str = "test-session",
    agent_slug: str | None = "coder",
    summary: str = "Fixed auth bug",
    outcome: str = "completed",
    branch: str | None = "main",
    is_worktree: bool = False,
    git_digest: str | None = None,
    hours_ago: float = 2.0,
) -> dict[str, Any]:
    """Create a mock summary dict."""
    return {
        "session_id": session_id,
        "agent_slug": agent_slug,
        "summary": summary,
        "outcome": outcome,
        "branch": branch,
        "is_worktree": is_worktree,
        "git_digest": git_digest,
        "created_at": datetime.now(UTC) - timedelta(hours=hours_ago),
    }


@pytest.mark.unit
class TestFormatRecentActivity:
    """Tests for format_recent_activity formatting."""

    def test_empty_summaries_returns_empty(self) -> None:
        """No summaries produces empty string."""
        assert format_recent_activity([]) == ""

    def test_formats_basic_summary(self) -> None:
        """Formats a single summary with agent and time."""
        result = format_recent_activity([_make_summary(hours_ago=2.0)])
        assert "## Recent Activity" in result
        assert "coder:" in result
        assert "Fixed auth bug" in result
        assert "[2h ago]" in result

    def test_failed_outcome_gets_prefix(self) -> None:
        """Failed sessions are prefixed with FAILED:."""
        result = format_recent_activity([
            _make_summary(outcome="failed", summary="Permission denied"),
        ])
        assert "FAILED: Permission denied" in result

    def test_completed_outcome_no_prefix(self) -> None:
        """Completed sessions get no prefix."""
        result = format_recent_activity([
            _make_summary(outcome="completed", summary="All good"),
        ])
        assert "FAILED:" not in result
        assert "All good" in result

    def test_minutes_time_label(self) -> None:
        """Recent summaries show minutes."""
        result = format_recent_activity([_make_summary(hours_ago=0.5)])
        assert "30m ago" in result

    def test_hours_time_label(self) -> None:
        """Older summaries show hours."""
        result = format_recent_activity([_make_summary(hours_ago=5.0)])
        assert "5h ago" in result

    def test_yesterday_time_label(self) -> None:
        """Day-old summaries show 'yesterday'."""
        result = format_recent_activity([_make_summary(hours_ago=30.0)])
        assert "yesterday" in result

    def test_days_time_label(self) -> None:
        """Multi-day summaries show days."""
        result = format_recent_activity([_make_summary(hours_ago=72.0)])
        assert "3d ago" in result

    def test_multiple_summaries_ordered(self) -> None:
        """Multiple summaries appear in list."""
        summaries = [
            _make_summary(agent_slug="coder", summary="First task", hours_ago=1.0),
            _make_summary(agent_slug="refactor", summary="Second task", hours_ago=5.0),
        ]
        result = format_recent_activity(summaries)
        lines = result.split("\n")
        assert len(lines) == 3  # header + 2 entries
        assert "coder:" in lines[1]
        assert "refactor:" in lines[2]

    def test_null_agent_slug_uses_session(self) -> None:
        """Null agent_slug falls back to 'session'."""
        result = format_recent_activity([_make_summary(agent_slug=None)])
        assert "session:" in result

    def test_git_digest_appended(self) -> None:
        """Git digest is appended to summary when available."""
        result = format_recent_activity([
            _make_summary(git_digest="adapters/, credentials UI"),
        ])
        assert "| Changed: adapters/, credentials UI" in result

    def test_no_git_digest_no_suffix(self) -> None:
        """No 'Changed:' suffix when git_digest is None."""
        result = format_recent_activity([_make_summary(git_digest=None)])
        assert "Changed:" not in result


@pytest.mark.unit
class TestBuildContinuityContext:
    """Tests for build_continuity_context with segment-based queries."""

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_summaries(self) -> None:
        """Returns empty ContinuityContext when no summaries found."""
        with _mock_db_query(segment_rows=[], legacy_rows=[]):
            ctx = await build_continuity_context(
                project_id="test-project",
                include_cross_project=False,
                include_live_sessions=False,
            )

        assert ctx.markdown == ""
        assert ctx.session_count == 0

    @pytest.mark.asyncio
    async def test_returns_summaries_from_segments(self) -> None:
        """Returns summaries from segment rows when available."""
        rows = [_mock_segment_row("s1", "coder", "Fixed bug", "completed", "main", False)]
        with _mock_db_query(segment_rows=rows, legacy_rows=[]):
            ctx = await build_continuity_context(
                project_id="test-project",
                include_cross_project=False,
                include_live_sessions=False,
            )

        assert ctx.session_count == 1
        assert "Fixed bug" in ctx.markdown
        assert "## Recent Activity" in ctx.markdown

    @pytest.mark.asyncio
    async def test_passes_branch_to_query(self) -> None:
        """Passes current_branch to the query for branch scoping."""
        rows = [_mock_segment_row("s1", "coder", "On feature branch", "completed", "feature/auth", False)]
        with _mock_db_query(segment_rows=rows, legacy_rows=[]):
            ctx = await build_continuity_context(
                project_id="test-project",
                current_branch="feature/auth",
                include_cross_project=False,
                include_live_sessions=False,
            )

        assert ctx.session_count == 1
        assert "On feature branch" in ctx.markdown

    @pytest.mark.asyncio
    async def test_falls_back_to_session_columns(self) -> None:
        """Uses session-column fallback when no segments exist (pre-migration)."""
        legacy = [_mock_session_row("s1", "coder", "Legacy summary", "completed", "main", False)]
        with _mock_db_query(segment_rows=[], legacy_rows=legacy):
            ctx = await build_continuity_context(
                project_id="test-project",
                include_cross_project=False,
                include_live_sessions=False,
            )

        assert ctx.session_count == 1
        assert "Legacy summary" in ctx.markdown

    @pytest.mark.asyncio
    async def test_supplements_segments_with_legacy(self) -> None:
        """Combines segment and legacy data when segments < max_sessions."""
        seg = [_mock_segment_row("s1", "coder", "New work", "completed", "main", False)]
        legacy = [_mock_session_row("s2", "refactor", "Old work", "completed", "main", False)]
        with _mock_db_query(segment_rows=seg, legacy_rows=legacy):
            ctx = await build_continuity_context(
                project_id="test-project",
                include_cross_project=False,
                include_live_sessions=False,
            )

        assert ctx.session_count == 2
        assert "New work" in ctx.markdown
        assert "Old work" in ctx.markdown


@pytest.mark.unit
class TestQueryRecentSummaries:
    """Tests for query_recent_summaries combining segments + legacy fallback."""

    @pytest.mark.asyncio
    async def test_multiple_segments_same_session(self) -> None:
        """Two segments for one session appear as separate entries."""
        seg1 = _mock_segment_row("s1", "coder", "Morning work", "completed", "main", False, hours_ago=5.0)
        seg2 = _mock_segment_row("s1", "coder", "Afternoon work", "completed", "main", False, hours_ago=1.0)
        mock_db = _create_mock_db(segment_rows=[seg2, seg1], legacy_rows=[])
        staleness_cutoff = datetime.now(UTC) - timedelta(hours=168)
        summaries = await query_recent_summaries(
            mock_db, "test-project", "main", 5, staleness_cutoff,
        )

        assert len(summaries) == 2
        assert summaries[0]["summary"] == "Afternoon work"  # Most recent first
        assert summaries[1]["summary"] == "Morning work"

    @pytest.mark.asyncio
    async def test_segment_time_uses_segment_created_at(self) -> None:
        """Time labels are based on segment created_at, not session created_at."""
        seg = _mock_segment_row("s1", "coder", "Recent", "completed", "main", False, hours_ago=0.5)
        mock_db = _create_mock_db(segment_rows=[seg], legacy_rows=[])
        staleness_cutoff = datetime.now(UTC) - timedelta(hours=168)
        summaries = await query_recent_summaries(
            mock_db, "test-project", None, 5, staleness_cutoff,
        )

        delta = datetime.now(UTC) - summaries[0]["created_at"]
        assert delta.total_seconds() < 3600  # Within an hour

    @pytest.mark.asyncio
    async def test_empty_segments_falls_back_completely(self) -> None:
        """When no segments exist, returns only legacy session data."""
        legacy = [_mock_session_row("s1", "coder", "Legacy", "completed", "main", False)]
        mock_db = _create_mock_db(segment_rows=[], legacy_rows=legacy)
        staleness_cutoff = datetime.now(UTC) - timedelta(hours=168)
        summaries = await query_recent_summaries(
            mock_db, "test-project", None, 5, staleness_cutoff,
        )

        assert len(summaries) == 1
        assert summaries[0]["summary"] == "Legacy"

    @pytest.mark.asyncio
    async def test_results_sorted_by_created_at_desc(self) -> None:
        """Combined results are sorted by created_at descending."""
        seg = _mock_segment_row("s1", "coder", "Recent segment", "completed", "main", False, hours_ago=1.0)
        legacy = _mock_session_row("s2", "coder", "Older session", "completed", "main", False, hours_ago=10.0)
        mock_db = _create_mock_db(segment_rows=[seg], legacy_rows=[legacy])
        staleness_cutoff = datetime.now(UTC) - timedelta(hours=168)
        summaries = await query_recent_summaries(
            mock_db, "test-project", None, 5, staleness_cutoff,
        )

        assert len(summaries) == 2
        assert summaries[0]["summary"] == "Recent segment"
        assert summaries[1]["summary"] == "Older session"


# ── Mock helpers ─────────────────────────────────────────────────────────


def _mock_segment_row(
    session_id: str,
    agent_slug: str | None,
    summary: str,
    outcome: str,
    branch: str | None,
    is_worktree: bool,
    git_digest: str | None = None,
    hours_ago: float = 2.0,
) -> MagicMock:
    """Create a mock Row matching the segment query's selected columns."""
    row = MagicMock()
    row.session_id = session_id
    row.agent_slug = agent_slug
    row.summary_oneliner = summary
    row.summary_outcome = outcome
    row.summary_branch = branch
    row.summary_is_worktree = is_worktree
    row.summary_git_digest = git_digest
    row.created_at = datetime.now(UTC) - timedelta(hours=hours_ago)
    return row


def _mock_session_row(
    session_id: str,
    agent_slug: str | None,
    summary: str,
    outcome: str,
    branch: str | None,
    is_worktree: bool,
    git_digest: str | None = None,
    hours_ago: float = 2.0,
) -> MagicMock:
    """Create a mock Row matching the session-column query's selected columns."""
    row = MagicMock()
    row.id = session_id
    row.agent_slug = agent_slug
    row.summary_oneliner = summary
    row.summary_outcome = outcome
    row.summary_branch = branch
    row.summary_is_worktree = is_worktree
    row.summary_git_digest = git_digest
    row.created_at = datetime.now(UTC) - timedelta(hours=hours_ago)
    return row


def _create_mock_db(
    segment_rows: list[MagicMock] | None = None,
    legacy_rows: list[MagicMock] | None = None,
) -> AsyncMock:
    """Create a mock DB for direct query_recent_summaries calls.

    Returns a mock db with execute() returning segment then legacy results.
    """
    mock_db = AsyncMock()

    seg_result = MagicMock()
    seg_result.all.return_value = segment_rows or []

    leg_result = MagicMock()
    leg_result.all.return_value = legacy_rows or []

    mock_db.execute = AsyncMock(side_effect=[seg_result, leg_result])
    return mock_db


def _mock_db_query(
    segment_rows: list[MagicMock] | None = None,
    legacy_rows: list[MagicMock] | None = None,
) -> Any:
    """Mock DB factory for build_continuity_context calls.

    Patches _get_session_factory to return a mock async context manager.
    The query pipeline makes two db.execute() calls:
    1. Segment query (query_from_segments)
    2. Session-column query (query_from_session_columns) — only if segments < max_sessions
    """
    mock_db = AsyncMock()

    seg_result = MagicMock()
    seg_result.all.return_value = segment_rows or []

    leg_result = MagicMock()
    leg_result.all.return_value = legacy_rows or []

    mock_db.execute = AsyncMock(side_effect=[seg_result, leg_result])

    mock_factory = MagicMock()
    mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_db)
    mock_factory.return_value.__aexit__ = AsyncMock(return_value=None)

    return patch(
        "app.services.memory.continuity_injector._get_session_factory",
        return_value=mock_factory,
    )
