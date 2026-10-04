"""Exact-run reference reads keep the existing authenticated feedback boundary."""

from __future__ import annotations

import json
from unittest.mock import patch

import httpx
import pytest
import typer
from typer.testing import CliRunner

from agent_hub_st.__main__ import OWNED_APPS
from agent_hub_st.feedback import app

runner = CliRunner()
REFERENCE = {
    "feedback_item_id": "canonical-feedback-item-id",
    "occurrence_id": "stable-occurrence-id",
    "run_ref": "neri:run/exact-root",
    "role": "hunter",
    "source_project_id": "neri",
    "component_id": "sf.cli",
    "feedback_type": "friction",
    "status": "acknowledged",
    "title": "Retained compact observation",
    "occurred_at": "2026-10-04T20:00:00Z",
    "item_updated_at": "2026-10-04T21:00:00Z",
}
PAYLOAD = {"references": [REFERENCE], "count": 1}


def test_references_deduplicates_exact_runs_and_outputs_only_reference_json() -> None:
    with patch("agent_hub_st.feedback_commands.feedback_request", return_value=PAYLOAD) as request:
        result = runner.invoke(app, [
            "references", "--run-ref", " neri:run/exact-root ",
            "--run-ref", "neri:run/exact-root", "--run-ref", "neri:run/exact-root-2",
            "--run-ref", "NERI:run/exact-root", "--json",
        ])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == PAYLOAD
    request.assert_called_once_with(
        "GET", "/api/feedback/references",
        params={"run_ref": ["neri:run/exact-root", "neri:run/exact-root-2", "NERI:run/exact-root"]},
    )
    assert not {"description", "consequence", "workaround", "evidence_refs", "votes"} & REFERENCE.keys()


def test_compact_output_preserves_canonical_ids_and_scope() -> None:
    with patch("agent_hub_st.feedback_commands.feedback_request", return_value=PAYLOAD) as request:
        result = runner.invoke(app, ["references", "--run-ref", REFERENCE["run_ref"]])
    assert result.exit_code == 0, result.output
    assert result.output == (
        "FEEDBACK_REFERENCES[1]\n"
        "canonical-feedback-item-id|occurrence=stable-occurrence-id|run=neri:run/exact-root|"
        "role=hunter|project=neri|sf.cli|friction|acknowledged|"
        "occurred_at=2026-10-04T20:00:00Z|updated_at=2026-10-04T21:00:00Z|"
        "Retained compact observation\n"
    )
    request.assert_called_once_with("GET", "/api/feedback/references", params={"run_ref": [REFERENCE["run_ref"]]})


@pytest.mark.parametrize("args", [[], ["--run-ref", ""], ["--run-ref", "   "]])
def test_references_requires_a_nonblank_run_before_any_request(args: list[str]) -> None:
    with patch("agent_hub_st.feedback_commands.feedback_request") as request:
        result = runner.invoke(app, ["references", *args])
    assert result.exit_code == 2
    assert "run-ref" in result.output
    request.assert_not_called()


def test_references_rejects_more_than_twenty_distinct_runs() -> None:
    args = [value for index in range(21) for value in ("--run-ref", f"run-{index}")]
    with patch("agent_hub_st.feedback_commands.feedback_request") as request:
        result = runner.invoke(app, ["references", *args])
    assert result.exit_code == 2
    assert "At most 20" in result.output
    request.assert_not_called()


@pytest.mark.parametrize("json_output", [False, True])
def test_empty_reconciliation_is_one_read_without_lifecycle_mutation(json_output: bool) -> None:
    args = ["references", "--run-ref", "unknown-run", *(["--json"] if json_output else [])]
    with patch("agent_hub_st.feedback_commands.feedback_request", return_value={"references": [], "count": 0}) as request:
        result = runner.invoke(app, args)
    assert result.exit_code == 0
    if json_output:
        assert json.loads(result.output) == {"references": [], "count": 0}
    else:
        assert result.output == "FEEDBACK_REFERENCES[0]\n"
    request.assert_called_once_with("GET", "/api/feedback/references", params={"run_ref": ["unknown-run"]})


def test_references_uses_existing_authenticated_transport_and_repeated_query_keys() -> None:
    calls = []

    def respond(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json=PAYLOAD)

    client = httpx.Client(transport=httpx.MockTransport(respond))
    with (
        patch("agent_hub_st.feedback_api.load_credentials", return_value=("owner-client", "reference-test")),
        patch("agent_hub_st.feedback_api.get_agent_hub_url", return_value="https://agent-hub.invalid"),
        patch("agent_hub_st.feedback_api.httpx.Client", return_value=client),
    ):
        result = runner.invoke(app, ["references", "--run-ref", "run/root", "--run-ref", "run/root-2", "--json"])
    assert result.exit_code == 0, result.output
    assert len(calls) == 1
    request = calls[0]
    assert request.method == "GET"
    assert request.url.path == "/api/feedback/references"
    assert request.url.params.multi_items() == [("run_ref", "run/root"), ("run_ref", "run/root-2")]
    assert request.headers["X-Client-Id"] == "owner-client"
    assert request.headers["X-Request-Source"] == "reference-test"
    assert request.content == b""


def test_request_failure_propagates_without_retry_or_other_actions() -> None:
    with patch("agent_hub_st.feedback_commands.feedback_request", side_effect=typer.Exit(1)) as request:
        result = runner.invoke(app, ["references", "--run-ref", "known-run"])
    assert result.exit_code == 1
    request.assert_called_once_with("GET", "/api/feedback/references", params={"run_ref": ["known-run"]})


def test_owned_feedback_extension_registers_reference_command() -> None:
    assert OWNED_APPS["feedback"] is app
    result = runner.invoke(OWNED_APPS["feedback"], ["references", "--help"])
    assert result.exit_code == 0
    assert "--run-ref" in result.output and "--json" in result.output
