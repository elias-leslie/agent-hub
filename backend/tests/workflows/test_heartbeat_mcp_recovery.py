"""Tests for MCP 'Stream closed' recovery in heartbeat post-processing.

Covers:
- dispatch_agent fire-and-forget via Hatchet wake
- _retry_failed_mcp_tools retrying write_journal and log_agent_performance
- _auto_journal_if_needed detecting "Stream closed" failures
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.workflows._heartbeat_postprocess import (
    _auto_journal_if_needed,
    _retry_failed_mcp_tools,
)


def _mock_async_session(mock_db):
    """Create a mock async_session context manager yielding mock_db."""

    @asynccontextmanager
    async def _session():
        yield mock_db

    return _session


def _make_fetchall_result(rows):
    """Create a mock DB result that returns rows from fetchall()."""
    mock_result = MagicMock()
    mock_result.fetchall.return_value = rows
    return mock_result


def _make_fetchone_result(row):
    """Create a mock DB result that returns row from fetchone()."""
    mock_result = MagicMock()
    mock_result.fetchone.return_value = row
    return mock_result


def _make_scalar_result(value):
    """Create a mock DB result for scalar_one_or_none()."""
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = value
    return mock_result


class TestDispatchAgentFireAndForget:
    """Tests for dispatch_agent using Hatchet wake workflow."""

    @pytest.mark.asyncio
    async def test_dispatch_agent_calls_dispatch_wake(self):
        """dispatch_agent resolves agent and calls dispatch_wake, not complete_internal."""
        mock_db = AsyncMock()
        mock_resolved = MagicMock()
        mock_resolved.model = "claude-sonnet-4-5"
        mock_resolved.provider = "claude"
        mock_resolved.agent.temperature = 0.7

        with (
            patch("app.db.async_session", _mock_async_session(mock_db)),
            patch(
                "app.services.agent_routing_utils.resolve_agent",
                new_callable=AsyncMock,
                return_value=mock_resolved,
            ),
            patch(
                "app.workflows.persona_wake.dispatch_wake",
            ) as mock_wake,
        ):
            from app.services.tools._executor_consultation import dispatch_agent

            result = await dispatch_agent("summitflow", "git-agent", "Fix the bug")

        mock_wake.assert_called_once_with(
            agent_slug="git-agent",
            model="claude-sonnet-4-5",
            provider="claude",
            temperature=0.7,
            prompt="Fix the bug",
            project_id="summitflow",
            event_type="dispatch",
            max_turns=25,
        )
        assert "Dispatched git-agent" in result
        assert "activity" in result

    @pytest.mark.asyncio
    async def test_dispatch_agent_does_not_call_complete_internal(self):
        """dispatch_agent must NOT call complete_internal (the whole point of this fix)."""
        mock_db = AsyncMock()
        mock_resolved = MagicMock()
        mock_resolved.model = "claude-sonnet-4-5"
        mock_resolved.provider = "claude"
        mock_resolved.agent.temperature = 0.7

        with (
            patch("app.db.async_session", _mock_async_session(mock_db)),
            patch(
                "app.services.agent_routing_utils.resolve_agent",
                new_callable=AsyncMock,
                return_value=mock_resolved,
            ),
            patch("app.workflows.persona_wake.dispatch_wake"),
            patch(
                "app.api.complete.core.complete_internal",
                new_callable=AsyncMock,
            ) as mock_complete,
        ):
            from app.services.tools._executor_consultation import dispatch_agent

            await dispatch_agent("summitflow", "git-agent", "Fix the bug")

        mock_complete.assert_not_called()

    @pytest.mark.asyncio
    async def test_dispatch_agent_no_project_id(self):
        """dispatch_agent returns error when project_id is None."""
        from app.services.tools._executor_consultation import dispatch_agent

        result = await dispatch_agent(None, "git-agent", "Fix the bug")
        assert "error" in result.lower()
        assert "project_id" in result.lower()


class TestRetryFailedMcpTools:
    """Tests for _retry_failed_mcp_tools."""

    @pytest.mark.asyncio
    async def test_retries_write_journal(self):
        """Retries write_journal when 'Stream closed' detected."""
        mock_db = AsyncMock()
        # First call: find failures
        failures_result = _make_fetchall_result([("mcp__agent-hub__write_journal", 10)])
        # Second call: find tool_use args
        tool_use_row = MagicMock()
        tool_use_row.tool_input = {"content": "My observation", "entry_type": "observation"}
        use_result = _make_fetchone_result(tool_use_row)

        mock_db.execute = AsyncMock(side_effect=[failures_result, use_result])

        with (
            patch("app.db.async_session", _mock_async_session(mock_db)),
            patch(
                "app.services.tools._executor_persona.write_journal",
                new_callable=AsyncMock,
                return_value="Journal entry recorded (observation)",
            ) as mock_journal,
        ):
            retried = await _retry_failed_mcp_tools("sess-123")

        assert retried == 1
        mock_journal.assert_awaited_once_with(
            content="My observation", entry_type="observation",
        )

    @pytest.mark.asyncio
    async def test_retries_log_agent_performance(self):
        """Retries log_agent_performance when 'Stream closed' detected."""
        mock_db = AsyncMock()
        failures_result = _make_fetchall_result([("mcp__agent-hub__log_agent_performance", 20)])
        tool_use_row = MagicMock()
        tool_use_row.tool_input = {
            "agent_slug": "git-agent",
            "model_id": "claude-sonnet-4-5",
            "feedback_type": "praise",
            "content": "Fast execution",
        }
        use_result = _make_fetchone_result(tool_use_row)

        mock_db.execute = AsyncMock(side_effect=[failures_result, use_result])

        with (
            patch("app.db.async_session", _mock_async_session(mock_db)),
            patch(
                "app.services.tools._executor_performance.log_agent_performance",
                new_callable=AsyncMock,
                return_value="Performance logged",
            ) as mock_perf,
        ):
            retried = await _retry_failed_mcp_tools("sess-123")

        assert retried == 1
        mock_perf.assert_awaited_once_with(
            agent_slug="git-agent",
            model_id="claude-sonnet-4-5",
            feedback_type="praise",
            content="Fast execution",
        )

    @pytest.mark.asyncio
    async def test_skips_unknown_tools(self):
        """Unknown tools are logged but not retried."""
        mock_db = AsyncMock()
        failures_result = _make_fetchall_result([("mcp__agent-hub__unknown_tool", 5)])
        mock_db.execute = AsyncMock(return_value=failures_result)

        with patch("app.db.async_session", _mock_async_session(mock_db)):
            retried = await _retry_failed_mcp_tools("sess-123")

        assert retried == 0

    @pytest.mark.asyncio
    async def test_no_failures_returns_zero(self):
        """Returns 0 immediately when no 'Stream closed' failures found."""
        mock_db = AsyncMock()
        failures_result = _make_fetchall_result([])
        mock_db.execute = AsyncMock(return_value=failures_result)

        with patch("app.db.async_session", _mock_async_session(mock_db)):
            retried = await _retry_failed_mcp_tools("sess-123")

        assert retried == 0

    @pytest.mark.asyncio
    async def test_handles_missing_tool_use_args(self):
        """Skips retry when tool_use event not found (no args to retry with)."""
        mock_db = AsyncMock()
        failures_result = _make_fetchall_result([("mcp__agent-hub__write_journal", 10)])
        use_result = _make_fetchone_result(None)  # No tool_use found
        mock_db.execute = AsyncMock(side_effect=[failures_result, use_result])

        with patch("app.db.async_session", _mock_async_session(mock_db)):
            retried = await _retry_failed_mcp_tools("sess-123")

        assert retried == 0

    @pytest.mark.asyncio
    async def test_handles_retry_exception(self):
        """Continues after individual retry failure."""
        mock_db = AsyncMock()
        # Two failures: first will raise, second should still succeed
        failures_result = _make_fetchall_result([
            ("mcp__agent-hub__write_journal", 10),
            ("mcp__agent-hub__write_journal", 20),
        ])
        tool_use_row1 = MagicMock()
        tool_use_row1.tool_input = {"content": "Entry 1", "entry_type": "observation"}
        tool_use_row2 = MagicMock()
        tool_use_row2.tool_input = {"content": "Entry 2", "entry_type": "decision"}
        use_result1 = _make_fetchone_result(tool_use_row1)
        use_result2 = _make_fetchone_result(tool_use_row2)

        mock_db.execute = AsyncMock(side_effect=[failures_result, use_result1, use_result2])

        call_count = 0

        async def write_journal_side_effect(content, entry_type):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("DB connection lost")
            return "Journal entry recorded"

        with (
            patch("app.db.async_session", _mock_async_session(mock_db)),
            patch(
                "app.services.tools._executor_persona.write_journal",
                new_callable=AsyncMock,
                side_effect=write_journal_side_effect,
            ),
        ):
            retried = await _retry_failed_mcp_tools("sess-123")

        assert retried == 1  # Only the second one succeeded


    @pytest.mark.asyncio
    async def test_retries_dispatch_agent(self):
        """Retries dispatch_agent when 'Stream closed' detected."""
        mock_db = AsyncMock()
        failures_result = _make_fetchall_result([("mcp__agent-hub__dispatch_agent", 80)])
        tool_use_row = MagicMock()
        tool_use_row.tool_input = {
            "agent_slug": "git-agent",
            "task": "Fix the biome thread bug",
            "project_id": "summitflow",
        }
        use_result = _make_fetchone_result(tool_use_row)

        mock_db.execute = AsyncMock(side_effect=[failures_result, use_result])

        with (
            patch("app.db.async_session", _mock_async_session(mock_db)),
            patch(
                "app.services.tools._executor_consultation.dispatch_agent",
                new_callable=AsyncMock,
                return_value="Dispatched git-agent — session will appear in activity when complete.",
            ) as mock_dispatch,
        ):
            retried = await _retry_failed_mcp_tools("sess-123")

        assert retried == 1
        mock_dispatch.assert_awaited_once_with(
            project_id="summitflow",
            agent_slug="git-agent",
            task="Fix the biome thread bug",
            max_turns=25,
        )


class TestAutoJournalStreamClosedDetection:
    """Tests for _auto_journal_if_needed with 'Stream closed' detection."""

    @pytest.mark.asyncio
    async def test_detects_stream_closed_and_auto_journals(self):
        """When write_journal tool_use exists but got 'Stream closed', auto-journal fires."""
        mock_db = AsyncMock()
        # First query: write_journal tool_use exists
        tool_use_result = _make_scalar_result("some-event-id")
        # Second query: "Stream closed" failure found
        stream_closed_result = _make_scalar_result(1)
        mock_db.execute = AsyncMock(side_effect=[tool_use_result, stream_closed_result])

        with (
            patch("app.db.async_session", _mock_async_session(mock_db)),
            patch(
                "app.services.tools._executor_persona.write_journal",
                new_callable=AsyncMock,
                return_value="Journal entry recorded (observation)",
            ) as mock_journal,
        ):
            result = await _auto_journal_if_needed(
                "sess-1", "HEARTBEAT_OK — Normal operations.", None,
            )

        assert result is True
        mock_journal.assert_awaited_once()
        assert "[auto]" in mock_journal.call_args[0][0]

    @pytest.mark.asyncio
    async def test_skips_when_journal_succeeded(self):
        """When write_journal succeeded (no Stream closed), auto-journal is skipped."""
        mock_db = AsyncMock()
        # First query: write_journal tool_use exists
        tool_use_result = _make_scalar_result("some-event-id")
        # Second query: no "Stream closed" failure
        no_failure_result = _make_scalar_result(None)
        mock_db.execute = AsyncMock(side_effect=[tool_use_result, no_failure_result])

        with patch("app.db.async_session", _mock_async_session(mock_db)):
            result = await _auto_journal_if_needed(
                "sess-1", "HEARTBEAT_OK — Normal operations.", None,
            )

        assert result is False
