"""Tests for st ctx: terse output on busy data, tolerant reads, review decisions built from the queue (HTTP mocked)."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any
from unittest.mock import MagicMock, Mock, patch

import pytest
from agent_hub_st.ctx import app
from typer.testing import CliRunner

runner = CliRunner()
MAX_LINES = 15


def cell(harness: str, name: str, n: int, **changes: Any) -> dict[str, Any]:
    base = {"harness": harness, "cell": name, "n": n, "total": 24000 + n, "harness_tokens": 18000, "ours": 5900, "brief": 80,
            "delta": None, "delta_pct": None, "warn_tokens": 60000, "jump_pct": 25, "flag": None, "future_field": {"x": 1}}
    return base | changes


MATRIX = {
    "days": 14, "jump_pct": 25, "coverage_from": "2026-10-04T16:41:00Z",
    "harnesses": [{"harness": "claude", "version": "2.1.316"}, {"harness": "agent_hub", "version": None}],
    "cells": [*(cell("claude", f"subagent:t{i}", 100 - i) for i in range(30)), cell("codex", "unknown", 5, flag="warn"),
              cell("claude", "lane", 1, total=None, harness_tokens=None, ours=None, brief=None), cell("agent_hub", "agent:chat", 11)],
}


def row(kind: str, target: str, **changes: Any) -> dict[str, Any]:
    base = {
        "key": f"{kind}:{target}", "target_kind": kind, "target_id": target, "title": "Test with Haiku agents", "change": "create",
        "actions": ["keep"], "first_at": "2026-11-01T17:00:00Z", "last_at": "2026-11-01T17:00:00Z", "base_revision": None, "through_revision": "rev-9",
        "version": 4, "scope_before": None, "scope_after": "global", "before": None, "after": {"content": "a\nb\n", "tier": 2},
        "delta_tokens": 128, "tokens_per_day": 17920, "reach": {"since": "2026-11-01T17:00:00Z", "until": "2026-11-01T19:00:00Z", "days": 1.0, "starts_per_day": 140, "starts": 280, "subagent_starts": 30, "receivers": []},
        "also_undoes": [], "writers": [{"session": "aico-widget-1", "harness": "claude", "work_role": "implementation"}],
        "sessions": ["aico-widget-1"], "linked": [], "hint": None,
    }
    return base | changes


QUEUE = {"rows": [row("memory", "3fa2c1d0-aaaa-bbbb"), row("memory", "3fa2ffff-aaaa-bbbb"), row("prompt", "safety-directive", version=None)],
         "summary": {"count": 3, "by_kind": {}, "global_count": 3, "tokens_per_day": 50000, "unknown_reach": 0}, "automatic": [{"key": "x"}]}


def routed(responses: dict[tuple[str, str], Any], seen: list[tuple[str, str, dict[str, Any]]] | None = None) -> Callable[..., Any]:
    def request(method: str, path: str, **kw: Any) -> Any:
        if seen is not None:
            seen.append((method, path, kw))
        return responses[(method, path)]
    return request


def run(args: list[str], responses: dict[tuple[str, str], Any], seen: list | None = None) -> Any:
    with patch("agent_hub_st.ctx.agent_hub_request", routed(responses, seen)), patch("agent_hub_st.ctx_changes.agent_hub_request", routed(responses, seen)):
        return runner.invoke(app, args)


MATRIX_GET = {("GET", "/api/context-observability/matrix"): MATRIX}
QUEUE_GET = {("GET", "/api/context-observability/changes"): QUEUE}


def test_cost_is_terse_on_a_busy_matrix_and_hides_agent_hub_by_default() -> None:
    result = run(["cost"], MATRIX_GET)
    lines = result.output.splitlines()
    assert result.exit_code == 0 and len(lines) <= MAX_LINES
    assert "last 14d against the 14d before" in lines[0] and "harness = its own prompt" in lines[1]  # the abbreviations are keyed
    assert lines[2].startswith("codex/unknown") and "OVER-BUDGET" in lines[2]  # flagged first
    assert "agent_hub" not in result.output and "+20 more cells" in lines[-1]
    assert "—" in run(["cost", "-r", "lane"], MATRIX_GET).output  # unknown is a dash, never 0


def test_cost_json_is_the_filtered_response_and_keeps_unknown_fields() -> None:
    data = json.loads(run(["cost", "-H", "claude", "-r", "subagent", "--json"], MATRIX_GET).output)
    assert data["days"] == 14 and len(data["cells"]) == 30
    assert all(c["harness"] == "claude" and c["future_field"] == {"x": 1} for c in data["cells"])


def test_reads_tolerate_missing_and_new_fields() -> None:
    sparse = {"harness": "claude", "role": "lane", "cause": "none", "brand_new": True}
    for command, path in (("why", "why"), ("trend", "trend"), ("cell", "cell")):
        result = run([command, "claude", "lane"], {("GET", f"/api/context-observability/{path}"): sparse})
        assert result.exit_code == 0, result.output
        assert len(result.output.splitlines()) <= MAX_LINES


def test_why_shows_cause_blocks_and_knob() -> None:
    why = {"cause": "config", "kind": "config", "at": "2026-11-01T14:53:44Z", "summary": "claude lane: 48.0K -> 24.3K",
           "before": {"total": 48000, "n": 113, "version": "2.1.316", "config_fp": "6c6aaea6ff"}, "after": {"total": 24300, "n": 44, "version": "2.1.316", "config_fp": "08535d69aa"},
           "parts": {"harness": -23300, "ours": -400}, "knobs": [{"label": "lane-tools.json", "at": "2026-11-01T14:53:24Z", "ref": "4bb4c49c1"}],
           "blocks": [{"change": "grown", "delta": 235, "label": f"b{i}", "block": f"b{i}", "scope": "global", "writer": {"writer_session": "cc:1"}} for i in range(9)]}
    out = run(["why", "claude", "lane"], {("GET", "/api/context-observability/why"): why}).output
    assert "cause=config" in out and "config file lane-tools.json changed" in out and "harness -23.3K" in out and "request shape 6c6aaea6" in out
    assert len(out.splitlines()) <= MAX_LINES


def test_markers_show_the_newest_few() -> None:
    found = [{"at": f"2026-11-01T1{i % 10}:00:00Z", "kind": "memory", "label": f"m{i}", "ref": str(i), "detail": {"action": "update", "tokens": 90}} for i in range(40)]
    result = run(["markers"], {("GET", "/api/context-observability/markers"): found})
    assert len(result.output.splitlines()) <= MAX_LINES and "40 found, newest 13" in result.output
    assert len(json.loads(run(["markers", "--json"], {("GET", "/api/context-observability/markers"): found}).output)) == 40


def test_budget_shows_levels_and_cells_over_and_sets() -> None:
    levels = [{"harness": "*", "role": "*", "warn_tokens": 60000, "jump_pct": 25, "note": None}, {"harness": "pi", "role": "*", "warn_tokens": 12000, "jump_pct": None}]
    states = [{"harness": "pi", "cell": "hunting", "n_recent": 4, "recent": 13000, "warn_tokens": 12000, "baseline": 8000, "pct": 62.0, "reason": "warn"},
              {"harness": "claude", "cell": "unknown", "n_recent": 9, "recent": 29600, "warn_tokens": 60000, "baseline": 46500, "body_recent": 31000,
               "body_baseline": 22000, "body_pct": 40.9, "reason": "jump"}]
    out = run(["budget"], {("GET", "/api/context-observability/budgets"): levels, ("GET", "/api/context-observability/budget-state"): states}).output
    assert "pi/hunting OVER-BUDGET: 24h median 13.0K is over warn 12.0K" in out
    assert "claude/unknown JUMP: 24h starts 31.0K vs 22.0K the 7 days before (+41%)" in out  # a percent, not the old ratio field
    assert "step alert = the last 24h of starts" in out
    seen: list = []
    done = run(["budget", "set", "pi", "*", "14000", "--note", "n"], {("PUT", "/api/context-observability/budgets"): {"harness": "pi", "role": "*", "warn_tokens": 14000}}, seen)
    assert "pi/* warn 14.0K" in done.output and seen[0][2]["json"] == {"harness": "pi", "role": "*", "warn_tokens": 14000, "note": "n"}


def test_changes_lists_rows_with_short_ids_and_session_filter() -> None:
    seen: list = []
    result = run(["changes", "--session", "aico-widget-1"], QUEUE_GET, seen)
    assert result.exit_code == 0 and len(result.output.splitlines()) <= MAX_LINES
    assert "memory:3fa2c1d0 create global" in result.output and "aico-widget-1 claude/implementation" in result.output
    assert "1 system writes" in result.output
    assert seen[0][2]["params"] == {"session": "aico-widget-1"}


def test_changes_mine_uses_the_aico_session(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AICO_SESSION_ID", "aico-widget-9")
    seen: list = []
    run(["changes", "--mine"], QUEUE_GET, seen)
    assert seen[0][2]["params"] == {"session": "aico-widget-9"}
    monkeypatch.delenv("AICO_SESSION_ID")
    assert run(["changes", "--mine"], QUEUE_GET).exit_code == 2


def test_show_prints_the_diff_within_the_line_cap() -> None:
    changed = row("memory", "3fa2c1d0-aaaa-bbbb", change="update", before={"content": "\n".join(f"old {i}" for i in range(30)), "tier": 3},
                  after={"content": "\n".join(f"new {i}" for i in range(30)), "tier": 2})
    out = run(["show", "memory:3fa2c1d0"], {("GET", "/api/context-observability/changes"): {"rows": [changed]}}).output
    assert len(out.splitlines()) <= MAX_LINES and "tier: 3 -> 2" in out and "-old 0" in out and "more changed lines" in out


def test_keep_sends_the_revision_and_version_the_reviewer_saw() -> None:
    seen: list = []
    response = {("GET", "/api/context-observability/changes"): QUEUE,
                ("POST", "/api/context-observability/changes/keep"): {"results": [{"key": "prompt:safety-directive", "outcome": "recorded"}], "linked_pending": []}}
    result = run(["keep", "safety-directive", "--note", "owner asked"], response, seen)
    assert result.exit_code == 0 and "kept 1 change" in result.output
    body = seen[-1][2]["json"]
    assert body == {"items": [{"target_kind": "prompt", "target_id": "safety-directive", "through_revision": "rev-9"}], "note": "owner asked"}
    memory = run(["keep", "memory:3fa2c1d0"], response, seen)
    assert seen[-1][2]["json"]["items"][0]["expected_version"] == 4 and memory.exit_code == 0


def test_a_prefix_that_matches_two_rows_changes_nothing() -> None:
    seen: list = []
    result = run(["refuse", "3fa2"], QUEUE_GET, seen)
    assert result.exit_code == 1 and [call[0] for call in seen] == ["GET"]
    assert run(["refuse", "nothing-like-it"], QUEUE_GET).exit_code == 1
    assert run(["refuse"], QUEUE_GET).exit_code == 2


def test_refuse_by_session_sends_every_row_and_reports_what_it_also_undid() -> None:
    seen: list = []
    response = {("GET", "/api/context-observability/changes"): QUEUE,
                ("POST", "/api/context-observability/changes/refuse"): {
                    "results": [{"key": "memory:3fa2c1d0-aaaa-bbbb", "outcome": "archived", "also_undid": [{"revision": "r"}]}],
                    "linked_pending": ["memory:zzzz"]}}
    result = run(["refuse", "--session", "aico-widget-1"], response, seen)
    assert len(seen[-1][2]["json"]["items"]) == 3
    assert "archived (also undid 1 later write)" in result.output and "1 more unreviewed from the same sessions" in result.output


def test_rework_edit_and_narrow(tmp_path: Any) -> None:
    seen: list = []
    response = {("GET", "/api/context-observability/changes"): QUEUE,
                ("POST", "/api/context-observability/changes/rework"): {"results": [{"key": "prompt:safety-directive", "outcome": "narrowed"}]}}
    done = run(["rework", "safety-directive", "--narrow", "role:review"], response, seen)
    assert done.exit_code == 0 and seen[-1][2]["json"]["narrow"] == {"to": "role", "role": "review"}
    new = tmp_path / "new.md"
    new.write_text("shorter\n", encoding="utf-8")
    run(["rework", "safety-directive", "-f", str(new), "--summary", "s"], response, seen)
    assert seen[-1][2]["json"]["edit"] == {"content": "shorter\n", "summary": "s"}
    assert run(["rework", "safety-directive"], response).exit_code == 2
    assert run(["rework", "safety-directive", "--narrow", "nowhere"], response).exit_code == 2


def test_decisions_are_written_with_the_writer_header(monkeypatch: pytest.MonkeyPatch) -> None:
    """The real request helper names the deciding session on keep, refuse and rework."""
    monkeypatch.setenv("AGENT_HUB_CONTEXT_PREINJECTED_HASH", "9241d175")
    monkeypatch.setenv("AICO_SESSION_ID", "aico-widget-a36fa317")
    client = Mock()
    client.get.return_value = Mock(status_code=200, **{"json.return_value": QUEUE})
    client.post.return_value = Mock(status_code=200, **{"json.return_value": {"results": []}})
    client_cm = MagicMock()
    client_cm.__enter__.return_value = client
    client_cm.__exit__.return_value = False
    with (
        patch("agent_hub_st.memory_api.load_credentials", return_value=("client-id", "st-memory")),
        patch("agent_hub_st.memory_api.get_agent_hub_url", return_value="http://localhost:8003"),
        patch("agent_hub_st.memory_api.httpx.Client", return_value=client_cm),
    ):
        assert runner.invoke(app, ["keep", "safety-directive"]).exit_code == 0
    assert client.post.call_args.kwargs["headers"]["X-Context-Writer"] == "delivery=9241d175; session=aico-widget-a36fa317"
    assert client.post.call_args.kwargs["headers"]["X-Tool-Name"] == "st ctx"


def test_a_409_detail_object_prints_its_message() -> None:
    from agent_hub_st.memory_api import _format_error_payload

    payload = {"detail": {"message": "Changed since you looked", "key": "memory:1", "latest_revision": "r2"}}
    assert _format_error_payload(payload, "raw") == "Changed since you looked"


def _help(*args: str) -> str:
    """The command's help as one line of words (the table border and wrapping removed)."""
    return " ".join(runner.invoke(app, [*args, "--help"], env={"COLUMNS": "200"}).output.replace("│", " ").split())


def test_cost_json_returns_every_cell_whatever_the_limit_and_the_help_says_so() -> None:
    assert len(json.loads(run(["cost", "--limit", "3", "--json"], MATRIX_GET).output)["cells"]) == 32
    assert "--json always returns every cell" in _help("cost")
    assert len(run(["cost", "--limit", "40"], MATRIX_GET).output.splitlines()) <= MAX_LINES  # a big limit still fits the line cap


def test_cost_says_why_a_big_change_is_not_flagged() -> None:
    held = cell("claude", "subagent:tiny", 4, delta_pct=60.0, flag_held="+60% but only 3 starts in the range before; a flag needs 5 on each side")
    out = run(["cost"], {("GET", "/api/context-observability/matrix"): {**MATRIX, "cells": [held, cell("claude", "subagent:t0", 90)]}}).output
    assert "not flagged: claude/subagent:tiny +60% but only 3 starts" in out and len(out.splitlines()) <= MAX_LINES


def test_a_typo_in_the_harness_or_role_is_an_error_not_an_empty_answer() -> None:
    for command in ("why", "trend", "cell"):
        bad = run([command, "bogus", "lane"], MATRIX_GET)
        assert bad.exit_code == 2 and "bogus" in bad.output, command
    assert run(["cost", "-H", "bogus"], MATRIX_GET).exit_code == 2
    assert run(["markers", "-H", "bogus"], {}).exit_code == 2
    missing = run(["why", "claude", "nosuchrole"], MATRIX_GET)
    assert missing.exit_code == 1 and "No claude cell named 'nosuchrole'" in missing.output
    known = {**MATRIX_GET, ("GET", "/api/context-observability/why"): {"cause": "none"}}
    assert run(["why", "claude", "subagent:t1"], known).exit_code == 0 and run(["why", "claude", "lane"], known).exit_code == 0


def test_a_mistyped_command_names_st_ctx_in_its_usage(capsys: pytest.CaptureFixture[str]) -> None:
    from agent_hub_st.__main__ import main

    with pytest.raises(SystemExit):
        main(["ctx", "cells"])
    err = capsys.readouterr()
    assert "Usage: st ctx" in err.out + err.err and "agent-hub-st" not in err.out + err.err


def test_a_config_marker_says_what_changed() -> None:
    marker = {"at": "2026-11-01T14:53:00Z", "kind": "config", "harness": "claude", "work_role": "implementation", "launch_mode": "project",
              "ref": "08535d69aa", "label": "08535d69aa", "detail": {"from_fp": "6c6aaea6ff", "model": "claude-opus-5-5", "version": "2.1.316"}}
    out = run(["markers"], {("GET", "/api/context-observability/markers"): [marker]}).output
    assert "claude implementation sessions on claude-opus-5-5 v2.1.316 sent a new request shape, 6c6aaea6 -> 08535d69" in out
    assert "config config" not in out


DECIDED = [
    {"id": "11111111-aaaa-bbbb-cccc-000000000001", "target_kind": "memory", "target_id": "3fa2c1d0-aaaa-bbbb-cccc-dddddddddddd", "decision": "keep",
     "through_revision": "rev-9-long", "result_revision": None, "note": "fine", "by": "aico-widget-1", "by_kind": "agent", "created_at": "2026-11-01T18:00:00Z"},
    {"id": "11111111-aaaa-bbbb-cccc-000000000002", "target_kind": "prompt", "target_id": "old-prompt", "decision": "refuse",
     "through_revision": "rev-3", "result_revision": "rev-2", "note": None, "by": "owner", "by_kind": "owner", "created_at": "2026-11-01T17:00:00Z"},
]
DECIDED_GET = {("GET", "/api/context-observability/changes/decisions"): DECIDED}


def test_a_decided_row_prints_an_id_that_show_accepts() -> None:
    listing = run(["changes", "--decided"], DECIDED_GET).output
    printed = next(line.split()[3] for line in listing.splitlines() if "memory:" in line)
    assert printed == "memory:3fa2c1d0-aaaa-bbbb-cccc-dddddddddddd"  # the whole id, not a cut one
    shown = run(["show", printed], {**QUEUE_GET, **DECIDED_GET})
    assert shown.exit_code == 0 and "already decided" in shown.output and "KEEP by aico-widget-1" in shown.output and "note: fine" in shown.output
    assert run(["show", "memory:3fa2c1d0"], {**QUEUE_GET, **DECIDED_GET}).exit_code == 0  # a prefix of it works too
    refused = run(["show", "prompt:old-prompt"], {**QUEUE_GET, **DECIDED_GET}).output
    assert "REFUSE by owner" in refused and "left at revision rev-2" in refused
    assert run(["show", "memory:nothing-at-all"], {**QUEUE_GET, **DECIDED_GET}).exit_code == 1


def test_the_changes_header_is_plain_words() -> None:
    assert "3 waiting for review; 3 of them reach every agent" in run(["changes"], QUEUE_GET).output
    empty = {"rows": [], "summary": {"count": 0, "global_count": 0, "tokens_per_day": 0}, "automatic": []}
    out = run(["changes"], {("GET", "/api/context-observability/changes"): empty}).output
    assert "none waiting for review" in out and "(0 global)" not in out and "tok/day" not in out


def test_the_help_says_what_refuse_undoes_and_that_bare_budget_only_reads() -> None:
    refuse = _help("refuse")
    assert "archived" in refuse and "put back" in refuse
    assert "only reads" in _help("budget")
