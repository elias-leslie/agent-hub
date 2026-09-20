"""Tests for st complete command ergonomics."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from agent_hub_st.complete import app
from typer.testing import CliRunner

runner = CliRunner()


def test_complete_accepts_message_option(tmp_path: Path) -> None:
    with patch("agent_hub_st.complete.call_complete") as mock_call:
        mock_call.return_value = {"content": "ok"}

        result = runner.invoke(
            app,
            ["--agent", "persona", "--message", "Say hello"],
        )

    assert result.exit_code == 0
    mock_call.assert_called_once()
    assert mock_call.call_args.args[1] == "Say hello"


def test_complete_uses_file_when_message_missing(tmp_path: Path) -> None:
    prompt_file = tmp_path / "prompt.txt"
    prompt_file.write_text("hello from file")

    with patch("agent_hub_st.complete.call_complete") as mock_call:
        mock_call.return_value = {"content": "ok"}

        result = runner.invoke(
            app,
            ["--agent", "persona", "--file", str(prompt_file)],
        )

    assert result.exit_code == 0
    assert mock_call.call_args.args[1] == "hello from file"


def test_complete_help_mentions_message_option() -> None:
    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "--message" in result.output


def test_complete_no_longer_exposes_agentic_flags() -> None:
    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "--execute-tools" not in result.output
    assert "--max-turns" not in result.output
    assert "--working-dir" not in result.output


def test_complete_supports_no_memory_flag() -> None:
    with patch("agent_hub_st.complete.call_complete") as mock_call:
        mock_call.return_value = {"content": "ok"}

        result = runner.invoke(
            app,
            ["--agent", "persona", "--no-memory", "--message", "Lean run"],
        )

    assert result.exit_code == 0
    assert mock_call.call_args.args[4] is False


def test_complete_forwards_task_type() -> None:
    with patch("agent_hub_st.complete.call_complete") as mock_call:
        mock_call.return_value = {"content": "ok"}

        result = runner.invoke(
            app,
            ["--agent", "persona", "--task-type", "heartbeat", "--message", "Lean run"],
        )

    assert result.exit_code == 0
    assert mock_call.call_args.args[16] == "heartbeat"


def test_complete_exits_nonzero_for_error_content() -> None:
    with patch("agent_hub_st.complete.call_complete") as mock_call:
        mock_call.return_value = {"content": "Error: provider failed"}

        result = runner.invoke(
            app,
            ["--agent", "persona", "--message", "Run"],
        )

    assert result.exit_code == 1
    assert "Error: provider failed" in result.output
