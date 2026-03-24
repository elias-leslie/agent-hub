"""Tests for heartbeat prompt builder — git_status_summary and prompt assembly."""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.workflows._heartbeat_data import (
    _build_workstream_next_action,
    _classify_workstream_lane,
    _fetch_recently_completed_sessions_section,
    _get_active_specialist_inventory,
    _get_active_work_summary,
    _get_cleanup_status_summary,
    _get_git_status_summary,
    _get_protection_status_summary,
    _get_workstream_inventory,
)


def _mock_async_session_with_rows(rows: list[object]):
    """Create an async_session context manager whose execute().all() yields rows."""
    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.all.return_value = rows
    mock_db.execute.return_value = mock_result

    @asynccontextmanager
    async def _session():
        yield mock_db

    return _session, mock_db


class TestGetGitStatusSummary:
    """Tests for _get_git_status_summary."""

    @pytest.mark.asyncio
    @patch("app.workflows._heartbeat_data._run_st_command", new_callable=AsyncMock)
    async def test_returns_xml_block(self, mock_run: AsyncMock) -> None:
        """Returns <git_state> XML when compact git status has content."""
        mock_run.return_value = (
            "GIT[2]\n"
            "summitflow      main            clean   uncommitted:0 ahead:0 behind:0\n"
            "agent-hub       main            dirty   uncommitted:3 ahead:1 behind:0\n"
        )
        result = await _get_git_status_summary()

        assert result.startswith("\n<git_state>")
        assert result.endswith("</git_state>")
        assert "GIT[2]" in result
        assert "ACTIONABLE-GIT[1]" in result
        assert "agent-hub" in result

    @pytest.mark.asyncio
    @patch("app.workflows._heartbeat_data._run_st_command", new_callable=AsyncMock, return_value="")
    async def test_empty_when_no_git_state(self, mock_run: AsyncMock) -> None:
        """Returns empty when compact git status output is empty."""
        result = await _get_git_status_summary()
        assert result == ""

    @pytest.mark.asyncio
    @patch("app.workflows._heartbeat_data._run_st_command", new_callable=AsyncMock)
    async def test_filters_to_target_project(self, mock_run: AsyncMock) -> None:
        mock_run.return_value = (
            "GIT[2]\n"
            "summitflow      main            clean   uncommitted:0 ahead:0 behind:0\n"
            "agent-hub       main            dirty   uncommitted:3 ahead:1 behind:0\n"
            "\n"
            "ACTIONABLE-GIT[2]\n"
            "- summitflow | branch=main | state=clean | next=none\n"
            "- agent-hub | branch=main | state=dirty | next=inspect_then_commit_or_dispatch\n"
        )

        result = await _get_git_status_summary("agent-hub")

        assert "agent-hub" in result
        assert "summitflow" not in result
        assert "ACTIONABLE-GIT[1]" in result


class TestBuildHeartbeatPromptIncludesGitState:
    """Integration: build_heartbeat_prompt includes git_state section."""

    @pytest.mark.asyncio
    @patch("app.workflows._heartbeat_prompt._get_active_specialist_inventory", new_callable=AsyncMock, return_value="")
    @patch("app.workflows._heartbeat_prompt._get_agent_roster_summary", new_callable=AsyncMock, return_value="")
    @patch(
        "app.workflows._heartbeat_prompt._get_protection_status_summary",
        new_callable=AsyncMock,
        return_value="\n<protection_status>\nLATEST bkp-123|completed|8.5MB\nSOURCE:agent-hub|enabled|daily|retention_days:30\n</protection_status>",
    )
    @patch(
        "app.workflows._heartbeat_prompt._get_cleanup_status_summary",
        new_callable=AsyncMock,
        return_value="\n<cleanup_status>\nCLEANUP[all]:repos=2 needs_cleanup=1 worktrees=1 dirty=0 orphan=1 prunable=0\n</cleanup_status>",
    )
    @patch(
        "app.workflows._heartbeat_prompt._get_git_status_summary",
        new_callable=AsyncMock,
        return_value="\n<git_state>\n[summitflow] test data\n</git_state>",
    )
    @patch("app.workflows._heartbeat_prompt._fetch_task_overview", new_callable=AsyncMock, return_value="")
    @patch(
        "app.workflows._heartbeat_prompt.require_prompt_content",
        new_callable=AsyncMock,
        return_value=(
            "Run your regular heartbeat check. Current time: {timestamp} ({local_time})\n\n"
            "{project_access_summary}\n\n"
            "## Model Review ({model_review_status})\n"
            "- If status is `DUE`, run `review_agent_performance`.\n"
            "- If status is not due, skip model review this heartbeat.\n\n"
            "## Available Tools ({tool_count} total)\n"
            "Beyond bash/read_file/write_file, you have: {persona_tool_list}\n\n"
            "Follow your <heartbeat_instructions> from your system context."
        ),
    )
    @patch("app.workflows._heartbeat_prompt._get_active_work_summary", new_callable=AsyncMock, return_value="")
    @patch("app.workflows._heartbeat_prompt._get_persona_tool_summary", return_value=(5, "tool1, tool2"))
    @patch("app.workflows._heartbeat_prompt.get_project_access_summary", new_callable=AsyncMock, return_value="test")
    @patch("app.workflows._heartbeat_prompt._get_persona_timezone", new_callable=AsyncMock, return_value="UTC")
    async def test_git_state_in_prompt(self, *mocks: MagicMock) -> None:
        from app.workflows._heartbeat_prompt import build_heartbeat_prompt

        prompt = await build_heartbeat_prompt(model_review_due=False, model_review_label="skip")
        assert "<protection_status>" in prompt
        assert "LATEST bkp-123|completed|8.5MB" in prompt
        assert "<cleanup_status>" in prompt
        assert "CLEANUP[all]:repos=2 needs_cleanup=1" in prompt
        assert "<git_state>" in prompt
        assert "[summitflow] test data" in prompt
        assert "Run your regular heartbeat check." in prompt
        assert "## Model Review (not due — skip)" in prompt
        assert "If status is not due, skip model review this heartbeat." in prompt
        assert "## Available Tools (5 total)" in prompt
        assert "tool1, tool2" in prompt
        assert "Follow your <heartbeat_instructions> from your system context." in prompt

    @pytest.mark.asyncio
    @patch("app.workflows._heartbeat_prompt._get_active_specialist_inventory", new_callable=AsyncMock, return_value="")
    @patch("app.workflows._heartbeat_prompt._get_agent_roster_summary", new_callable=AsyncMock, return_value="")
    @patch("app.workflows._heartbeat_prompt._get_protection_status_summary", new_callable=AsyncMock, return_value="")
    @patch("app.workflows._heartbeat_prompt._get_cleanup_status_summary", new_callable=AsyncMock, return_value="")
    @patch("app.workflows._heartbeat_prompt._get_git_status_summary", new_callable=AsyncMock, return_value="")
    @patch("app.workflows._heartbeat_prompt._fetch_task_overview", new_callable=AsyncMock, return_value="")
    @patch(
        "app.workflows._heartbeat_prompt.require_prompt_content",
        new_callable=AsyncMock,
        return_value="Tools: {persona_tool_list}",
    )
    @patch("app.workflows._heartbeat_prompt._get_active_work_summary", new_callable=AsyncMock, return_value="")
    @patch(
        "app.workflows._heartbeat_prompt._get_persona_tool_summary",
        return_value=(2, "mcp__agent-hub__manage_tasks, mcp__agent-hub__query_sessions"),
    )
    @patch("app.workflows._heartbeat_prompt.get_project_access_summary", new_callable=AsyncMock, return_value="test")
    @patch("app.workflows._heartbeat_prompt._get_persona_timezone", new_callable=AsyncMock, return_value="UTC")
    async def test_claude_prompt_uses_provider_specific_tool_names(self, *mocks: MagicMock) -> None:
        from app.workflows._heartbeat_prompt import build_heartbeat_prompt

        prompt = await build_heartbeat_prompt(
            model_review_due=False,
            model_review_label="skip",
            provider="claude",
        )

        assert "mcp__agent-hub__manage_tasks" in prompt
        assert "mcp__agent-hub__query_sessions" in prompt


class TestProtectionStatusSummary:
    """Tests for the heartbeat protection summary block."""

    @pytest.mark.asyncio
    @patch("app.workflows._heartbeat_data._fetch_backup_schedule", new_callable=AsyncMock)
    @patch("app.workflows._heartbeat_data._fetch_backup_status", new_callable=AsyncMock)
    async def test_returns_target_project_backup_summary(
        self,
        mock_status: AsyncMock,
        mock_schedule: AsyncMock,
    ) -> None:
        mock_status.return_value = "LATEST bkp-123|completed|8.5MB"
        mock_schedule.return_value = "SOURCE:agent-hub|enabled|daily|retention_days:30"

        result = await _get_protection_status_summary("agent-hub")

        assert result.startswith("\n<protection_status>")
        assert "LATEST bkp-123|completed|8.5MB" in result
        assert "SOURCE:agent-hub|enabled|daily|retention_days:30" in result
        mock_status.assert_called_once_with("agent-hub")
        mock_schedule.assert_called_once_with("agent-hub")

    @pytest.mark.asyncio
    @patch("app.workflows._heartbeat_data._fetch_backup_schedule", new_callable=AsyncMock)
    @patch("app.workflows._heartbeat_data._fetch_backup_status", new_callable=AsyncMock)
    async def test_empty_when_no_backup_data(
        self,
        mock_status: AsyncMock,
        mock_schedule: AsyncMock,
    ) -> None:
        mock_status.return_value = ""
        mock_schedule.return_value = ""

        assert await _get_protection_status_summary("agent-hub") == ""


class TestCleanupStatusSummary:
    """Tests for heartbeat cleanup-status section."""

    @pytest.mark.asyncio
    @patch(
        "app.workflows._heartbeat_data._fetch_cleanup_status",
        new_callable=AsyncMock,
        return_value="CLEANUP[all]:repos=3 needs_cleanup=1 worktrees=2 dirty=1 orphan=1 prunable=0",
    )
    async def test_returns_xml_block(self, _mock_fetch: AsyncMock) -> None:
        result = await _get_cleanup_status_summary()
        assert result.startswith("\n<cleanup_status>")
        assert "needs_cleanup=1" in result
        assert result.endswith("</cleanup_status>")

    @pytest.mark.asyncio
    @patch("app.workflows._heartbeat_data._fetch_cleanup_status", new_callable=AsyncMock, return_value="")
    async def test_returns_empty_when_no_cleanup_state(self, _mock_fetch: AsyncMock) -> None:
        assert await _get_cleanup_status_summary() == ""

    @pytest.mark.asyncio
    @patch("app.workflows._heartbeat_data._fetch_cleanup_status", new_callable=AsyncMock)
    async def test_filters_to_target_project(self, mock_fetch: AsyncMock) -> None:
        mock_fetch.return_value = (
            "CLEANUP[all]:repos=2 needs_cleanup=2 worktrees=2 dirty=2 orphan=0 prunable=0\n"
            "summitflow worktrees:1 dirty:1 orphan:0 prunable:0 tasks:task-1\n"
            "agent-hub worktrees:1 dirty:1 orphan:0 prunable:0 tasks:task-2\n"
        )

        result = await _get_cleanup_status_summary("agent-hub")

        assert "agent-hub worktrees:1 dirty:1" in result
        assert "summitflow" not in result


class TestActiveSpecialistInventory:
    """Tests for active specialist inventory in heartbeat prompt context."""

    @pytest.mark.asyncio
    async def test_groups_active_non_owner_specialists_by_project_and_agent(self) -> None:
        fake_rows = [
            {
                "session_id": "sess-1",
                "agent_slug": "reviewer",
                "project_id": "summitflow",
                "parent_session_id": "parent-1",
                "request_source": "dispatch",
                "age_minutes": 4,
            },
            {
                "session_id": "sess-2",
                "agent_slug": "reviewer",
                "project_id": "summitflow",
                "parent_session_id": "parent-2",
                "request_source": "dispatch",
                "age_minutes": 1,
            },
            {
                "session_id": "sess-3",
                "agent_slug": "investment-committee",
                "project_id": "portfolio-ai",
                "parent_session_id": None,
                "request_source": "dispatch",
                "age_minutes": 2,
            },
        ]

        with patch(
            "app.workflows._heartbeat_data._query_active_specialist_sessions",
            new_callable=AsyncMock,
            return_value=fake_rows,
        ):
            result = await _get_active_specialist_inventory()

        assert "<active_specialist_inventory>" in result
        assert "summitflow | reviewer | active=2" in result
        assert "next=dedupe_or_wait" in result
        assert "portfolio-ai | investment-committee | active=1" in result
        assert "next=wait_or_complement" in result

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_active_specialists_exist(self) -> None:
        with patch(
            "app.workflows._heartbeat_data._query_active_specialist_sessions",
            new_callable=AsyncMock,
            return_value=[],
        ):
            result = await _get_active_specialist_inventory()

        assert result == ""

    @pytest.mark.asyncio
    async def test_passes_target_project_filter(self) -> None:
        with patch(
            "app.workflows._heartbeat_data._query_active_specialist_sessions",
            new_callable=AsyncMock,
            return_value=[],
        ) as mock_query:
            await _get_active_specialist_inventory("agent-hub")

        mock_query.assert_awaited_once_with("agent-hub")


class TestRecentlyCompletedSessionsSection:
    """Tests for recently completed session summaries in heartbeat context."""

    @pytest.mark.asyncio
    async def test_excludes_persona_sessions_from_completed_summary(self) -> None:
        now = datetime.now(UTC)
        session_factory, mock_db = _mock_async_session_with_rows(
            [
                MagicMock(
                    id="sess-1",
                    agent_slug="refactor",
                    project_id="agent-hub",
                    summary_oneliner="Refactored the tool handler",
                    created_at=now,
                ),
            ]
        )

        with (
            patch("app.db.async_session", session_factory),
            patch(
                "app.workflows._heartbeat_data.fetch_session_display_summary_results",
                new_callable=AsyncMock,
                return_value={
                    "sess-1": MagicMock(
                        summary="Refactored the tool handler and verified follow-up.",
                        has_summary_tag=True,
                        summary_outcome="completed",
                        has_unresolved_blocker=False,
                    )
                },
            ),
        ):
            result = await _fetch_recently_completed_sessions_section()

        executed_query = str(mock_db.execute.await_args.args[0])
        assert "Recently completed sessions: 1" in result
        assert "refactor on agent-hub" in result
        assert "Refactored the tool handler and verified follow-up." in result
        assert "persona" not in result
        assert "sessions.agent_slug != :agent_slug_1" in executed_query

    @pytest.mark.asyncio
    async def test_skips_sessions_without_clean_display_summary(self) -> None:
        now = datetime.now(UTC)
        session_factory, _mock_db = _mock_async_session_with_rows(
            [
                MagicMock(
                    id="sess-noisy",
                    agent_slug="coder",
                    project_id="agent-hub",
                    summary_oneliner="Noisy fallback summary",
                    created_at=now,
                ),
                MagicMock(
                    id="sess-clean",
                    agent_slug="refactor",
                    project_id="summitflow",
                    summary_oneliner="Refactored cleanup flow",
                    created_at=now,
                ),
            ]
        )

        with (
            patch("app.db.async_session", session_factory),
            patch(
                "app.workflows._heartbeat_data.fetch_session_display_summary_results",
                new_callable=AsyncMock,
                return_value={
                    "sess-noisy": MagicMock(summary=None, has_summary_tag=False),
                    "sess-clean": MagicMock(
                        summary="Refactored cleanup flow and verified the lane state.",
                        has_summary_tag=True,
                        summary_outcome="completed",
                        has_unresolved_blocker=False,
                    ),
                },
            ),
        ):
            result = await _fetch_recently_completed_sessions_section()

        assert "Recently completed sessions: 1" in result
        assert "sess-noisy" not in result
        assert "summitflow" in result
        assert "Refactored cleanup flow and verified the lane state." in result

    @pytest.mark.asyncio
    async def test_skips_sessions_without_explicit_summary_tag(self) -> None:
        now = datetime.now(UTC)
        session_factory, _mock_db = _mock_async_session_with_rows(
            [
                MagicMock(
                    id="sess-fallback",
                    agent_slug="coder",
                    project_id="agent-hub",
                    summary_oneliner="Fallback summary",
                    created_at=now,
                ),
            ]
        )

        with (
            patch("app.db.async_session", session_factory),
            patch(
                "app.workflows._heartbeat_data.fetch_session_display_summary_results",
                new_callable=AsyncMock,
                return_value={
                    "sess-fallback": MagicMock(
                        summary="Fallback summary cleaned from prose.",
                        has_summary_tag=False,
                        summary_outcome=None,
                        has_unresolved_blocker=False,
                    )
                },
            ),
        ):
            result = await _fetch_recently_completed_sessions_section()

        assert result == ""

    @pytest.mark.asyncio
    async def test_skips_completed_summary_that_still_describes_blocker(self) -> None:
        now = datetime.now(UTC)
        session_factory, _mock_db = _mock_async_session_with_rows(
            [
                MagicMock(
                    id="sess-blocked",
                    agent_slug="coder",
                    project_id="agent-hub",
                    summary_oneliner="Publish is blocked.",
                    created_at=now,
                ),
            ]
        )

        with (
            patch("app.db.async_session", session_factory),
            patch(
                "app.workflows._heartbeat_data.fetch_session_display_summary_results",
                new_callable=AsyncMock,
                return_value={
                    "sess-blocked": MagicMock(
                        summary="Publish is blocked because detached rebuild is unavailable.",
                        has_summary_tag=True,
                        summary_outcome="completed",
                        has_unresolved_blocker=True,
                    )
                },
            ),
        ):
            result = await _fetch_recently_completed_sessions_section()

        assert result == ""


class TestActiveWorkSummary:
    """Tests for active_work shaping in heartbeat context."""

    @pytest.mark.asyncio
    async def test_suppresses_completed_sessions_when_ready_work_exists_and_queue_is_clean(self) -> None:
        fake_overview = """READY-ALL[2 ready, 0 blocked, 0 active, 0 stale across 1 projects]

agent-hub (2 ready)
    task-52831804 P3 refactor [A] Refactor: backend/app/services/tools/_executor_consultation.py
    task-0e20ca4d P3 refactor [A] Refactor: backend/app/services/memory/session_analysis.py
"""

        with (
            patch(
                "app.workflows._heartbeat_data._fetch_task_overview",
                return_value=fake_overview,
            ),
            patch(
                "app.workflows._heartbeat_data._fetch_active_sessions_section",
                new_callable=AsyncMock,
                return_value="",
            ),
            patch(
                "app.workflows._heartbeat_data._fetch_recently_completed_sessions_section",
                new_callable=AsyncMock,
                return_value="Recently completed sessions: 1\n- refactor on agent-hub: old summary",
            ) as mock_completed,
        ):
            result = await _get_active_work_summary()

        assert "task-52831804" in result
        assert "Recently completed sessions" not in result
        mock_completed.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_keeps_completed_sessions_when_live_or_stale_work_exists(self) -> None:
        fake_overview = """READY-ALL[1 ready, 0 blocked, 0 active, 1 stale across 1 projects]

agent-hub (1 ready, 1 stale)
  ? task-de53b498 P1 task     [M] Fix stale running queue state [stale-running]
    task-52831804 P3 refactor [A] Refactor: backend/app/services/tools/_executor_consultation.py
"""

        with (
            patch(
                "app.workflows._heartbeat_data._fetch_task_overview",
                return_value=fake_overview,
            ),
            patch(
                "app.workflows._heartbeat_data._fetch_active_sessions_section",
                new_callable=AsyncMock,
                return_value="",
            ),
            patch(
                "app.workflows._heartbeat_data._fetch_recently_completed_sessions_section",
                new_callable=AsyncMock,
                return_value="Recently completed sessions: 1\n- refactor on agent-hub: old summary",
            ) as mock_completed,
        ):
            result = await _get_active_work_summary()

        assert "Recently completed sessions: 1" in result
        mock_completed.assert_awaited_once()

    @pytest.mark.asyncio
    @patch("app.workflows._heartbeat_data._fetch_recently_completed_sessions_section", new_callable=AsyncMock, return_value="")
    @patch("app.workflows._heartbeat_data._fetch_active_sessions_section", new_callable=AsyncMock, return_value="")
    async def test_filters_task_overview_to_target_project(
        self,
        _mock_sessions: AsyncMock,
        _mock_completed: AsyncMock,
    ) -> None:
        task_overview = (
            "READY-ALL[2 ready, 0 blocked, 2 active, 0 stale across 2 projects]\n\n"
            "PROJECTS[2]\n"
            "- agent-hub | 1 ready, 1 active\n"
            "- summitflow | 1 ready, 1 active\n\n"
            "ACTIONABLE-READY[2]\n"
            "- agent-hub | task-1 | P2 refactor [A] | Refactor: backend/app/foo.py\n"
            "- summitflow | task-2 | P2 refactor [A] | Refactor: backend/app/bar.py\n"
        )

        result = await _get_active_work_summary(
            task_overview=task_overview,
            target_project_id="agent-hub",
        )

        assert "- agent-hub | 1 ready, 1 active" in result
        assert "- agent-hub | task-1" in result
        assert "summitflow" not in result


class TestGetWorkstreamInventory:
    """Tests for first-class workstream inventory classification."""

    @pytest.mark.asyncio
    async def test_reports_completed_lane_ready_for_closure(self) -> None:
        fake_rows = [
            {
                "session_id": "sess-1",
                "agent_slug": "coder",
                "project_id": "summitflow",
                "external_id": "task-123",
                "current_branch": "task-123/main",
                "status": "completed",
                "created_at": "ignored",
                "updated_at": "ignored",
            },
        ]

        with patch(
            "app.workflows._heartbeat_data._query_recent_workstream_sessions",
            new_callable=AsyncMock,
            return_value=fake_rows,
        ), patch(
            "app.workflows._heartbeat_data._fetch_task_overview",
            return_value="agent-hub (1)\n  * task-123 pending Refactor",
        ):
            result = await _get_workstream_inventory()

        assert "<workstream_inventory>" in result
        assert "task-123" in result
        assert "state=completed_ready_for_closure" in result
        assert 'manage_tasks(action="reconcile"' in result

    @pytest.mark.asyncio
    async def test_reports_claude_callable_names_for_workstream_actions(self) -> None:
        fake_rows = [
            {
                "session_id": "sess-1",
                "agent_slug": "coder",
                "project_id": "summitflow",
                "external_id": "task-123",
                "current_branch": "task-123/main",
                "status": "completed",
                "created_at": "ignored",
                "updated_at": "ignored",
            },
        ]

        with patch(
            "app.workflows._heartbeat_data._query_recent_workstream_sessions",
            new_callable=AsyncMock,
            return_value=fake_rows,
        ), patch(
            "app.workflows._heartbeat_data._fetch_task_overview",
            return_value="agent-hub (1)\n  * task-123 pending Refactor",
        ):
            result = await _get_workstream_inventory(provider="claude")

        assert 'mcp__agent-hub__manage_tasks(action="reconcile"' in result

    @pytest.mark.asyncio
    async def test_branch_only_completed_lane_still_recovers_task_id(self) -> None:
        fake_rows = [
            {
                "session_id": "sess-branch-only",
                "agent_slug": "refactor",
                "project_id": "terminal",
                "external_id": None,
                "current_branch": "task-a3903361/main",
                "status": "completed",
                "created_at": "ignored",
                "updated_at": "ignored",
            },
        ]

        with patch(
            "app.workflows._heartbeat_data._query_recent_workstream_sessions",
            new_callable=AsyncMock,
            return_value=fake_rows,
        ), patch(
            "app.workflows._heartbeat_data._fetch_task_overview",
            return_value="terminal (1)\n  * task-a3903361 pending Refactor",
        ):
            result = await _get_workstream_inventory()

        assert "task-a3903361" in result
        assert "state=completed_ready_for_closure" in result
        assert 'manage_tasks(action="reconcile", task_id="task-a3903361", project_id="terminal")' in result

    @pytest.mark.asyncio
    async def test_reports_stale_active_lane(self) -> None:
        fake_rows = [
            {
                "session_id": "sess-2",
                "agent_slug": "reviewer",
                "project_id": "agent-hub",
                "external_id": "task-999",
                "current_branch": "task-999/main",
                "status": "active",
                "created_at": "ignored",
                "updated_at": "ignored",
                "age_minutes": 480,
                "idle_minutes": 480,
            },
        ]

        with patch(
            "app.workflows._heartbeat_data._query_recent_workstream_sessions",
            new_callable=AsyncMock,
            return_value=fake_rows,
        ):
            result = await _get_workstream_inventory()

        assert "task-999" in result
        assert "state=stale_active" in result
        assert 'query_sessions(' in result

    @pytest.mark.asyncio
    async def test_omits_completed_lane_when_task_is_not_in_current_queue_snapshot(self) -> None:
        fake_rows = [
            {
                "session_id": "sess-gone",
                "agent_slug": "refactor",
                "project_id": "agent-hub",
                "external_id": "task-deadbeef",
                "current_branch": "task-deadbeef/main",
                "status": "completed",
                "created_at": "ignored",
                "updated_at": "ignored",
                "age_minutes": 30,
                "idle_minutes": 30,
            },
        ]

        with (
            patch(
                "app.workflows._heartbeat_data._query_recent_workstream_sessions",
                new_callable=AsyncMock,
                return_value=fake_rows,
            ),
            patch(
                "app.workflows._heartbeat_data._fetch_task_overview",
                return_value="READY-ALL[0 ready, 0 blocked, 0 active, 0 stale across 0 projects]",
            ),
        ):
            result = await _get_workstream_inventory()

        assert result == ""

    @pytest.mark.asyncio
    async def test_omits_persona_completed_lanes_without_task_ids(self) -> None:
        fake_rows = [
            {
                "session_id": "sess-persona",
                "agent_slug": "persona",
                "project_id": "agent-hub",
                "external_id": None,
                "current_branch": None,
                "status": "completed",
                "created_at": "ignored",
                "updated_at": "ignored",
            },
        ]

        with (
            patch(
                "app.workflows._heartbeat_data._query_recent_workstream_sessions",
                new_callable=AsyncMock,
                return_value=fake_rows,
            ),
            patch(
                "app.workflows._heartbeat_data._fetch_task_overview",
                return_value="READY-ALL[0 ready, 0 blocked, 0 active, 0 stale across 0 projects]",
            ),
        ):
            result = await _get_workstream_inventory()

        assert result == ""

    @pytest.mark.asyncio
    async def test_reports_stale_active_lane_from_idle_time_not_session_age(self) -> None:
        fake_rows = [
            {
                "session_id": "sess-2",
                "agent_slug": "refactor",
                "project_id": "agent-hub",
                "external_id": "task-123",
                "current_branch": "task-123/main",
                "status": "active",
                "created_at": "ignored",
                "updated_at": "ignored",
                "age_minutes": 6,
                "idle_minutes": 12,
            },
        ]

        with patch(
            "app.workflows._heartbeat_data._query_recent_workstream_sessions",
            new_callable=AsyncMock,
            return_value=fake_rows,
        ):
            result = await _get_workstream_inventory()

        assert "task-123" in result
        assert "state=stale_active" in result
        assert "idle=12m" in result

    @pytest.mark.asyncio
    async def test_reports_mixed_lane_when_multiple_branches_active(self) -> None:
        fake_rows = [
            {
                "session_id": "sess-3",
                "agent_slug": "coder",
                "project_id": "summitflow",
                "external_id": "task-777",
                "current_branch": "task-777/main",
                "working_dir": "/tmp/worktrees/task-777-main",
                "status": "active",
                "created_at": "ignored",
                "updated_at": "ignored",
                "age_minutes": 10,
            },
            {
                "session_id": "sess-4",
                "agent_slug": "debugger",
                "project_id": "summitflow",
                "external_id": "task-777",
                "current_branch": "task-777/follow-up",
                "working_dir": "/tmp/worktrees/task-777-follow-up",
                "status": "active",
                "created_at": "ignored",
                "updated_at": "ignored",
                "age_minutes": 5,
            },
        ]

        with patch(
            "app.workflows._heartbeat_data._query_recent_workstream_sessions",
            new_callable=AsyncMock,
            return_value=fake_rows,
        ):
            result = await _get_workstream_inventory()

        assert "task-777" in result
        assert "state=mixed" in result
        assert "branches=2" in result
        assert "worktree=/tmp/worktrees/task-777-follow-up" in result or "worktree=/tmp/worktrees/task-777-main" in result

    @pytest.mark.asyncio
    async def test_reports_worktree_path_when_lane_has_working_dir(self) -> None:
        fake_rows = [
            {
                "session_id": "sess-7",
                "agent_slug": "refactor",
                "project_id": "terminal",
                "external_id": "task-999",
                "current_branch": "task-999/main",
                "working_dir": "/home/testuser/.local/share/st/worktrees/terminal/task-999",
                "status": "active",
                "created_at": "ignored",
                "updated_at": "ignored",
                "age_minutes": 2,
            },
        ]

        with patch(
            "app.workflows._heartbeat_data._query_recent_workstream_sessions",
            new_callable=AsyncMock,
            return_value=fake_rows,
        ):
            result = await _get_workstream_inventory()

        assert "task-999" in result
        assert "worktree=/home/testuser/.local/share/st/worktrees/terminal/task-999" in result

    @pytest.mark.asyncio
    async def test_reports_reconciled_lane_from_persisted_lifecycle_markers(self) -> None:
        fake_rows = [
            {
                "session_id": "sess-5",
                "agent_slug": "coder",
                "project_id": "summitflow",
                "external_id": "task-888",
                "current_branch": "task-888/main",
                "status": "completed",
                "workstream_status": "authoritative",
                "created_at": "ignored",
                "updated_at": "ignored",
            },
            {
                "session_id": "sess-6",
                "agent_slug": "reviewer",
                "project_id": "summitflow",
                "external_id": "task-888",
                "current_branch": "task-888/old",
                "status": "completed",
                "workstream_status": "superseded",
                "created_at": "ignored",
                "updated_at": "ignored",
            },
        ]

        with patch(
            "app.workflows._heartbeat_data._query_recent_workstream_sessions",
            new_callable=AsyncMock,
            return_value=fake_rows,
        ):
            result = await _get_workstream_inventory()

        assert "task-888" in result
        assert "state=reconciled" in result
        assert "lifecycle=authoritative,superseded" in result

    @pytest.mark.asyncio
    async def test_promotes_stale_running_ready_all_entries_into_workstream_inventory(self) -> None:
        fake_overview = """READY-ALL[1 ready, 0 blocked, 0 active, 1 stale across 1 projects]

agent-hub (1 ready, 1 stale)
  ? task-de53b498 P1 task     [M] Add persona heartbeat provider regression tests for ... [stale-running]
"""

        with patch(
            "app.workflows._heartbeat_data._query_recent_workstream_sessions",
            new_callable=AsyncMock,
            return_value=[],
        ), patch(
            "app.workflows._heartbeat_data._fetch_task_overview",
            return_value=fake_overview,
        ):
            result = await _get_workstream_inventory()

        assert "task-de53b498" in result
        assert "state=stale_running_task" in result
        assert (
            'manage_tasks(action="reconcile", task_id="task-de53b498", project_id="agent-hub")'
            in result
        )

    @pytest.mark.asyncio
    async def test_stale_running_queue_truth_overrides_historical_session_rows(self) -> None:
        fake_overview = """READY-ALL[1 ready, 0 blocked, 0 active, 1 stale across 1 projects]

agent-hub (1 ready, 1 stale)
  ? task-de53b498 P1 task     [M] Add persona heartbeat provider regression tests for ... [stale-running]
"""
        fake_rows = [
            {
                "session_id": "sess-1",
                "agent_slug": "refactor",
                "project_id": "agent-hub",
                "external_id": "task-de53b498",
                "current_branch": "task-de53b498/main",
                "status": "completed",
                "workstream_status": "superseded",
                "created_at": "ignored",
                "updated_at": "ignored",
            },
        ]

        with patch(
            "app.workflows._heartbeat_data._query_recent_workstream_sessions",
            new_callable=AsyncMock,
            return_value=fake_rows,
        ), patch(
            "app.workflows._heartbeat_data._fetch_task_overview",
            return_value=fake_overview,
        ):
            result = await _get_workstream_inventory()

        assert "task-de53b498" in result
        assert "state=stale_running_task" in result
        assert "state=superseded" not in result


class TestWorkstreamLaneContract:
    """Tests for lane classification precedence and automation boundaries."""

    def test_classify_reconciled_wins_over_completed_ready_for_closure(self) -> None:
        rows = [
            {
                "status": "completed",
                "workstream_status": "authoritative",
                "current_branch": "task-1/main",
            },
            {
                "status": "completed",
                "workstream_status": "superseded",
                "current_branch": "task-1/old",
            },
        ]

        assert _classify_workstream_lane(rows) == "reconciled"

    def test_classify_retired_wins_over_completed_ready_for_closure(self) -> None:
        rows = [
            {
                "status": "completed",
                "workstream_status": "retired",
                "current_branch": "task-2/main",
            }
        ]

        assert _classify_workstream_lane(rows) == "retired"

    def test_classify_superseded_wins_over_completed_ready_for_closure(self) -> None:
        rows = [
            {
                "status": "completed",
                "workstream_status": "superseded",
                "current_branch": "task-3/main",
            }
        ]

        assert _classify_workstream_lane(rows) == "superseded"

    def test_classify_active_wins_when_lane_is_fresh(self) -> None:
        rows = [
            {
                "status": "active",
                "current_branch": "task-4/main",
                "age_minutes": 15,
                "idle_minutes": 5,
            }
        ]

        assert _classify_workstream_lane(rows) == "active"

    def test_classify_orphaned_when_lane_has_no_active_or_completed_status(self) -> None:
        rows = [
            {
                "status": "paused",
                "current_branch": "task-5/main",
            }
        ]

        assert _classify_workstream_lane(rows) == "orphaned"

    def test_build_next_action_limits_automation_for_informational_states(self) -> None:
        assert (
            _build_workstream_next_action(
                state="mixed",
                project_id="summitflow",
                task_id="task-6",
            )
            == "split/promotion cleanup; do not dispatch more implementation onto this lane"
        )
        assert (
            _build_workstream_next_action(
                state="reconciled",
                project_id="summitflow",
                task_id="task-6",
            )
            == "authoritative lane recorded; avoid redispatch unless new facts contradict it"
        )
        assert (
            _build_workstream_next_action(
                state="retired",
                project_id="summitflow",
                task_id="task-6",
            )
            == "retired_lane_no_action"
        )
        assert (
            _build_workstream_next_action(
                state="superseded",
                project_id="summitflow",
                task_id="task-6",
            )
            == "superseded_lane_no_action"
        )

    def test_build_next_action_uses_claude_mcp_names(self) -> None:
        assert (
            _build_workstream_next_action(
                state="completed_ready_for_closure",
                project_id="agent-hub",
                task_id="task-6",
                provider="claude",
            )
            == 'mcp__agent-hub__manage_tasks(action="reconcile", task_id="task-6", project_id="agent-hub")'
        )
