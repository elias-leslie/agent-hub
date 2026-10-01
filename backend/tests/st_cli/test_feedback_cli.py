"""Tests for feedback CLI argument validation."""

from __future__ import annotations

from unittest.mock import patch

from agent_hub_st.feedback import app
from typer.testing import CliRunner

runner = CliRunner()


class TestFeedbackLimitValidation:
    """Feedback list/search should reject out-of-range limits locally."""

    def test_list_rejects_limit_above_api_cap(self) -> None:
        result = runner.invoke(app, ["list", "--limit", "201"])

        assert result.exit_code == 1
        assert "Limit must be between 1 and 200." in result.output

    def test_search_rejects_limit_above_api_cap(self) -> None:
        result = runner.invoke(app, ["search", "audit", "--limit", "201"])

        assert result.exit_code == 1
        assert "Limit must be between 1 and 200." in result.output

    def test_list_accepts_limit_at_api_cap(self) -> None:
        with patch("agent_hub_st.feedback.list_impl") as mock_list_impl:
            result = runner.invoke(app, ["list", "--limit", "200"])

        assert result.exit_code == 0
        mock_list_impl.assert_called_once()

    def test_search_accepts_limit_at_api_cap(self) -> None:
        with patch("agent_hub_st.feedback.search_impl") as mock_search_impl:
            result = runner.invoke(app, ["search", "audit", "--limit", "200"])

        assert result.exit_code == 0
        mock_search_impl.assert_called_once()


class TestFeedbackSortValidation:
    """Feedback list/search should reject invalid sort values locally."""

    def test_list_rejects_invalid_sort_with_valid_values(self) -> None:
        result = runner.invoke(app, ["list", "--sort", "recent"])

        assert result.exit_code == 1
        assert "Invalid sort" in result.output
        assert "recent" in result.output
        assert "Valid sorts: votes, newest, oldest" in result.output

    def test_search_rejects_invalid_sort_with_valid_values(self) -> None:
        result = runner.invoke(app, ["search", "audit", "--sort", "recent"])

        assert result.exit_code == 1
        assert "Invalid sort" in result.output
        assert "recent" in result.output
        assert "Valid sorts: votes, newest, oldest" in result.output


class TestFeedbackCommandRouting:
    """Feedback command flags should wire through to implementations."""

    def test_search_accepts_explicit_query_option(self) -> None:
        with patch("agent_hub_st.feedback.search_impl") as mock_search_impl:
            result = runner.invoke(app, ["search", "--query", "--frontend-only compiler flag"])

        assert result.exit_code == 0
        assert mock_search_impl.call_args.args[0] == "--frontend-only compiler flag"

    def test_search_rejects_positional_query_with_query_option(self) -> None:
        with patch("agent_hub_st.feedback.search_impl") as mock_search_impl:
            result = runner.invoke(app, ["search", "memory", "--query", "error"])

        assert result.exit_code == 2
        assert "Specify either SEARCH query or --query, not both" in result.output
        mock_search_impl.assert_not_called()

    def test_report_passes_vote_if_match(self) -> None:
        with patch("agent_hub_st.feedback.report_impl") as mock_report_impl:
            result = runner.invoke(
                app,
                [
                    "report",
                    "sf.cli",
                    "Existing duplicate",
                    "--session",
                    "sess-123",
                    "--vote-if-match",
                ],
            )

        assert result.exit_code == 0
        assert mock_report_impl.call_args.kwargs["vote_if_duplicate"]

    def test_archive_routes_to_archive_impl(self) -> None:
        with patch("agent_hub_st.feedback.archive_impl") as mock_archive_impl:
            result = runner.invoke(app, ["archive", "deadbeef", "--note", "aged out"])

        assert result.exit_code == 0
        mock_archive_impl.assert_called_once_with("deadbeef", note="aged out")

    def test_resolve_accepts_message_alias(self) -> None:
        with patch("agent_hub_st.feedback.resolve_impl") as mock_resolve_impl:
            result = runner.invoke(app, ["resolve", "deadbeef", "-m", "fixed"])

        assert result.exit_code == 0
        mock_resolve_impl.assert_called_once_with("deadbeef", note="fixed")

    def test_merge_routes_to_merge_impl(self) -> None:
        with patch("agent_hub_st.feedback.merge_impl") as mock_merge_impl:
            result = runner.invoke(app, ["merge", "deadbeef", "feedcafe"])

        assert result.exit_code == 0
        mock_merge_impl.assert_called_once_with("deadbeef", "feedcafe")

    def test_get_accepts_json_output(self) -> None:
        with patch("agent_hub_st.feedback.get_impl") as mock_get_impl:
            result = runner.invoke(app, ["get", "deadbeef", "--json"])

        assert result.exit_code == 0
        mock_get_impl.assert_called_once_with("deadbeef", json_output=True)


def test_native_occurrence_metadata_and_explicit_link():
    from agent_hub_st.feedback_commands import link_impl, report_impl, vote_impl

    metadata = {"occurrence_id": "origin-a", "source_project_id": "domain-a", "run_ref": "run-a",
                "role": "reporter", "evidence_refs": ["sanitized:artifact"], "consequence": "Delayed output"}
    with patch("agent_hub_st.feedback_commands.feedback_request", return_value={"created": True, "item": {}}) as request:
        report_impl("xc.product", "Native feedback", project_id="domain-a", occurrence=metadata)
        assert request.call_args.kwargs["json"]["occurrence_id"] == "origin-a"
        vote_impl("item-id", occurrence=metadata)
        assert request.call_args_list[-2].kwargs["json"]["run_ref"] == "run-a"
        assert "session_id" not in request.call_args_list[-2].kwargs["json"]
        link_impl("item-id", "task-explicit")
        assert request.call_args.args[:2] == ("PATCH", "/api/feedback/item-id")
        assert request.call_args.kwargs["json"] == {"linked_task_id": "task-explicit"}


def test_sessionless_occurrence_vote_replay_has_safe_output(capsys):
    from agent_hub_st.feedback_commands import vote_impl

    with patch("agent_hub_st.feedback_commands.feedback_request", return_value={"message": "Already voted"}) as request:
        vote_impl("item-id", occurrence={"occurrence_id": "origin-a"})
    request.assert_called_once()
    assert "VOTE:ALREADY_VOTED:item-id|origin-a" in capsys.readouterr().out
