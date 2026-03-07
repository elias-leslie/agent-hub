"""Tests for heartbeat prompt builder — git_status_summary and prompt assembly."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.workflows._heartbeat_data import (
    _get_git_project_status,
    _get_git_status_summary,
)


class TestGetGitProjectStatus:
    """Tests for _get_git_project_status."""

    @patch("app.workflows._heartbeat_data.subprocess.run")
    def test_returns_none_when_no_git_state(self, mock_run: MagicMock) -> None:
        """Clean repo with no notable state returns None."""
        mock_run.return_value = MagicMock(stdout="", returncode=0)
        result = _get_git_project_status("summitflow", "/home/kasadis/summitflow")
        assert result is None

    @patch("app.workflows._heartbeat_data.subprocess.run")
    def test_shows_uncommitted_changes(self, mock_run: MagicMock) -> None:
        """Uncommitted files appear in output."""
        def side_effect(args, **kwargs):
            mock = MagicMock(returncode=0)
            if "status" in args:
                mock.stdout = " M backend/app/main.py\n?? new_file.py\n"
            else:
                mock.stdout = ""
            return mock

        mock_run.side_effect = side_effect
        result = _get_git_project_status("summitflow", "/home/kasadis/summitflow")

        assert result is not None
        assert "[summitflow]" in result
        assert "uncommitted" in result
        assert "backend/app/main.py" in result

    @patch("app.workflows._heartbeat_data.subprocess.run")
    def test_shows_recent_commits(self, mock_run: MagicMock) -> None:
        """Recent commits appear in output."""
        def side_effect(args, **kwargs):
            mock = MagicMock(returncode=0)
            if "log" in args:
                mock.stdout = "abc1234 Fix bug (SummitFlow Dev)\ndef5678 Add feature (kasadis)\n"
            else:
                mock.stdout = ""
            return mock

        mock_run.side_effect = side_effect
        result = _get_git_project_status("agent-hub", "/home/kasadis/agent-hub")

        assert result is not None
        assert "recent commits" in result
        assert "SummitFlow Dev" in result

    @patch("app.workflows._heartbeat_data.subprocess.run")
    def test_shows_task_branches(self, mock_run: MagicMock) -> None:
        """Task branches appear in output."""
        def side_effect(args, **kwargs):
            mock = MagicMock(returncode=0)
            if "branch" in args:
                mock.stdout = "  task-42-fix-login\n  task-99-add-feature\n"
            else:
                mock.stdout = ""
            return mock

        mock_run.side_effect = side_effect
        result = _get_git_project_status("summitflow", "/home/kasadis/summitflow")

        assert result is not None
        assert "task branches" in result
        assert "task-42-fix-login" in result

    @patch("app.workflows._heartbeat_data.subprocess.run")
    def test_all_sections_combined(self, mock_run: MagicMock) -> None:
        """All three sections appear when all have data."""
        def side_effect(args, **kwargs):
            mock = MagicMock(returncode=0)
            if "status" in args:
                mock.stdout = " M file.py\n"
            elif "log" in args:
                mock.stdout = "abc1234 Fix (Dev)\n"
            elif "branch" in args:
                mock.stdout = "  task-1-test\n"
            else:
                mock.stdout = ""
            return mock

        mock_run.side_effect = side_effect
        result = _get_git_project_status("test-project", "/tmp/test")

        assert result is not None
        assert "uncommitted" in result
        assert "recent commits" in result
        assert "task branches" in result


class TestGetGitStatusSummary:
    """Tests for _get_git_status_summary."""

    @patch("app.constants.projects.get_known_roots", return_value={})
    def test_empty_when_no_roots(self, _mock: MagicMock) -> None:
        result = _get_git_status_summary()
        assert result == ""

    @patch("app.workflows._heartbeat_data.subprocess.run")
    @patch(
        "app.constants.projects.get_known_roots",
        return_value={"summitflow": "/home/kasadis/summitflow"},
    )
    def test_returns_xml_block(self, _mock_roots: MagicMock, mock_run: MagicMock) -> None:
        """Returns <git_state> XML when projects have state."""
        def side_effect(args, **kwargs):
            mock = MagicMock(returncode=0)
            if "log" in args:
                mock.stdout = "abc Fix (Dev)\n"
            else:
                mock.stdout = ""
            return mock

        mock_run.side_effect = side_effect
        result = _get_git_status_summary()

        assert result.startswith("\n<git_state>")
        assert result.endswith("</git_state>")
        assert "[summitflow]" in result

    @patch("app.workflows._heartbeat_data.subprocess.run")
    @patch(
        "app.constants.projects.get_known_roots",
        return_value={"summitflow": "/home/kasadis/summitflow"},
    )
    def test_empty_when_no_git_state(self, _mock_roots: MagicMock, mock_run: MagicMock) -> None:
        """Returns empty when all projects are clean."""
        mock_run.return_value = MagicMock(stdout="", returncode=0)
        result = _get_git_status_summary()
        assert result == ""


class TestBuildHeartbeatPromptIncludesGitState:
    """Integration: build_heartbeat_prompt includes git_state section."""

    @pytest.mark.asyncio
    @patch("app.workflows._heartbeat_prompt._get_agent_roster_summary", new_callable=AsyncMock, return_value="")
    @patch(
        "app.workflows._heartbeat_prompt._get_git_status_summary",
        return_value="\n<git_state>\n[summitflow] test data\n</git_state>",
    )
    @patch("app.workflows._heartbeat_prompt._get_active_work_summary", new_callable=AsyncMock, return_value="")
    @patch("app.workflows._heartbeat_prompt._get_persona_tool_summary", return_value=(5, "tool1, tool2"))
    @patch("app.workflows._heartbeat_prompt.get_project_access_summary", new_callable=AsyncMock, return_value="test")
    @patch("app.workflows._heartbeat_prompt._get_persona_timezone", new_callable=AsyncMock, return_value="UTC")
    async def test_git_state_in_prompt(self, *mocks: MagicMock) -> None:
        from app.workflows._heartbeat_prompt import build_heartbeat_prompt

        prompt = await build_heartbeat_prompt(model_review_due=False, model_review_label="skip")
        assert "<git_state>" in prompt
        assert "[summitflow] test data" in prompt
        assert "Your heartbeat working directory is persona-sandbox" in prompt
        assert "prefer `dispatch_agent` to a coding-capable specialist" in prompt
        assert "prefer coding-capable agents like `reviewer`, `debugger`, or `coder`" in prompt
        assert "Treat recent completed sessions as evidence, not just history." in prompt
        assert "Treat already-active specialist sessions as current work" in prompt
        assert "prefer monitoring, waiting, or dispatching a complementary role instead of sending a duplicate agent of the same type" in prompt
        assert "Only redispatch the same specialist lane when you have concrete evidence the active session is stuck" in prompt
        assert "Treat follow-up branches and worktrees as single workstreams, not shared scratchpads" in prompt
        assert "Reuse an existing follow-up branch only when the new work is the same task lane" in prompt
        assert "create a new task/worktree instead of piling onto the old branch" in prompt
        assert "your next action is split/promotion/cleanup, not another implementation dispatch onto that same branch" in prompt
        assert "do not redispatch the same investigation unless new contradictory evidence appeared" in prompt
        assert "create or advance the recovery task instead of re-opening another review loop" in prompt
        assert "your default next action is `manage_tasks` / task-state repair / verification follow-through" in prompt
        assert "prefer `fixer` or `coder` (or close it yourself) over sending another `reviewer`/`debugger` pass" in prompt
        assert "trust the current state and frame the dispatch around that truth instead of repeating the stale description" in prompt
