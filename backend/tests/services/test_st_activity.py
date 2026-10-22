"""ST footprint regressions at the existing Activity aggregation boundary."""

import json
from pathlib import Path
from types import SimpleNamespace as Row

import pytest

from app.services.st_activity import shell_segments
from tests.services.test_admin_activity_cost import event, snapshot


def test_st_isolated_text_and_elapsed_are_separate_from_usage_and_occupancy():
    result = snapshot([
        event(call="a", tool_input={"command": "st context private-task"}),
        event("tool_result", call="a", seconds=10, returned_characters=81),
        event(call="b", tool_input={"command": ["/usr/bin/st", "--project", "private-project", "web", "search", "private-query"]}),
        event("tool_result", call="b", seconds=10, returned_characters=0),
        event(call="c", tool_input={"cmd": "st check --quick"}, tool_name="functions.exec_command"),
        event("tool_result", call="c", duration_ms=0),
    ])
    st = result["st_commands"]
    assert st["commands"] == 3
    assert st["measured_seconds"] == 20
    assert result["tool_time"]["denominator_seconds"] == 10  # Concurrent intervals merged only here.
    assert st["commands_with_duration"] == 3
    assert st["output_tokens_estimate"] == 21
    assert st["commands_with_output"] == 2  # Empty is known zero; absent is unknown.
    assert result["tokens"]["denominator"] == 0
    assert {row["category"] for row in st["families"]} == {"administration", "substantive", "necessary_support"}
    assert "private-task" not in str(result)
    assert "private-project" not in str(result)
    assert "private-query" not in str(result)


def test_st_compound_calls_never_allocate_shared_output_or_duration():
    result = snapshot([
        event(tool_input={"command": "st context x && st check --quick; cat private-file"}),
        event("tool_result", seconds=12, returned_characters=8000),
    ])["st_commands"]
    assert result["commands"] == 2
    assert result["shared_commands"] == 2
    assert result["calls_with_st"] == result["shell_calls"] == 1
    assert result["input_tokens_estimate"] > 0
    assert result["measured_seconds"] == result["output_tokens_estimate"] == 0
    assert result["commands_with_duration"] == result["commands_with_output"] == 0


@pytest.mark.parametrize("command", ["st context $(secret)", "st context x > private-file", "st context x &", "if true; then st context x; fi", 'st context "unclosed', "st context x |", "st context x &&"])
def test_unsupported_shell_syntax_is_explicitly_unparsed(command):
    st = snapshot([event(tool_input={"command": command})])["st_commands"]
    assert st["commands"] == 0
    assert st["shell_calls_unparsed"] == 1


def test_quoted_operators_are_data_and_safe_family_names_cannot_leak_arguments():
    assert shell_segments("st sessions send recipient 'hello; st web $x | tail'") == [["st", "sessions", "send", "recipient", "hello; st web $x | tail"]]
    st = snapshot([
        event(tool_input={"command": "bash -lc \"st --project=secret sessions send recipient 'hello; st web'\""}),
        event(call="unknown", tool_input={"command": "st private-family private-argument"}),
    ], limit=1)["st_commands"]
    assert st["commands"] == 2
    assert st["families_total"] == 2 and len(st["families"]) == 1
    assert st["unknown_commands"] == 1
    assert st["shell_calls_unparsed"] == 0
    assert "secret" not in str(st) and "private-family" not in str(st)


def test_st_exact_wrappers_duplicates_orphans_and_task_links_keep_existing_rules():
    result = snapshot([
        event(call="wrapper", tool_name="exec_command", tool_input={"cmd": "st context x"}),
        event("tool_result", call="wrapper", seconds=90, returned_characters=9999),
        event(call="native", tool_input={"command": "st context x", "wrapper_candidate_call_id": "wrapper", "wrapper_correlation": "nested_command_digest"}),
        event(call="native", tool_input={"command": "st context x"}),
        event("tool_result", call="native", duration_ms=0, returned_characters=0),
        event("tool_result", call="orphan", tool_input=None, seconds=5, returned_characters=100),
        event(call="unmatched", sid="unknown-session"),
    ], bindings=[Row(session_id="s", project_id="project", task_id="one"), Row(session_id="s", project_id="project", task_id="two")])
    st = result["st_commands"]
    assert st["commands"] == 2
    assert st["commands_with_duration"] == st["commands_with_output"] == 1
    assert st["measured_seconds"] == st["output_tokens_estimate"] == 0
    assert result["task_rollups"] == []
    assert result["wrappers_excluded"] == 1
    assert st["families"][0]["sample_session_id"] == "s"


def test_backend_st_fixture_reconciles_across_the_frontend_boundary():
    result = snapshot([
        event(call="admin", tool_input={"command": "st context task-synthetic"}),
        event("tool_result", call="admin", seconds=2, returned_characters=81),
        event(call="web", tool_input={"cmd": "st web search example"}, tool_name="exec_command"),
        event("tool_result", call="web", duration_ms=0, returned_characters=0),
        event(call="compound", tool_input={"command": "st check --quick && st commit -m synthetic"}),
        event("tool_result", call="compound", seconds=10, returned_characters=1000),
        event(call="unparsed", tool_input={"command": "st context $(example)"}),
    ])
    fixture = Path(__file__).parents[3] / "frontend/src/__tests__/fixtures/st-activity-snapshot.json"
    assert json.loads(fixture.read_text()) == result
    st = result["st_commands"]
    assert st["commands"] == 4 and st["shared_commands"] == 2
    assert st["commands_with_duration"] == st["commands_with_output"] == 2
    assert st["input_tokens_estimate"] == 19
    assert st["output_tokens_estimate"] == 21


