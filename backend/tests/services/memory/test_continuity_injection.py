"""Tests for continuity injection with branch scoping, outcome filtering, and staleness."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.memory.continuity_injector import (
    STALENESS_HOURS,
    ContinuityContext,
    _format_recent_activity,
    build_continuity_context,
)


def _make_summary(
    session_id: str = "test-session",
    agent_slug: str = "coder",
    summary: str = "Fixed auth bug",
    outcome: str = "completed",
    branch: str | None = "main",
    is_worktree: bool = False,
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
        "created_at": datetime.now(UTC) - timedelta(hours=hours_ago),
    }


@pytest.mark.unit
class TestFormatRecentActivity:
    """Tests for _format_recent_activity formatting."""

    def test_empty_summaries_returns_empty(self) -> None:
        """No summaries produces empty string."""
        assert _format_recent_activity([]) == ""

    def test_formats_basic_summary(self) -> None:
        """Formats a single summary with agent and time."""
        result = _format_recent_activity([_make_summary(hours_ago=2.0)])
        assert "## Recent Activity" in result
        assert "coder:" in result
        assert "Fixed auth bug" in result
        assert "[2h ago]" in result

    def test_failed_outcome_gets_prefix(self) -> None:
        """Failed sessions are prefixed with FAILED:."""
        result = _format_recent_activity([
            _make_summary(outcome="failed", summary="Permission denied"),
        ])
        assert "FAILED: Permission denied" in result

    def test_completed_outcome_no_prefix(self) -> None:
        """Completed sessions get no prefix."""
        result = _format_recent_activity([
            _make_summary(outcome="completed", summary="All good"),
        ])
        assert "FAILED:" not in result
        assert "All good" in result

    def test_minutes_time_label(self) -> None:
        """Recent summaries show minutes."""
        result = _format_recent_activity([_make_summary(hours_ago=0.5)])
        assert "30m ago" in result

    def test_hours_time_label(self) -> None:
        """Older summaries show hours."""
        result = _format_recent_activity([_make_summary(hours_ago=5.0)])
        assert "5h ago" in result

    def test_yesterday_time_label(self) -> None:
        """Day-old summaries show 'yesterday'."""
        result = _format_recent_activity([_make_summary(hours_ago=30.0)])
        assert "yesterday" in result

    def test_days_time_label(self) -> None:
        """Multi-day summaries show days."""
        result = _format_recent_activity([_make_summary(hours_ago=72.0)])
        assert "3d ago" in result

    def test_multiple_summaries_ordered(self) -> None:
        """Multiple summaries appear in list."""
        summaries = [
            _make_summary(agent_slug="coder", summary="First task", hours_ago=1.0),
            _make_summary(agent_slug="refactor", summary="Second task", hours_ago=5.0),
        ]
        result = _format_recent_activity(summaries)
        lines = result.split("\n")
        assert len(lines) == 3  # header + 2 entries
        assert "coder:" in lines[1]
        assert "refactor:" in lines[2]

    def test_null_agent_slug_uses_session(self) -> None:
        """Null agent_slug falls back to 'session'."""
        result = _format_recent_activity([_make_summary(agent_slug=None)])
        assert "session:" in result

    def test_token_budget_truncates_entries(self) -> None:
        """Entries are dropped when token budget is exceeded."""
        summaries = [
            _make_summary(agent_slug="coder", summary="A" * 100, hours_ago=1.0),
            _make_summary(agent_slug="refactor", summary="B" * 100, hours_ago=2.0),
            _make_summary(agent_slug="reviewer", summary="C" * 100, hours_ago=3.0),
        ]
        # Very small budget: header (~20 chars) + 1 entry (~120 chars) = ~140 chars = ~35 tokens
        result = _format_recent_activity(summaries, max_tokens=40)
        lines = result.strip().split("\n")
        # Should have header + 1 entry, second truncated by budget
        assert lines[0] == "## Recent Activity"
        assert len(lines) == 2
        assert "A" * 100 in lines[1]

    def test_token_budget_always_includes_first_entry(self) -> None:
        """At least one entry is included even if it exceeds budget."""
        summaries = [_make_summary(summary="X" * 200)]
        result = _format_recent_activity(summaries, max_tokens=10)
        lines = result.strip().split("\n")
        assert len(lines) == 2  # header + 1 entry always included

    def test_large_token_budget_includes_all(self) -> None:
        """Large budget includes all entries."""
        summaries = [
            _make_summary(agent_slug="a", summary="Task 1", hours_ago=1.0),
            _make_summary(agent_slug="b", summary="Task 2", hours_ago=2.0),
            _make_summary(agent_slug="c", summary="Task 3", hours_ago=3.0),
        ]
        result = _format_recent_activity(summaries, max_tokens=1000)
        lines = result.strip().split("\n")
        assert len(lines) == 4  # header + 3 entries


@pytest.mark.unit
class TestBuildContinuityContext:
    """Tests for build_continuity_context with poisoning protection."""

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_summaries(self) -> None:
        """Returns empty ContinuityContext when no summaries found."""
        with _mock_db_query([]):
            ctx = await build_continuity_context(project_id="test-project")

        assert ctx.markdown == ""
        assert ctx.session_count == 0

    @pytest.mark.asyncio
    async def test_returns_summaries_for_project(self) -> None:
        """Returns summaries when available."""
        rows = [_mock_row("s1", "coder", "Fixed bug", "completed", "main", False)]
        with _mock_db_query(rows):
            ctx = await build_continuity_context(project_id="test-project")

        assert ctx.session_count == 1
        assert "Fixed bug" in ctx.markdown
        assert "## Recent Activity" in ctx.markdown

    @pytest.mark.asyncio
    async def test_passes_branch_to_query(self) -> None:
        """Passes current_branch to the query for branch scoping."""
        rows = [_mock_row("s1", "coder", "On feature branch", "completed", "feature/auth", False)]
        with _mock_db_query(rows):
            ctx = await build_continuity_context(
                project_id="test-project",
                current_branch="feature/auth",
            )

        assert ctx.session_count == 1
        assert "On feature branch" in ctx.markdown


def _mock_row(
    session_id: str,
    agent_slug: str,
    summary: str,
    outcome: str,
    branch: str | None,
    is_worktree: bool,
) -> MagicMock:
    """Create a mock database Row."""
    row = MagicMock()
    row.id = session_id
    row.agent_slug = agent_slug
    row.summary_oneliner = summary
    row.summary_outcome = outcome
    row.summary_branch = branch
    row.summary_is_worktree = is_worktree
    row.created_at = datetime.now(UTC) - timedelta(hours=2)
    return row


def _mock_db_query(rows: list[MagicMock]) -> Any:
    """Context manager that mocks the DB session factory for continuity queries."""
    mock_db = AsyncMock()

    result = MagicMock()
    result.all.return_value = rows

    mock_db.execute = AsyncMock(return_value=result)

    mock_factory = MagicMock()
    mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_db)
    mock_factory.return_value.__aexit__ = AsyncMock(return_value=None)

    return patch(
        "app.services.memory.continuity_injector._get_session_factory",
        return_value=mock_factory,
    )
