"""Tests for st memory CLI behaviors."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
import typer
from agent_hub_st.memory import app
from agent_hub_st.memory_crud import revisions_impl, save_impl, tag_impl, update_impl
from agent_hub_st.memory_formatters import format_list_compact
from st_sdk.context import OutputContext
from typer.testing import CliRunner

runner = CliRunner()


@pytest.mark.parametrize("options", [[], ["-s", "typo"], ["-s", "project"], ["-s", "global", "--scope-id", "neri"]])
def test_save_rejects_ambiguous_scope_before_write(options):
    with patch("agent_hub_st.memory_crud.agent_hub_request") as request:
        result = runner.invoke(app, ["save", "-S", "Keep scoped knowledge", "--content", "**Scope**: Keep this learning in its project.", *options])
    assert result.exit_code != 0
    assert "scope" in result.output.lower()
    request.assert_not_called()


def test_update_scope_uses_revision_checked_canonical_policy():
    policy = {"scope": "global", "targets": [], "workflows": [], "activation": "always", "required": True, "format": "full", "task_types": [], "phases": [], "applicability": {}}
    source = {"source_type": "memory", "source_id": "abc12345-full", "revision": "sha256:before", "policy": policy}
    with patch("agent_hub_st.memory_crud.agent_hub_request", side_effect=[{"sources": [source]}, {"change_id": "change-1"}]) as request:
        result = runner.invoke(app, ["update", "abc12345", "--scope", "project", "--scope-id", "neri", "--change-reason", "Correct project scope"])
    assert result.exit_code == 0, result.output
    draft = request.call_args.kwargs["json"]
    edit = draft["edits"][0]
    assert edit["expected_revision"] == "sha256:before"
    assert edit["policy"] == {**policy, "scope": "project", "targets": ["neri"]}
    assert draft["reason"] == "Correct project scope"
    assert "change-1" in result.output


class TestMemoryUpdateContentInput:
    """Tests for safe content ingestion in `st memory update`."""

    def test_update_accepts_content_from_file(self, tmp_path: Path) -> None:
        """`--content-file` should load the file contents and forward them to update_impl."""
        content_file = tmp_path / "episode.md"
        content_file.write_text(
            "**Git Publish**: Use /commit_it when available.\n",
            encoding="utf-8",
        )

        with patch("agent_hub_st.memory.update_impl") as mock_update_impl:
            result = runner.invoke(app, ["update", "abc12345", "--content-file", str(content_file)])

        assert result.exit_code == 0
        mock_update_impl.assert_called_once()
        args = mock_update_impl.call_args.args
        assert args[0] == "abc12345"
        assert args[1] == "**Git Publish**: Use /commit_it when available.\n"
        assert args[2:] == (
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            False,
            None,
            False,
            None,
        )

    def test_update_accepts_content_from_stdin(self) -> None:
        """`--content-file -` should read content from stdin."""
        with patch("agent_hub_st.memory.update_impl") as mock_update_impl:
            result = runner.invoke(
                app,
                ["update", "abc12345", "--content-file", "-"],
                input="**Literal Work**: Keep `backticks` in stored content.\n",
            )

        assert result.exit_code == 0
        mock_update_impl.assert_called_once()
        args = mock_update_impl.call_args.args
        assert args[0] == "abc12345"
        assert args[1] == "**Literal Work**: Keep `backticks` in stored content.\n"
        assert args[2:] == (
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            False,
            None,
            False,
            None,
        )

    def test_update_rejects_inline_and_file_content_together(self, tmp_path: Path) -> None:
        """`--content` and `--content-file` together should error clearly."""
        content_file = tmp_path / "episode.md"
        content_file.write_text("content\n", encoding="utf-8")

        with patch("agent_hub_st.memory.update_impl") as mock_update_impl:
            result = runner.invoke(
                app,
                [
                    "update",
                    "abc12345",
                    "--content",
                    "inline",
                    "--content-file",
                    str(content_file),
                ],
            )

        assert result.exit_code == 2
        assert "Specify only one of --content or --content-file" in result.output
        mock_update_impl.assert_not_called()

    def test_update_rejects_blank_content_and_file_together(self, tmp_path: Path) -> None:
        """An explicit blank `--content` should still conflict with `--content-file`."""
        content_file = tmp_path / "episode.md"
        content_file.write_text("content\n", encoding="utf-8")

        with patch("agent_hub_st.memory.update_impl") as mock_update_impl:
            result = runner.invoke(
                app,
                [
                    "update",
                    "abc12345",
                    "--content",
                    "",
                    "--content-file",
                    str(content_file),
                ],
            )

        assert result.exit_code == 2
        assert "Specify only one of --content or --content-file" in result.output
        mock_update_impl.assert_not_called()


class TestMemorySaveContentInput:
    """Tests for safe content ingestion in `st memory save`."""

    def test_save_accepts_content_from_file(self, tmp_path: Path) -> None:
        """`--content-file` should load content for save."""
        content_file = tmp_path / "episode.md"
        content_file.write_text("**Quality Checks**: Use dt for all quality checks.\n", encoding="utf-8")

        with patch("agent_hub_st.memory.save_impl") as mock_save_impl:
            result = runner.invoke(
                app,
                [
                    "save",
                    "--content-file",
                    str(content_file),
                    "--summary",
                    "Use dt for checks",
                ],
            )

        assert result.exit_code == 0
        args = mock_save_impl.call_args.args
        assert args[1] == "**Quality Checks**: Use dt for all quality checks.\n"
        assert args[8:16] == (None, None, None, None, None, None, None, None)

    def test_save_accepts_content_from_stdin(self) -> None:
        """`--content-file -` should read save content from stdin."""
        with patch("agent_hub_st.memory.save_impl") as mock_save_impl:
            result = runner.invoke(
                app,
                [
                    "save",
                    "--content-file",
                    "-",
                    "--summary",
                    "Use dt for checks",
                ],
                input="**Quality Checks**: Use dt for all quality checks.\n",
            )

        assert result.exit_code == 0
        args = mock_save_impl.call_args.args
        assert args[1] == "**Quality Checks**: Use dt for all quality checks.\n"
        assert args[8:16] == (None, None, None, None, None, None, None, None)

    def test_save_accepts_content_option(self) -> None:
        """`--content` should support explicit inline save content."""
        with patch("agent_hub_st.memory.save_impl") as mock_save_impl:
            result = runner.invoke(
                app,
                [
                    "save",
                    "--content",
                    "**Quality Checks**: Use dt for all quality checks.\n",
                    "--summary",
                    "Use dt for checks",
                ],
            )

        assert result.exit_code == 0
        args = mock_save_impl.call_args.args
        assert args[1] == "**Quality Checks**: Use dt for all quality checks.\n"
        assert args[8:16] == (None, None, None, None, None, None, None, None)

    def test_save_rejects_blank_positional_and_content_option_together(self) -> None:
        """A blank positional CONTENT should still conflict with explicit `--content`."""
        with patch("agent_hub_st.memory.save_impl") as mock_save_impl:
            result = runner.invoke(
                app,
                [
                    "save",
                    "",
                    "--content",
                    "**Quality Checks**: Use dt for all quality checks.\n",
                    "--summary",
                    "Use dt for checks",
                ],
            )

        assert result.exit_code == 2
        assert "Specify either [CONTENT] or --content, not both" in result.output
        mock_save_impl.assert_not_called()

    def test_save_rejects_blank_content_option_and_file_together(self, tmp_path: Path) -> None:
        """An explicit blank `--content` should still conflict with `--content-file`."""
        content_file = tmp_path / "episode.md"
        content_file.write_text("content\n", encoding="utf-8")

        with patch("agent_hub_st.memory.save_impl") as mock_save_impl:
            result = runner.invoke(
                app,
                [
                    "save",
                    "--content",
                    "",
                    "--content-file",
                    str(content_file),
                    "--summary",
                    "Use dt for checks",
                ],
            )

        assert result.exit_code == 2
        assert "Specify only one of --content or --content-file" in result.output
        mock_save_impl.assert_not_called()

    def test_save_validates_authoring_fields(self) -> None:
        with (
            patch("agent_hub_st.memory.validate_memory_authoring") as mock_validate,
            patch("agent_hub_st.memory.save_impl") as mock_save_impl,
        ):
            result = runner.invoke(
                app,
                [
                    "save",
                    "**Quality Checks**: Use dt for all quality checks.\n",
                    "--summary",
                    "Use dt for checks",
                ],
            )

        assert result.exit_code == 0
        mock_validate.assert_called_once_with(
            "Use dt for checks",
            "**Quality Checks**: Use dt for all quality checks.\n",
            "Use dt for checks",
            "reference",
        )
        mock_save_impl.assert_called_once()





    def test_save_rejects_inline_and_file_content_together(self, tmp_path: Path) -> None:
        """`save` should reject inline content combined with --content-file."""
        content_file = tmp_path / "episode.md"
        content_file.write_text("content\n", encoding="utf-8")

        with patch("agent_hub_st.memory.save_impl") as mock_save_impl:
            result = runner.invoke(
                app,
                [
                    "save",
                    "inline content",
                    "--content-file",
                    str(content_file),
                    "--summary",
                    "Use dt for checks",
                ],
            )

        assert result.exit_code == 2
        assert "Specify only one of --content or --content-file" in result.output
        mock_save_impl.assert_not_called()

    def test_save_missing_summary_shows_quickstart(self) -> None:
        """Missing summary should show a self-contained quickstart."""
        with patch("agent_hub_st.memory.save_impl") as mock_save_impl:
            result = runner.invoke(
                app,
                [
                    "save",
                    "**Quality Checks**: Use dt for all quality checks.",
                ],
            )

        assert result.exit_code == 1
        assert "st memory save requires --summary." in result.output
        assert 'st memory save -s project --scope-id a-term -t reference' in result.output
        assert "Content: non-empty text or Markdown." in result.output
        mock_save_impl.assert_not_called()

    def test_save_missing_content_shows_quickstart(self) -> None:
        """Missing content should show a self-contained quickstart."""
        with patch("agent_hub_st.memory.save_impl") as mock_save_impl:
            result = runner.invoke(
                app,
                [
                    "save",
                    "--summary",
                    "Use dt for checks",
                ],
            )

        assert result.exit_code == 1
        assert "st memory save requires content or --content-file." in result.output
        assert 'st memory save -s project --scope-id a-term -t reference' in result.output
        assert "Content: non-empty text or Markdown." in result.output
        mock_save_impl.assert_not_called()


class TestMemoryFormatCommand:
    """Tests for the mechanical memory formatter helper."""

    def test_format_builds_standard_episode_and_summary(self) -> None:
        result = runner.invoke(
            app,
            [
                "format",
                "--tier",
                "mandate",
                "--topic",
                "Memory Headers",
                "--instruction",
                "Use compact topic headers for every memory episode",
                "--prohibition",
                "Never repeat tier names inside the episode body",
                "--why",
                "tier already lives in metadata",
            ],
        )

        assert result.exit_code == 0
        assert "summary: compact topic headers for every" in result.output.lower()
        assert "CONTENT:" in result.output
        assert "**Memory Headers**: Use compact topic headers for every memory episode." in result.output
        assert "Never repeat tier names inside the episode body." in result.output
        assert "Why: tier already lives in metadata." in result.output


class TestMemoryTagOptions:
    """Tests for tag-aware save/update CLI plumbing."""

    def test_save_forwards_tags_to_impl(self) -> None:
        """`st memory save --tags` should wire tags through the public CLI."""
        with patch("agent_hub_st.memory.save_impl") as mock_save_impl:
            result = runner.invoke(
                app,
                [
                    "save",
                    "**Topic**: Use finance tags on portfolio memories.",
                    "--summary",
                    "Tag finance memory",
                    "--tags",
                    "finance-relevant,portfolio",
                ],
            )

        assert result.exit_code == 0
        args = mock_save_impl.call_args.args
        assert args[1:] == (
            "**Topic**: Use finance tags on portfolio memories.",
            "Tag finance memory",
            "reference",
            80,
            None,
            False,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            "finance-relevant,portfolio",
            None,
            None,
            None,
        )

    def test_save_forwards_change_reason_to_impl(self) -> None:
        with patch("agent_hub_st.memory.save_impl") as mock_save_impl:
            result = runner.invoke(
                app,
                [
                    "save",
                    "**Topic**: Use finance tags on portfolio memories.",
                    "--summary",
                    "Tag finance memory",
                    "--change-reason",
                    "dedupe stale guidance",
                ],
            )

        assert result.exit_code == 0
        assert mock_save_impl.call_args.args[-1] == "dedupe stale guidance"

    def test_update_forwards_tags_to_impl(self) -> None:
        """`st memory update --tags` should wire tag replacement through the CLI."""
        with patch("agent_hub_st.memory.update_impl") as mock_update_impl:
            result = runner.invoke(
                app,
                [
                    "update",
                    "abc12345",
                    "--tags",
                    "finance-relevant",
                ],
            )

        assert result.exit_code == 0
        args = mock_update_impl.call_args.args
        assert args == (
            "abc12345",
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            False,
            "finance-relevant",
            False,
            None,
        )

    def test_update_accepts_content_without_memory_warnings(self) -> None:
        with patch("agent_hub_st.memory.update_impl") as mock_update_impl:
            result = runner.invoke(
                app,
                [
                    "update",
                    "abc12345",
                    "--content",
                    "**Quality Checks**: Use dt for all quality checks.\n",
                ],
            )

        assert result.exit_code == 0
        mock_update_impl.assert_called_once()

    def test_save_forwards_context_routing_to_impl(self) -> None:
        """`st memory save` should wire new routing controls through the public CLI."""
        with patch("agent_hub_st.memory.save_impl") as mock_save_impl:
            result = runner.invoke(
                app,
                [
                    "save",
                    "**Tool Docs**: Keep CLI docs role-scoped.",
                    "--summary",
                    "Scope tool docs",
                    "--context-kind",
                    "capability",
                    "--trigger-phases",
                    "implementation,verification",
                    "--consumer-profiles",
                    "codex_startup,claude_startup",
                    "--exclude-consumer-profiles",
                    "agent_runtime",
                    "--agent-slugs",
                    "jenny",
                    "--exclude-agent-slugs",
                    "formatter",
                    "--audience-tags",
                    "operator-tooling",
                    "--exclude-audience-tags",
                    "narrow-output",
                ],
            )

        assert result.exit_code == 0
        args = mock_save_impl.call_args.args
        assert args[8:16] == (
            "implementation,verification",
            "capability",
            "codex_startup,claude_startup",
            "agent_runtime",
            "jenny",
            "formatter",
            "operator-tooling",
            "narrow-output",
        )

    def test_tag_command_forwards_bulk_tag_updates(self) -> None:
        """`st memory tag` should call tag_impl with add/remove operations."""
        with patch("agent_hub_st.memory.tag_impl") as mock_tag_impl:
            result = runner.invoke(
                app,
                [
                    "tag",
                    "abc12345",
                    "def67890",
                    "--add-tags",
                    "finance-relevant,portfolio",
                    "--remove-tags",
                    "stale",
                ],
            )

        assert result.exit_code == 0
        assert mock_tag_impl.call_args.args == (["abc12345", "def67890"],)
        assert mock_tag_impl.call_args.kwargs == {
            "add_tags": "finance-relevant,portfolio",
            "remove_tags": "stale",
        }

    def test_update_forwards_change_reason_to_impl(self) -> None:
        with patch("agent_hub_st.memory.update_impl") as mock_update_impl:
            result = runner.invoke(
                app,
                [
                    "update",
                    "abc12345",
                    "--summary",
                    "Fresh summary",
                    "--change-reason",
                    "refresh duplicate wording",
                ],
            )

        assert result.exit_code == 0
        assert mock_update_impl.call_args.args[-1] == "refresh duplicate wording"

    def test_update_forwards_context_routing_to_impl(self) -> None:
        """`st memory update` should wire new routing controls through the public CLI."""
        with patch("agent_hub_st.memory.update_impl") as mock_update_impl:
            result = runner.invoke(
                app,
                [
                    "update",
                    "abc12345",
                    "--context-kind",
                    "capability",
                    "--trigger-phases",
                    "implementation,verification",
                    "--consumer-profiles",
                    "codex_startup",
                    "--exclude-consumer-profiles",
                    "agent_runtime",
                    "--agent-slugs",
                    "jenny",
                    "--exclude-agent-slugs",
                    "formatter",
                    "--audience-tags",
                    "operator-tooling",
                    "--exclude-audience-tags",
                    "narrow-output",
                    "--clear-applicability",
                ],
            )

        assert result.exit_code == 0
        assert mock_update_impl.call_args.args == (
            "abc12345",
            None,
            None,
            None,
            None,
            "implementation,verification",
            None,
            "capability",
            "codex_startup",
            "agent_runtime",
            "jenny",
            "formatter",
            "operator-tooling",
            "narrow-output",
            True,
            None,
            False,
            None,
        )

    def test_delete_forwards_change_reason_to_impl(self) -> None:
        with patch("agent_hub_st.memory.delete_impl") as mock_delete_impl:
            result = runner.invoke(
                app,
                [
                    "delete",
                    "abc12345",
                    "--change-reason",
                    "remove duplicate memory",
                ],
            )

        assert result.exit_code == 0
        assert mock_delete_impl.call_args.kwargs["change_reason"] == "remove duplicate memory"

    def test_revisions_forwards_to_impl(self) -> None:
        with patch("agent_hub_st.memory.revisions_impl") as mock_revisions_impl:
            result = runner.invoke(
                app,
                [
                    "revisions",
                    "abc12345",
                    "--limit",
                    "7",
                ],
            )

        assert result.exit_code == 0
        assert mock_revisions_impl.call_args.args[1:] == ("abc12345", 7)

    def test_restore_forwards_change_reason_to_impl(self) -> None:
        with patch("agent_hub_st.memory.restore_impl") as mock_restore_impl:
            result = runner.invoke(
                app,
                [
                    "restore",
                    "abc12345",
                    "rev98765",
                    "--change-reason",
                    "rollback bad curator edit",
                ],
            )

        assert result.exit_code == 0
        assert mock_restore_impl.call_args.args == ("abc12345", "rev98765")
        assert mock_restore_impl.call_args.kwargs["change_reason"] == "rollback bad curator edit"

    def test_update_impl_rejects_tags_and_clear_tags_together(self) -> None:
        """Tag replacement and clearing are mutually exclusive."""
        with patch("agent_hub_st.memory_crud.typer.echo") as mock_echo:
            try:
                update_impl(
                    "abc12345",
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    False,
                    "finance-relevant",
                    True,
                )
            except typer.Exit as exc:
                assert exc.exit_code == 1
            else:
                raise AssertionError("Expected typer.Exit when both --tags and --clear-tags are provided")

        mock_echo.assert_called_once_with("Error: Specify only one of --tags or --clear-tags")

    def test_tag_impl_calls_bulk_tag_endpoint(self) -> None:
        with (
            patch("agent_hub_st.memory_crud.agent_hub_request", return_value={"updated": 2, "failed": 1}) as mock_request,
            patch("agent_hub_st.memory_crud.typer.echo") as mock_echo,
        ):
            tag_impl(["abc12345", "def67890"], add_tags="finance-relevant,portfolio", remove_tags="stale")

        assert mock_request.call_args.args == ("POST", "/api/memory/episodes/bulk-tag")
        assert mock_request.call_args.kwargs["json"] == {
            "uuids": ["abc12345", "def67890"],
            "add_tags": ["finance-relevant", "portfolio"],
            "remove_tags": ["stale"],
        }
        assert mock_request.call_args.kwargs["tool_name"] == "st memory tag"
        mock_echo.assert_called_once_with("Tagged: updated=2 failed=1")

    def test_tag_impl_rejects_empty_bulk_tag_request(self) -> None:
        with patch("agent_hub_st.memory_crud.typer.echo") as mock_echo:
            try:
                tag_impl(["abc12345"], add_tags=None, remove_tags=None)
            except typer.Exit as exc:
                assert exc.exit_code == 1
            else:
                raise AssertionError("Expected typer.Exit when no add/remove tags are provided")

        mock_echo.assert_called_once_with("Error: Must specify --add-tags and/or --remove-tags")

    def test_save_impl_applies_tags_after_learning_is_saved(self) -> None:
        """Save should apply requested tags using the memory tags endpoint."""
        out = OutputContext(compact=True)
        with (
            patch("agent_hub_st.memory_crud.validate_save_inputs", return_value="Tag finance memory"),
            patch("agent_hub_st.memory_crud.validate_content_format"),
            patch("agent_hub_st.memory_crud.agent_hub_request", return_value={"uuid": "abc12345", "status": "provisional"}),
            patch("agent_hub_st.memory_crud.replace_episode_tags") as mock_replace_tags,
            patch("agent_hub_st.memory_crud.format_save_compact"),
        ):
            save_impl(
                out,
                "**Topic**: Tag finance memories.",
                "Tag finance memory",
                "reference",
                80,
                None,
                False,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                "finance-relevant,portfolio",
                "project",
                "portfolio-ai",
            )

        mock_replace_tags.assert_called_once_with("abc12345", ["finance-relevant", "portfolio"])

    def test_delete_impl_forwards_query_params(self) -> None:
        with patch("agent_hub_st.memory_crud.agent_hub_request", return_value={"success": True}) as mock_request:
            from agent_hub_st.memory_crud import _delete_single

            _delete_single("abc12345", change_reason="remove duplicate memory")

        assert mock_request.call_args.kwargs["params"] == {"change_reason": "remove duplicate memory"}

    def test_revisions_impl_uses_history_endpoint(self) -> None:
        out = OutputContext(compact=True)
        with (
            patch("agent_hub_st.memory_crud.agent_hub_request", return_value={"revisions": []}) as mock_request,
            patch("agent_hub_st.memory_crud.format_revisions_compact"),
        ):
            revisions_impl(out, "abc12345", 9)

        assert mock_request.call_args.args[:2] == ("GET", "/api/memory/episode/abc12345/revisions")
        assert mock_request.call_args.kwargs["params"] == {"limit": 9}

    def test_update_impl_preserves_existing_tags_when_updating_in_place(self) -> None:
        """Content/tier updates should preserve tags on the existing episode UUID."""
        with (
            patch("agent_hub_st.memory_crud.fetch_existing_episode", return_value={"uuid": "abc12345", "content": "old", "summary": "Old", "injection_tier": "reference"}),
            patch("agent_hub_st.memory_crud.fetch_episode_tags", return_value=["finance-relevant"]),
            patch("agent_hub_st.memory_crud.update_episode_content_or_tier") as mock_update_episode,
            patch("agent_hub_st.memory_crud.replace_episode_tags") as mock_replace_tags,
            patch("agent_hub_st.memory_crud.validate_content_format"),
            patch("agent_hub_st.memory_crud.typer.echo"),
        ):
            update_impl(
                "abc12345",
                "new content",
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                False,
                None,
                False,
            )

        mock_update_episode.assert_called_once_with(
            "abc12345",
            content="new content",
            tier="reference",
            change_reason=None,
        )
        mock_replace_tags.assert_called_once_with("abc12345", ["finance-relevant"])

    def test_update_impl_skips_tag_fetch_for_summary_only_changes(self) -> None:
        """Summary-only updates should not fetch or rewrite tags."""
        with (
            patch("agent_hub_st.memory_crud.fetch_existing_episode") as mock_fetch_existing,
            patch("agent_hub_st.memory_crud.fetch_episode_tags") as mock_fetch_tags,
            patch("agent_hub_st.memory_crud.patch_episode_properties") as mock_patch_properties,
            patch("agent_hub_st.memory_crud.replace_episode_tags") as mock_replace_tags,
        ):
            update_impl(
                "abc12345",
                None,
                None,
                "Updated summary",
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                False,
                None,
                False,
            )

        mock_fetch_existing.assert_not_called()
        mock_fetch_tags.assert_not_called()
        mock_patch_properties.assert_called_once_with(
            "abc12345", "Updated summary", None, None, None, None, None, render_mode=None,
        )
        mock_replace_tags.assert_not_called()

    def test_update_impl_merges_applicability_changes(self) -> None:
        """Applicability updates should preserve untouched existing targeting keys."""
        with (
            patch(
                "agent_hub_st.memory_crud.fetch_existing_episode",
                return_value={
                    "uuid": "abc12345",
                    "applicability": {
                        "consumer_profiles": ["codex_startup"],
                        "agent_slugs": ["jenny"],
                    },
                },
            ) as mock_fetch_existing,
            patch("agent_hub_st.memory_crud.patch_episode_properties") as mock_patch_properties,
        ):
            update_impl(
                "abc12345",
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                "claude_startup",
                None,
                None,
                None,
                None,
                None,
                False,
                None,
                False,
            )

        mock_fetch_existing.assert_called_once_with("abc12345")
        mock_patch_properties.assert_called_once_with(
            "abc12345",
            None,
            None,
            None,
            None,
            None,
            {
                "consumer_profiles": ["claude_startup"],
                "exclude_consumer_profiles": [],
                "agent_slugs": ["jenny"],
                "exclude_agent_slugs": [],
                "audience_tags": [],
                "exclude_audience_tags": [],
            },
            render_mode=None,
        )

    def test_update_impl_rejects_invalid_tier(self) -> None:
        """Tier updates should validate allowed tier values."""
        with patch("agent_hub_st.memory_crud.fetch_existing_episode") as mock_fetch_existing:
            try:
                update_impl("abc12345", None, "bad-tier", None, None, None, None, None, None, None, None, None, None, None, False, None, False)
            except typer.Exit as exc:
                assert exc.exit_code == 1
            else:
                raise AssertionError("Expected typer.Exit for invalid tier")

        mock_fetch_existing.assert_not_called()

    def test_update_impl_passes_render_mode_to_patch(self) -> None:
        """--render-mode flows through update_impl into patch_episode_properties."""
        with (
            patch("agent_hub_st.memory_crud.fetch_existing_episode") as mock_fetch_existing,
            patch("agent_hub_st.memory_crud.patch_episode_properties") as mock_patch_properties,
        ):
            update_impl(
                "abc12345",
                None, None, None, None, None, None, None, None, None, None, None, None, None,
                False, None, False, None,
                render_mode="full",
            )

        mock_fetch_existing.assert_not_called()
        mock_patch_properties.assert_called_once_with(
            "abc12345", None, None, None, None, None, None, render_mode="full",
        )

    def test_update_impl_clears_render_mode_with_auto(self) -> None:
        """--render-mode auto sends a null render_mode to clear the override."""
        with (
            patch("agent_hub_st.memory_crud.fetch_existing_episode"),
            patch("agent_hub_st.memory_crud.patch_episode_properties") as mock_patch_properties,
        ):
            update_impl(
                "abc12345",
                None, None, None, None, None, None, None, None, None, None, None, None, None,
                False, None, False, None,
                render_mode="auto",
            )

        # The CLI sentinel for "clear" is the RENDER_MODE_CLEAR string from
        # _memory_crud_helpers; patch_episode_properties translates it to None.
        from agent_hub_st._memory_crud_helpers import RENDER_MODE_CLEAR

        mock_patch_properties.assert_called_once_with(
            "abc12345", None, None, None, None, None, None, render_mode=RENDER_MODE_CLEAR,
        )

    def test_update_impl_rejects_invalid_render_mode(self) -> None:
        """--render-mode must be full/compact/summary/auto/clear."""
        with patch("agent_hub_st.memory_crud.fetch_existing_episode"):
            try:
                update_impl(
                    "abc12345",
                    None, None, None, None, None, None, None, None, None, None, None, None, None,
                    False, None, False, None,
                    render_mode="bogus",
                )
            except typer.Exit as exc:
                assert exc.exit_code == 1
            else:
                raise AssertionError("Expected typer.Exit for invalid render-mode")


class TestMemoryStatusCommand:
    """Tests for the operator-facing memory status command."""

    def test_status_command_forwards_cli_options(self) -> None:
        with patch("agent_hub_st.memory.status_impl", return_value=True) as mock_status_impl:
            result = runner.invoke(
                app,
                [
                    "status",
                    "--scope",
                    "project",
                    "--scope-id",
                    "agent-hub",
                    "--consumer-profile",
                    "codex_startup",
                    "--branch",
                    "main",
                ],
            )

        assert result.exit_code == 0
        assert mock_status_impl.call_args.args[1:] == (
            "project",
            "agent-hub",
            "codex_startup",
            "main",
        )

    def test_status_command_exits_nonzero_when_probe_fails(self) -> None:
        with patch("agent_hub_st.memory.status_impl", return_value=False):
            result = runner.invoke(app, ["status"])

        assert result.exit_code == 1

    def test_status_impl_renders_failed_probe_compactly(self) -> None:
        out = OutputContext(compact=True)
        result = {
            "status": "failed",
            "attempts": 3,
            "latency_ms": 912,
            "failure": {
                "operation": "progressive-context",
                "error_type": "RuntimeError",
                "error_message": "database unavailable",
            },
        }

        with (
            patch("agent_hub_st.memory_crud.agent_hub_request", return_value=result) as mock_request,
            patch("agent_hub_st.memory_crud.typer.echo") as mock_echo,
        ):
            from agent_hub_st.memory_crud import status_impl

            healthy = status_impl(out, "project", "agent-hub", "claude_session_start", "main")

        assert mock_request.call_args.args == ("GET", "/api/memory/progressive-context")
        assert mock_request.call_args.kwargs["params"] == {
            "query": "memory status probe",
            "consumer_profile": "claude_session_start",
            "current_branch": "main",
        }
        assert mock_request.call_args.kwargs["tool_name"] == "st memory status"
        assert mock_request.call_args.kwargs["retries"] == 3
        assert healthy is False
        first = mock_echo.call_args_list[0].args[0]
        second = mock_echo.call_args_list[1].args[0]
        assert "memory=FAILED" in first
        assert "attempts=3" in first
        assert "failure=RuntimeError" in second

    def test_update_impl_rejects_blank_summary(self) -> None:
        """Blank summaries should fail instead of writing whitespace."""
        with patch("agent_hub_st.memory_crud.fetch_existing_episode") as mock_fetch_existing:
            try:
                update_impl("abc12345", None, None, "   ", None, None, None, None, None, None, None, None, None, None, False, None, False)
            except typer.Exit as exc:
                assert exc.exit_code == 1
            else:
                raise AssertionError("Expected typer.Exit for blank summary")

        mock_fetch_existing.assert_not_called()

    def test_save_impl_rejects_blank_content(self) -> None:
        """Blank content should fail before any API call."""
        out = OutputContext(compact=True)
        with patch("agent_hub_st.memory_crud.agent_hub_request") as mock_request:
            try:
                save_impl(out, "   ", "Use dt for checks", "reference", 80, None, False, None, None, None, None, None, None, None, None, None, None, "global", None)
            except typer.Exit as exc:
                assert exc.exit_code == 1
            else:
                raise AssertionError("Expected typer.Exit for blank content")

        mock_request.assert_not_called()

    def test_update_impl_rejects_blank_content(self) -> None:
        """Blank content updates should fail before loading the episode."""
        with patch("agent_hub_st.memory_crud.fetch_existing_episode") as mock_fetch_existing:
            try:
                update_impl("abc12345", "   ", None, None, None, None, None, None, None, None, None, None, None, None, False, None, False)
            except typer.Exit as exc:
                assert exc.exit_code == 1
            else:
                raise AssertionError("Expected typer.Exit for blank content")

        mock_fetch_existing.assert_not_called()


class TestMemoryListFormatting:
    """Tests for TOON formatting of memory list output."""

    def test_list_formatter_falls_back_to_category(self, capsys) -> None:
        """List output should show tier from API category field when injection_tier is absent."""
        format_list_compact(
            {
                "episodes": [
                    {
                        "uuid": "abc12345-dead-beef-cafe-1234567890ab",
                        "category": "mandate",
                        "summary": "Use dt",
                        "content": "**DT CLI**: Prefer dt.",
                    }
                ],
                "cursor": None,
            }
        )

        out = capsys.readouterr().out
        assert "abc12345 [mandate] summary=Use dt" in out
