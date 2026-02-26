"""Tests for Claude adapter environment injection.

Verifies that Claude adapter CLI paths (oauth, streaming)
pass build_venv_env_overlay() result to ClaudeAgentOptions.env, ensuring
agents in worktrees get the correct VIRTUAL_ENV and PATH.

This is the integration test that verifies the fix for:
  "Agent's Bash tool in worktrees doesn't have VIRTUAL_ENV"
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.adapters.base import Message
from app.constants.models import CLAUDE_SONNET


def _make_venv(tmp_path: Path) -> Path:
    """Create a fake venv with python binary."""
    venv = tmp_path / "backend" / ".venv" / "bin"
    venv.mkdir(parents=True)
    (venv / "python").write_text("#!/usr/bin/env python3\n")
    return tmp_path / "backend" / ".venv"


def _make_worktree(tmp_path: Path) -> tuple[Path, Path]:
    """Create a fake worktree pointing to a main repo with venv.

    Returns (worktree_path, expected_venv_path).
    """
    main_repo = tmp_path / "main-repo"
    main_repo.mkdir()
    (main_repo / ".git").mkdir()
    (main_repo / ".git" / "worktrees" / "task-abc").mkdir(parents=True)
    venv = main_repo / "backend" / ".venv" / "bin"
    venv.mkdir(parents=True)
    (venv / "python").write_text("#!/usr/bin/env python3\n")

    worktree = tmp_path / "worktree-abc"
    worktree.mkdir()
    gitdir = str(main_repo / ".git" / "worktrees" / "task-abc")
    (worktree / ".git").write_text(f"gitdir: {gitdir}\n")

    return worktree, main_repo / "backend" / ".venv"


class TestClaudeOAuthEnvInjection:
    """Tests for env injection in claude_oauth._build_sdk_options()."""

    def test_env_in_sdk_options_main_repo(self, tmp_path: Path) -> None:
        """_build_sdk_options includes env with VIRTUAL_ENV for main repo."""
        venv_path = _make_venv(tmp_path)
        captured_opts: dict[str, Any] = {}

        def capture_options(**kwargs: Any) -> MagicMock:
            captured_opts.update(kwargs)
            return MagicMock()

        with patch("claude_agent_sdk.ClaudeAgentOptions", side_effect=capture_options):
            from app.adapters.claude_oauth import _build_sdk_options

            _build_sdk_options(
                cli_path="/usr/bin/claude",
                sdk_model="sonnet",
                json_mode=False,
                json_schema=None,
                kwargs={"working_dir": str(tmp_path)},
            )

        assert "env" in captured_opts
        assert captured_opts["env"]["VIRTUAL_ENV"] == str(venv_path)

    def test_env_in_sdk_options_worktree(self, tmp_path: Path) -> None:
        """_build_sdk_options resolves main repo venv for worktree."""
        worktree, expected_venv = _make_worktree(tmp_path)
        captured_opts: dict[str, Any] = {}

        def capture_options(**kwargs: Any) -> MagicMock:
            captured_opts.update(kwargs)
            return MagicMock()

        with patch("claude_agent_sdk.ClaudeAgentOptions", side_effect=capture_options):
            from app.adapters.claude_oauth import _build_sdk_options

            _build_sdk_options(
                cli_path="/usr/bin/claude",
                sdk_model="sonnet",
                json_mode=False,
                json_schema=None,
                kwargs={"working_dir": str(worktree)},
            )

        assert captured_opts["env"]["VIRTUAL_ENV"] == str(expected_venv)


class TestClaudeStreamingEnvInjection:
    """Tests for env injection in claude_streaming.stream_oauth()."""

    @pytest.mark.asyncio
    async def test_env_in_streaming_options(self, tmp_path: Path) -> None:
        """stream_oauth includes env in ClaudeAgentOptions."""
        venv_path = _make_venv(tmp_path)
        captured_opts: dict[str, Any] = {}

        def capture_options(**kwargs: Any) -> MagicMock:
            captured_opts.update(kwargs)
            return MagicMock()

        mock_query = AsyncMock()
        mock_query.return_value.__aiter__ = AsyncMock(return_value=iter([]))

        with (
            patch("claude_agent_sdk.ClaudeAgentOptions", side_effect=capture_options),
            patch("claude_agent_sdk.query", return_value=mock_query.return_value),
        ):
            from app.adapters.claude_streaming import stream_oauth

            gen = stream_oauth(
                messages=[Message(role="user", content="test")],
                model=CLAUDE_SONNET,
                cli_path="/usr/bin/claude",
                model_map={},
                working_dir=str(tmp_path),
            )
            async for _ in gen:
                pass

        assert "env" in captured_opts
        assert captured_opts["env"]["VIRTUAL_ENV"] == str(venv_path)
