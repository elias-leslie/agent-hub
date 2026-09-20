"""Tests for st prompt CLI behaviors."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from agent_hub_st.prompt import app
from agent_hub_st.prompt_formatters import (
    format_prompt_detail,
    format_prompt_list,
    format_prompt_measure,
    format_prompt_restored,
    format_prompt_revisions,
    format_prompt_search,
)
from st_sdk.state import set_compact_output
from typer.testing import CliRunner

runner = CliRunner()


class TestPromptHistoryCommands:
    def test_revisions_forwards_limit_to_prompt_api(self) -> None:
        with (
            patch("agent_hub_st.prompt.prompt_api", return_value={"revisions": []}) as mock_prompt_api,
            patch("agent_hub_st.prompt.format_prompt_revisions") as mock_format,
        ):
            result = runner.invoke(app, ["revisions", "persona-heartbeat-instructions", "--limit", "7"])

        assert result.exit_code == 0
        mock_prompt_api.assert_called_once_with(
            "GET",
            "/persona-heartbeat-instructions/revisions",
            params={"limit": 7},
            tool_name="st prompt revisions",
        )
        mock_format.assert_called_once_with("persona-heartbeat-instructions", {"revisions": []})

    def test_restore_forwards_change_reason_to_prompt_api(self) -> None:
        with (
            patch("agent_hub_st.prompt.prompt_api", return_value={"slug": "persona-heartbeat-instructions"}) as mock_prompt_api,
            patch("agent_hub_st.prompt.format_prompt_restored") as mock_format,
        ):
            result = runner.invoke(
                app,
                [
                    "restore",
                    "persona-heartbeat-instructions",
                    "rev-12345678",
                    "--change-reason",
                    "rollback bad edit",
                ],
            )

        assert result.exit_code == 0
        mock_prompt_api.assert_called_once_with(
            "POST",
            "/persona-heartbeat-instructions/revisions/rev-12345678/restore",
            json={"change_reason": "rollback bad edit"},
            tool_name="st prompt restore",
        )
        mock_format.assert_called_once_with(
            "persona-heartbeat-instructions",
            "rev-12345678",
            {"slug": "persona-heartbeat-instructions"},
        )

    def test_update_forwards_change_reason_to_prompt_api(self, tmp_path: Path) -> None:
        content_file = tmp_path / "prompt.md"
        content_file.write_text("Keep signal, cut filler.\n", encoding="utf-8")

        with patch("agent_hub_st.prompt.prompt_api", return_value={"content": "Keep signal, cut filler.\n"}) as mock_prompt_api:
            result = runner.invoke(
                app,
                [
                    "update",
                    "persona-heartbeat-instructions",
                    "--file",
                    str(content_file),
                    "--change-reason",
                    "compress duplicate wording",
                ],
            )

        assert result.exit_code == 0
        mock_prompt_api.assert_called_once_with(
            "PUT",
            "/persona-heartbeat-instructions",
            json={
                "content": "Keep signal, cut filler.\n",
                "change_reason": "compress duplicate wording",
            },
        )

    def test_update_forwards_enabled_flag_to_prompt_api(self) -> None:
        with patch("agent_hub_st.prompt.prompt_api", return_value={"enabled": False}) as mock_prompt_api:
            result = runner.invoke(
                app,
                [
                    "update",
                    "caveman-output-directive",
                    "--disabled",
                    "--change-reason",
                    "benchmark against non-caveman baseline",
                ],
            )

        assert result.exit_code == 0
        mock_prompt_api.assert_called_once_with(
            "PUT",
            "/caveman-output-directive",
            json={
                "enabled": False,
                "change_reason": "benchmark against non-caveman baseline",
            },
        )





    def test_measure_fetches_current_prompt_when_no_candidate_file(self) -> None:
        with patch(
            "agent_hub_st.prompt.prompt_api",
            return_value={"content": "Keep signal, cut filler.\n"},
        ) as mock_prompt_api:
            result = runner.invoke(app, ["measure", "persona-heartbeat-instructions"])

        assert result.exit_code == 0
        mock_prompt_api.assert_called_once_with("GET", "/persona-heartbeat-instructions")

    def test_measure_reads_candidate_file_when_provided(self, tmp_path: Path) -> None:
        candidate_file = tmp_path / "prompt.md"
        candidate_file.write_text("Compressed wording.\n", encoding="utf-8")

        with patch(
            "agent_hub_st.prompt.prompt_api",
            return_value={"content": "Keep signal, cut filler.\n"},
        ) as mock_prompt_api:
            result = runner.invoke(
                app,
                ["measure", "persona-heartbeat-instructions", "--file", str(candidate_file)],
            )

        assert result.exit_code == 0
        mock_prompt_api.assert_called_once_with("GET", "/persona-heartbeat-instructions")

    def test_search_finds_metadata_and_content_matches(self) -> None:
        prompts = [
            {
                "slug": "platform-context",
                "name": "Platform Context",
                "is_global": True,
                "content": "Use st for project development.\nNative tools come second.\n",
            },
            {
                "slug": "other",
                "name": "Other Prompt",
                "is_global": False,
                "description": "st wrapper policy",
                "content": "No matching body.\n",
            },
            {
                "slug": "quiet",
                "name": "Quiet",
                "is_global": False,
                "content": "No match here.\n",
            },
        ]

        set_compact_output(True)
        try:
            with patch("agent_hub_st.prompt.prompt_api", return_value={"prompts": prompts}) as mock_prompt_api:
                result = runner.invoke(app, ["search", "st", "--max-lines", "1"])
        finally:
            set_compact_output(False)

        assert result.exit_code == 0
        mock_prompt_api.assert_called_once_with(
            "GET",
            "",
            params={},
            tool_name="st prompt search",
        )
        assert "PROMPT_SEARCH[2]:query=st" in result.output
        assert "platform-context" in result.output
        assert "L1: Use st for project development." in result.output
        assert "other" in result.output
        assert "meta=description|lines=0" in result.output
        assert "quiet" not in result.output

    def test_search_forwards_global_filter(self) -> None:
        with patch("agent_hub_st.prompt.prompt_api", return_value={"prompts": []}) as mock_prompt_api:
            result = runner.invoke(app, ["search", "st", "--global"])

        assert result.exit_code == 0
        mock_prompt_api.assert_called_once_with(
            "GET",
            "",
            params={"is_global": "true"},
            tool_name="st prompt search",
        )


class TestPromptHistoryFormatters:
    def test_format_prompt_list_compact_shows_enabled_state(self, capsys) -> None:
        set_compact_output(True)
        try:
            format_prompt_list(
                [
                    {
                        "slug": "caveman-output-directive",
                        "name": "Caveman Output Directive",
                        "is_global": True,
                        "enabled": False,
                        "content": "Terse like caveman.\n",
                    }
                ]
            )
        finally:
            set_compact_output(False)

        captured = capsys.readouterr().out
        assert "PROMPTS[1]" in captured
        assert "caveman-output-directive" in captured
        assert "Y N 1L" in captured

    def test_format_prompt_detail_compact_shows_enabled_state(self, capsys) -> None:
        set_compact_output(True)
        try:
            format_prompt_detail(
                {
                    "slug": "caveman-output-directive",
                    "name": "Caveman Output Directive",
                    "is_global": True,
                    "enabled": False,
                    "content": "Terse like caveman.\n",
                }
            )
        finally:
            set_compact_output(False)

        captured = capsys.readouterr().out
        assert "PROMPT:caveman-output-directive|Caveman Output Directive|Y|N|1L" in captured
        assert "Terse like caveman." in captured

    def test_format_prompt_measure_compact_current_only(self, capsys) -> None:
        set_compact_output(True)
        try:
            format_prompt_measure("persona-heartbeat-instructions", "Keep signal, cut filler.\n")
        finally:
            set_compact_output(False)

        captured = capsys.readouterr().out
        assert "PROMPT_MEASURE:persona-heartbeat-instructions|chars=25|lines=1|tokens=6" in captured

    def test_format_prompt_measure_compact_with_candidate_delta(self, capsys) -> None:
        set_compact_output(True)
        try:
            format_prompt_measure(
                "persona-heartbeat-instructions",
                "Keep signal, cut filler.\n",
                "Cut filler.\n",
            )
        finally:
            set_compact_output(False)

        captured = capsys.readouterr().out
        assert "PROMPT_MEASURE:persona-heartbeat-instructions" in captured
        assert "|current=6tok/1L/25c|candidate=3tok/1L/12c|delta=-3tok/0L/-13c" in captured

    def test_format_prompt_revisions_compact(self, capsys) -> None:
        set_compact_output(True)
        try:
            format_prompt_revisions(
                "persona-heartbeat-instructions",
                {
                    "revisions": [
                        {
                            "id": "rev-12345678",
                            "action": "update",
                            "created_at": "2026-04-11T05:00:00Z",
                            "changed_by": "api",
                            "change_reason": "compress duplicate wording",
                        }
                    ]
                },
            )
        finally:
            set_compact_output(False)

        captured = capsys.readouterr().out
        assert "PROMPT_REVISIONS[1]:slug=persona-heartbeat-instructions" in captured
        assert "rev-1234 [update] at=2026-04-11T05:00:00Z by=api" in captured
        assert "reason=compress duplicate wording" in captured

    def test_format_prompt_restored_compact(self, capsys) -> None:
        set_compact_output(True)
        try:
            format_prompt_restored(
                "persona-heartbeat-instructions",
                "rev-12345678",
                {
                    "content": "Keep signal, cut filler.\n",
                    "updated_at": "2026-04-11T05:15:00Z",
                },
            )
        finally:
            set_compact_output(False)

        captured = capsys.readouterr().out
        assert "PROMPT_RESTORED:persona-heartbeat-instructions:rev=rev-1234|1L|updated_at=2026-04-11T05:15:00Z" in captured

    def test_format_prompt_search_compact(self, capsys) -> None:
        set_compact_output(True)
        try:
            format_prompt_search(
                "st",
                [
                    {
                        "slug": "platform-context",
                        "metadata_matches": ["slug"],
                        "line_match_count": 2,
                        "line_matches": [
                            {"line": 1, "text": "Use st for project development."},
                        ],
                    }
                ],
            )
        finally:
            set_compact_output(False)

        captured = capsys.readouterr().out
        assert "PROMPT_SEARCH[1]:query=st" in captured
        assert "platform-context" in captured
        assert "meta=slug|lines=2" in captured
        assert "L1: Use st for project development." in captured
