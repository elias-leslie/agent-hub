"""Tests for MCP 'Stream closed' recovery in heartbeat post-processing.

Covers:
- dispatch_agent fire-and-forget via Hatchet wake
- _retry_failed_mcp_tools retrying log_agent_performance
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.constants.models import CLAUDE_SONNET
from app.workflows._heartbeat_postprocess import (
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
        mock_resolved.model = CLAUDE_SONNET
        mock_resolved.provider = "claude"
        mock_resolved.agent.temperature = 0.7
        mock_resolved.agent.thinking_level = "medium"

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
            model=CLAUDE_SONNET,
            provider="claude",
            temperature=0.7,
            prompt="Fix the bug",
            project_id="summitflow",
            event_type="dispatch",
            thinking_level="medium",
            max_turns=None,
            parent_session_id=None,
            current_branch=None,
            working_dir=None,
        )
        assert "Dispatched git-agent" in result
        assert "heartbeat" in result

    @pytest.mark.asyncio
    async def test_dispatch_agent_forwards_parent_session_id(self):
        """dispatch_agent links wake sessions back to the current parent session."""
        mock_db = AsyncMock()
        mock_resolved = MagicMock()
        mock_resolved.model = "codex/gpt-5.4"
        mock_resolved.provider = "codex"
        mock_resolved.agent.temperature = 0.2
        mock_resolved.agent.thinking_level = "high"

        with (
            patch("app.db.async_session", _mock_async_session(mock_db)),
            patch(
                "app.services.agent_routing_utils.resolve_agent",
                new_callable=AsyncMock,
                return_value=mock_resolved,
            ),
            patch("app.workflows.persona_wake.dispatch_wake") as mock_wake,
        ):
            from app.services.tools._executor_consultation import dispatch_agent

            await dispatch_agent(
                "summitflow",
                "git-agent",
                "Advance the stale task recovery flow.",
                parent_session_id="parent-session-123",
            )

        mock_wake.assert_called_once_with(
            agent_slug="git-agent",
            model="codex/gpt-5.4",
            provider="codex",
            temperature=0.2,
            prompt="Advance the stale task recovery flow.",
            project_id="summitflow",
            event_type="dispatch",
            thinking_level="high",
            max_turns=None,
            parent_session_id="parent-session-123",
            current_branch=None,
            working_dir=None,
        )

    @pytest.mark.asyncio
    async def test_dispatch_agent_forwards_explicit_max_turns(self):
        """Explicit max_turns should override persona-limit resolution."""
        mock_db = AsyncMock()
        mock_resolved = MagicMock()
        mock_resolved.model = "codex/gpt-5.4"
        mock_resolved.provider = "codex"
        mock_resolved.agent.temperature = 0.2
        mock_resolved.agent.thinking_level = "high"

        with (
            patch("app.db.async_session", _mock_async_session(mock_db)),
            patch(
                "app.services.agent_routing_utils.resolve_agent",
                new_callable=AsyncMock,
                return_value=mock_resolved,
            ),
            patch("app.workflows.persona_wake.dispatch_wake") as mock_wake,
        ):
            from app.services.tools._executor_consultation import dispatch_agent

            await dispatch_agent(
                "summitflow",
                "git-agent",
                "Advance the stale task recovery flow.",
                max_turns=87,
            )

        mock_wake.assert_called_once_with(
            agent_slug="git-agent",
            model="codex/gpt-5.4",
            provider="codex",
            temperature=0.2,
            prompt="Advance the stale task recovery flow.",
            project_id="summitflow",
            event_type="dispatch",
            thinking_level="high",
            max_turns=87,
            parent_session_id=None,
            current_branch=None,
            working_dir=None,
        )

    @pytest.mark.asyncio
    async def test_dispatch_agent_does_not_call_complete_internal(self):
        """dispatch_agent must NOT call complete_internal (the whole point of this fix)."""
        mock_db = AsyncMock()
        mock_resolved = MagicMock()
        mock_resolved.model = CLAUDE_SONNET
        mock_resolved.provider = "claude"
        mock_resolved.agent.temperature = 0.7
        mock_resolved.agent.thinking_level = "medium"

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

    @pytest.mark.asyncio
    async def test_dispatch_agent_requires_explicit_mode_for_specialists(self):
        mock_db = AsyncMock()
        mock_resolved = MagicMock()
        mock_resolved.model = CLAUDE_SONNET
        mock_resolved.provider = "claude"
        mock_resolved.agent.temperature = 0.3
        mock_resolved.agent.thinking_level = "medium"

        with (
            patch("app.db.async_session", _mock_async_session(mock_db)),
            patch(
                "app.services.agent_routing_utils.resolve_agent",
                new_callable=AsyncMock,
                return_value=mock_resolved,
            ),
            patch("app.workflows.persona_wake.dispatch_wake") as mock_wake,
        ):
            from app.services.tools._executor_consultation import dispatch_agent

            result = await dispatch_agent(
                "agent-hub",
                "refactor",
                "Refactor the overlap guard.",
            )

        assert "Mode: task" in result
        assert "Mode: campaign" in result
        mock_wake.assert_not_called()

    @pytest.mark.asyncio
    async def test_dispatch_agent_blocks_when_parent_hits_subagent_limit(self):
        mock_db = AsyncMock()
        parent_session = MagicMock()
        parent_session.agent_slug = "persona"
        parent_session.id = "parent-session-123"
        child_one = MagicMock()
        child_one.id = "child-1"
        child_one.project_id = "summitflow"
        child_one.status = "active"
        child_two = MagicMock()
        child_two.id = "child-2"
        child_two.project_id = "summitflow"
        child_two.status = "active"

        mock_db.execute = AsyncMock(
            side_effect=[
                _make_scalar_result(parent_session),
                MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[child_one, child_two])))),
            ]
        )

        parent_resolved = MagicMock()
        parent_resolved.agent.max_subagent_concurrency = 2

        with (
            patch("app.db.async_session", _mock_async_session(mock_db)),
            patch(
                "app.services.agent_routing_utils.resolve_agent",
                new_callable=AsyncMock,
                return_value=parent_resolved,
            ) as mock_resolve,
            patch(
                "app.services.ownership_inventory.query_project_ownership",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch(
                "app.services.ownership_inventory.query_project_active_specialists",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch(
                "app.services.session_live_activity.is_session_actionably_active",
                side_effect=[True, True],
            ),
            patch("app.workflows.persona_wake.dispatch_wake") as mock_wake,
        ):
            from app.services.tools._executor_consultation import dispatch_agent

            result = await dispatch_agent(
                "summitflow",
                "git-agent",
                "Fix the bug",
                parent_session_id="parent-session-123",
            )

        assert "Dispatch blocked for persona" in result
        assert "max_subagent_concurrency=2" in result
        assert mock_resolve.await_count == 1
        mock_wake.assert_not_called()

    @pytest.mark.asyncio
    async def test_dispatch_agent_ignores_non_actionable_children_for_parent_limit(self):
        mock_db = AsyncMock()
        parent_session = MagicMock()
        parent_session.agent_slug = "persona"
        parent_session.id = "parent-session-123"
        stale_child = MagicMock()
        stale_child.id = "child-stale"
        stale_child.project_id = "summitflow"
        stale_child.status = "active"

        mock_db.execute = AsyncMock(
            side_effect=[
                _make_scalar_result(parent_session),
                MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[stale_child])))),
            ]
        )

        parent_resolved = MagicMock()
        parent_resolved.agent.max_subagent_concurrency = 1

        child_resolved = MagicMock()
        child_resolved.model = CLAUDE_SONNET
        child_resolved.provider = "claude"
        child_resolved.agent.temperature = 0.7
        child_resolved.agent.thinking_level = "medium"

        with (
            patch("app.db.async_session", _mock_async_session(mock_db)),
            patch(
                "app.services.agent_routing_utils.resolve_agent",
                new_callable=AsyncMock,
                side_effect=[parent_resolved, child_resolved],
            ),
            patch(
                "app.services.ownership_inventory.query_project_ownership",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch(
                "app.services.ownership_inventory.query_project_active_specialists",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch(
                "app.services.session_live_activity.is_session_actionably_active",
                return_value=False,
            ),
            patch("app.workflows.persona_wake.dispatch_wake") as mock_wake,
        ):
            from app.services.tools._executor_consultation import dispatch_agent

            result = await dispatch_agent(
                "summitflow",
                "git-agent",
                "Fix the bug",
                parent_session_id="parent-session-123",
            )

        assert "Dispatched git-agent" in result
        mock_wake.assert_called_once()

    @pytest.mark.asyncio
    async def test_dispatch_agent_for_task_mode_forwards_lane_metadata(self):
        mock_db = AsyncMock()
        mock_resolved = MagicMock()
        mock_resolved.model = "codex/gpt-5.4"
        mock_resolved.provider = "codex"
        mock_resolved.agent.temperature = 0.2
        mock_resolved.agent.thinking_level = "high"

        fake_plan = MagicMock()
        fake_plan.event_type = "dispatch_task"
        fake_plan.current_branch = "task-12345678/main"
        fake_plan.working_dir = "/tmp/lanes/task-12345678"

        with (
            patch("app.db.async_session", _mock_async_session(mock_db)),
            patch(
                "app.services.agent_routing_utils.resolve_agent",
                new_callable=AsyncMock,
                return_value=mock_resolved,
            ),
            patch(
                "app.services.tools._executor_consultation.prepare_specialist_dispatch",
                new_callable=AsyncMock,
                return_value=fake_plan,
            ),
            patch("app.workflows.persona_wake.dispatch_wake") as mock_wake,
        ):
            from app.services.tools._executor_consultation import dispatch_agent

            await dispatch_agent(
                "agent-hub",
                "debugger",
                "Mode: task\nTask-ID: task-12345678\nTask: Debug the overlap gate.",
                parent_session_id="parent-session-123",
            )

        mock_wake.assert_called_once_with(
            agent_slug="debugger",
            model="codex/gpt-5.4",
            provider="codex",
            temperature=0.2,
            prompt="Mode: task\nTask-ID: task-12345678\nTask: Debug the overlap gate.",
            project_id="agent-hub",
            event_type="dispatch_task",
            thinking_level="high",
            max_turns=None,
            parent_session_id="parent-session-123",
            current_branch="task-12345678/main",
            working_dir="/tmp/lanes/task-12345678",
            task_id="task-12345678",
        )

    @pytest.mark.asyncio
    async def test_dispatch_agent_honors_explicit_task_mode_for_coder(self):
        mock_db = AsyncMock()
        mock_resolved = MagicMock()
        mock_resolved.model = "codex/gpt-5.4"
        mock_resolved.provider = "codex"
        mock_resolved.agent.temperature = 0.2
        mock_resolved.agent.thinking_level = "high"

        fake_plan = MagicMock()
        fake_plan.event_type = "dispatch_task"
        fake_plan.current_branch = "task-87654321/main"
        fake_plan.working_dir = "/tmp/lanes/task-87654321"

        with (
            patch("app.db.async_session", _mock_async_session(mock_db)),
            patch(
                "app.services.agent_routing_utils.resolve_agent",
                new_callable=AsyncMock,
                return_value=mock_resolved,
            ),
            patch(
                "app.services.tools._executor_consultation.prepare_specialist_dispatch",
                new_callable=AsyncMock,
                return_value=fake_plan,
            ) as mock_prepare,
            patch("app.workflows.persona_wake.dispatch_wake") as mock_wake,
        ):
            from app.services.tools._executor_consultation import dispatch_agent

            await dispatch_agent(
                "summitflow",
                "coder",
                "Mode: task\nTask-ID: task-87654321\nTask: Fix the bad dispatch cwd.",
            )

        mock_prepare.assert_awaited_once()
        mock_wake.assert_called_once_with(
            agent_slug="coder",
            model="codex/gpt-5.4",
            provider="codex",
            temperature=0.2,
            prompt="Mode: task\nTask-ID: task-87654321\nTask: Fix the bad dispatch cwd.",
            project_id="summitflow",
            event_type="dispatch_task",
            thinking_level="high",
            max_turns=None,
            parent_session_id=None,
            current_branch="task-87654321/main",
            working_dir="/tmp/lanes/task-87654321",
            task_id="task-87654321",
        )


class TestRetryFailedMcpTools:
    """Tests for _retry_failed_mcp_tools."""

    @pytest.mark.asyncio
    async def test_retries_log_agent_performance(self):
        """Retries log_agent_performance when 'Stream closed' detected."""
        mock_db = AsyncMock()
        failures_result = _make_fetchall_result([("mcp__agent-hub__log_agent_performance", 20)])
        tool_use_row = MagicMock()
        tool_use_row.tool_input = {
            "agent_slug": "git-agent",
            "model_id": CLAUDE_SONNET,
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
            model_id=CLAUDE_SONNET,
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
            max_turns=None,
        )
