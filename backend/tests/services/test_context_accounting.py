"""Tool-context estimates must stay distinct from time and provider usage."""

from datetime import timedelta

import pytest

from app.services.context_accounting import context_split, tool_context_row
from app.services.session_accounting import accounting_sort_key, summarize_session_duration
from app.services.st_activity import POLICY
from tests.services.test_admin_activity_cost import NOW, event, snapshot
from tests.services.test_session_role_accounting import comparison_sample


def test_context_uses_retained_text_once_with_unknown_and_missing_coverage():
    secret = "fixture-private-argument"
    events = [
        event(call="wrapper", tool_input={"command": secret}),
        event("tool_result", call="wrapper", returned_characters=99999),
        event(call="admin", tool_input={"command": "st context fixture", "wrapper_candidate_call_id": "wrapper", "wrapper_correlation": "nested_command_digest"}),
        event("tool_result", call="admin", returned_characters=400),
        event(call="edit", tool_name="apply_patch", tool_input={"raw": "patch", "format": "opaque"}),
        event("tool_result", call="edit", returned_characters=0),
        event("tool_result", call="orphan", tool_input=None, returned_characters=40),
        event(call="missing", tool_name="unsupported", tool_input={}),
    ]
    result = snapshot(events)
    context = result["context_split"]
    assert context["tools_sampled"] == 4 and context["tools_missing_output"] == 1
    assert context["returned_tokens_estimate"] == 110
    assert context["unknown_tokens_estimate"] >= 10
    assert context["unknown_tokens_estimate"] < context["other_tokens_estimate"]
    assert context["denominator_tokens_estimate"] == context["argument_tokens_estimate"] + 110
    assert result["tokens"]["denominator"] == result["tool_time"]["denominator_seconds"] == 0
    assert secret not in str(result)
    session = summarize_session_duration(events, start=NOW - timedelta(hours=24), end=NOW)
    assert session["context_split"] == context
    assert accounting_sort_key("s", session, "admin_share", "desc")[0] is False
    empty = summarize_session_duration([], start=NOW - timedelta(hours=24), end=NOW)
    assert empty["context_split"]["admin_share"] is None
    assert accounting_sort_key("empty", empty, "admin_share", "desc")[0] is True


def test_tokenizer_budget_fallback_and_capped_sample_are_explicit(monkeypatch):
    monkeypatch.setitem(POLICY, "max_tokenized_characters_per_command", 100)
    monkeypatch.setitem(POLICY, "max_tokenized_characters_per_snapshot", 2)
    calls = [tool_context_row(event(tool_input={"command": "st context fixture"}), None, "administration")]
    data = context_split(calls, truncated=True)
    assert data["tokenized_argument_calls"] == 0 and data["estimated_argument_calls"] == 1
    assert data["tools_missing_output"] == 1 and data["events_truncated"]
    assert data["argument_tokens_estimate"] > 0
    assert data["admin_share"] == 1


def test_group_context_is_weighted_by_text_not_duration():
    from app.services.admin_activity_cost import summarize_activity_cost

    events, costs, ledger, sessions = comparison_sample()
    events.extend([event("tool_result", sid="a", returned_characters=4000),
                   event("tool_result", sid="b", returned_characters=40),
                   event("tool_result", sid="c", returned_characters=400)])
    result = summarize_activity_cost(events, costs, ledger, sessions, [], cutoff=NOW - timedelta(hours=1), now=NOW, limit=5, truncated=False)
    split = result["context_split"]
    assert split["admin_share"] > 0.8
    project = next(row for row in result["by_project"] if row["project_id"] == "p1")
    role = next(row for row in result["by_work_role"] if row["work_role_id"] == "implementation")
    assert project["context_split"] == role["context_split"]
    assert sum(row["context_split"]["denominator_tokens_estimate"] for row in result["by_harness"]) == split["denominator_tokens_estimate"]
    assert result["duration_split"]["admin_share"] != pytest.approx(split["admin_share"])
