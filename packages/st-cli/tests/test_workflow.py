"""st workflow: payload building, Aico env fill, wait state diffs and exit codes, --set parsing (HTTP mocked)."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
import typer
from typer.testing import CliRunner

from agent_hub_st import workflow, workflow_wait
from agent_hub_st.workflow_format import run_text, step_line

runner = CliRunner()
ENV = {"AICO_SESSION_ID": "aico-widget-1", "AICO_AGENT_SLUG": "claude-code"}


def attempt(**overrides: Any) -> dict[str, Any]:
    base = {
        "requested_model": "m/flash", "served_model": "m/flash", "fallback_used": False, "fallback_reason": None,
        "decision": {"action": "complete", "reason": "completed"},
        "cost": {"usd": 0.0023, "basis": "metered", "source": "catalog_estimate"},
    }
    return base | overrides


def step(key: str, status: str = "pending", **overrides: Any) -> dict[str, Any]:
    base = {"key": key, "status": status, "attempts": 0, "attempt_limit": 2, "chain": ["m/flash"], "attempt_history": [],
            "outcome": None, "live": None, "readiness": None}
    return base | overrides


def view(state: str = "running", steps: list[dict[str, Any]] | None = None, **overrides: Any) -> dict[str, Any]:
    base = {"id": "run-1", "state": state, "goal": "g", "plan_revision": 0, "pause": None, "failure": None,
            "steps": steps if steps is not None else [step("a")], "usage_totals": {"total_tokens": 0, "cost": {}}}
    return base | overrides


@pytest.fixture(autouse=True)
def frontend(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENT_HUB_URL", "http://hub.test:8003")
    monkeypatch.delenv("AGENT_HUB_FRONTEND_URL", raising=False)
    monkeypatch.delenv("AGENT_HUB_FRONTEND_PORT", raising=False)
    monkeypatch.delenv("AICO_SESSION_ID", raising=False)  # tests run inside Aico sessions
    monkeypatch.delenv("AICO_AGENT_SLUG", raising=False)


# --- payloads -----------------------------------------------------------------------------------------------


def test_create_payload_fills_launcher_from_aico_env_and_keeps_file_values() -> None:
    payload = workflow.build_create_payload({"goal": "g", "steps": []}, request_id="r1", max_concurrent_steps=2, env=ENV)
    assert payload == {"goal": "g", "steps": [], "launched_by": "aico-widget-1", "coordinator": "claude-code",
                       "request_id": "r1", "policy": {"max_concurrent_steps": 2}}
    explicit = workflow.build_create_payload({"launched_by": "mine", "coordinator": "x"}, env=ENV)
    assert (explicit["launched_by"], explicit["coordinator"]) == ("mine", "x")
    assert workflow.build_create_payload({"goal": "g"}, env={}) == {"goal": "g"}


def test_create_payload_merges_the_concurrency_flag_into_the_files_policy() -> None:
    payload = workflow.build_create_payload(
        {"goal": "g", "policy": {"max_attempts": 4, "max_concurrent_steps": 1}}, max_concurrent_steps=3, env={}
    )
    assert payload == {"goal": "g", "policy": {"max_attempts": 4, "max_concurrent_steps": 3}}
    assert "max_concurrent_steps" not in payload  # RunDefinition forbids it at the top level
    untouched = workflow.build_create_payload({"goal": "g", "policy": {"max_attempts": 4}}, env={})
    assert untouched == {"goal": "g", "policy": {"max_attempts": 4}}


def test_create_payload_merges_the_tool_level_flag_into_the_files_policy() -> None:
    payload = workflow.build_create_payload(
        {"goal": "g", "policy": {"max_concurrent_steps": 2, "tool_level": "full"}}, tool_level="read",
        max_concurrent_steps=3, env={},
    )
    assert payload == {"goal": "g", "policy": {"max_concurrent_steps": 3, "tool_level": "read"}}
    assert "tool_level" not in workflow.build_create_payload({"goal": "g"}, env={}).get("policy", {})


def test_run_view_shows_the_tool_level() -> None:
    from agent_hub_st.workflow_format import run_text

    assert "tool level: read" in run_text(view(tool_level="read"))
    assert "tool level" not in run_text(view())


def test_create_command_posts_definition_and_prints_run_and_page_url(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    for name, value in ENV.items():
        monkeypatch.setenv(name, value)
    path = tmp_path / "def.json"
    path.write_text(json.dumps({"goal": "g", "project_id": "p", "steps": [{"key": "a"}]}))
    with patch.object(workflow, "agent_hub_request", return_value=view() | {"created": True}) as request:
        result = runner.invoke(workflow.app, ["create", "--file", str(path), "--request-id", "r1"])
    assert result.exit_code == 0, result.output
    method, api_path = request.call_args.args
    assert (method, api_path) == ("POST", "/api/workflow-runs")
    sent = request.call_args.kwargs["json"]
    assert sent["launched_by"] == "aico-widget-1" and sent["request_id"] == "r1"
    assert request.call_args.kwargs["tool_name"] == "st workflow"
    assert "run run-1 running" in result.output
    assert "page: http://hub.test:3003/workflow-runs/run-1" in result.output


def test_create_reports_an_existing_run_for_a_repeated_request_id(tmp_path: Path) -> None:
    path = tmp_path / "def.json"
    path.write_text(json.dumps({"goal": "g", "steps": []}))
    with patch.object(workflow, "agent_hub_request", return_value=view() | {"created": False}):
        result = runner.invoke(workflow.app, ["create", "--file", str(path), "--request-id", "r1"])
    assert "existing run for request_id r1" in result.output


def test_page_url_comes_from_config(monkeypatch: pytest.MonkeyPatch) -> None:
    assert workflow.page_url("x") == "http://hub.test:3003/workflow-runs/x"
    monkeypatch.setenv("AGENT_HUB_FRONTEND_PORT", "4000")
    assert workflow.page_url("x") == "http://hub.test:4000/workflow-runs/x"
    monkeypatch.setenv("AGENT_HUB_FRONTEND_URL", "https://hub.example/")
    assert workflow.page_url("x") == "https://hub.example/workflow-runs/x"


def test_create_rejects_unreadable_or_non_object_input(tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text("[1]")
    with patch.object(workflow, "agent_hub_request") as request:
        assert runner.invoke(workflow.app, ["create", "--file", str(bad)]).exit_code == 2
        assert runner.invoke(workflow.app, ["create", "--file", str(tmp_path / "missing.json")]).exit_code == 2
    request.assert_not_called()


def test_add_payload_accepts_step_list_or_wrapper_and_stamps_who_and_why() -> None:
    one = workflow.build_add_payload({"key": "b"}, after="a", reason="more", env=ENV)
    assert one == {"steps": [{"key": "b"}], "after": "a", "changed_by": "aico-widget-1", "reason": "more"}
    assert workflow.build_add_payload([{"key": "b"}], env={})["steps"] == [{"key": "b"}]
    wrapped = workflow.build_add_payload({"steps": [{"key": "b"}], "reason": "file wins"}, reason="flag", env={})
    assert wrapped["reason"] == "file wins"
    with pytest.raises(ValueError):
        workflow.build_add_payload("nope")


def test_add_step_command_sends_to_steps_path(tmp_path: Path) -> None:
    path = tmp_path / "s.json"
    path.write_text(json.dumps({"key": "b", "instructions": "i", "agent_slug": "coder"}))
    with patch.object(workflow, "agent_hub_request", return_value={"state": "running", "plan_revision": 1}) as request:
        result = runner.invoke(workflow.app, ["add-step", "run-1", "--file", str(path), "--after", "a"])
    assert result.exit_code == 0 and "added b; plan r1" in result.output
    assert request.call_args.args == ("POST", "/api/workflow-runs/run-1/steps")
    assert request.call_args.kwargs["json"]["after"] == "a"


# --- revise --set ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("pair", "expected"),
    [
        ("model_override=opencode-go/deepseek-v4-pro", ("model_override", "opencode-go/deepseek-v4-pro")),
        ("model_override=null", ("model_override", None)),
        ("instructions=null", ("instructions", "null")),
        ("instructions=1 + 1 = 2", ("instructions", "1 + 1 = 2")),
        ("max_attempts=3", ("max_attempts", 3)),
        ("max_attempts=null", ("max_attempts", None)),
        ("allowed_models=a,b", ("allowed_models", ["a", "b"])),
        ('allowed_models=["a","b"]', ("allowed_models", ["a", "b"])),
        ("depends_on=[]", ("depends_on", [])),
        ("depends_on=", ("depends_on", [])),
        ("depends_on=null", ("depends_on", None)),
        ("acceptance=pytest -q", ("acceptance", ["pytest -q"])),
        ('acceptance=[{"cmd":"make","timeout_s":60}]', ("acceptance", [{"cmd": "make", "timeout_s": 60}])),
    ],
)
def test_set_parsing(pair: str, expected: tuple[str, Any]) -> None:
    assert workflow.parse_set(pair) == expected


@pytest.mark.parametrize("pair", ["nofield", "bogus=1", "max_attempts=many", "max_attempts=1.5", "max_attempts=true"])
def test_set_parsing_rejects_unknown_fields_and_bad_numbers(pair: str) -> None:
    with pytest.raises(ValueError):
        workflow.parse_set(pair)


def test_revision_payload_merges_file_then_sets_and_requires_a_change() -> None:
    body = workflow.build_revision_payload(["effort=high", "max_attempts=2"], {"effort": "low", "instructions": "x"},
                                           reason="why", env=ENV)
    assert body == {"effort": "high", "instructions": "x", "max_attempts": 2, "changed_by": "aico-widget-1", "reason": "why"}
    with pytest.raises(ValueError):
        workflow.build_revision_payload([], None, reason="only a reason", env=ENV)


def test_revise_command_patches_the_step_and_remove_sends_a_body() -> None:
    with patch.object(workflow, "agent_hub_request", return_value={"state": "running", "plan_revision": 3}) as request:
        result = runner.invoke(workflow.app, ["revise", "run-1", "b", "--set", "effort=high", "--reason", "harder"])
        assert result.exit_code == 0 and "revised b (effort); plan r3" in result.output
        assert request.call_args.args == ("PATCH", "/api/workflow-runs/run-1/steps/b")
        assert request.call_args.kwargs["json"]["effort"] == "high"
        removed = runner.invoke(workflow.app, ["remove-step", "run-1", "b", "--reason", "not needed"])
        assert removed.exit_code == 0
        assert request.call_args.args == ("DELETE", "/api/workflow-runs/run-1/steps/b")
        assert request.call_args.kwargs["json"] == {"reason": "not needed"}
    assert runner.invoke(workflow.app, ["revise", "run-1", "b", "--set", "bogus=1"]).exit_code == 2


# --- cancel / resume / list -----------------------------------------------------------------------------------


def test_cancel_run_or_step_and_resume_actions() -> None:
    with patch.object(workflow, "agent_hub_request", return_value={"state": "running", "cancelling": True, "step": "b", "status": "pending"}) as request:
        assert runner.invoke(workflow.app, ["cancel", "run-1", "--reason", "stop"]).exit_code == 0
        assert request.call_args.args == ("POST", "/api/workflow-runs/run-1/cancel")
        assert request.call_args.kwargs["json"] == {"reason": "stop"}
        assert runner.invoke(workflow.app, ["cancel", "run-1", "--step", "b"]).exit_code == 0
        assert request.call_args.args == ("POST", "/api/workflow-runs/run-1/steps/b/cancel")
        assert request.call_args.kwargs["json"] is None
        ok = runner.invoke(workflow.app, ["resume", "run-1", "--action", "retry", "--extra-attempts", "2", "--model", "m"])
        assert ok.exit_code == 0
        assert request.call_args.args == ("POST", "/api/workflow-runs/run-1/resume")
        assert request.call_args.kwargs["json"] == {"action": "retry", "model": "m", "extra_attempts": 2}
        calls = request.call_count
        assert runner.invoke(workflow.app, ["resume", "run-1", "--action", "skip", "--extra-attempts", "2"]).exit_code == 2
        assert runner.invoke(workflow.app, ["resume", "run-1", "--action", "explode"]).exit_code == 2
        assert request.call_count == calls


def test_list_mine_asks_the_server_to_filter_by_session_and_needs_the_env(monkeypatch: pytest.MonkeyPatch) -> None:
    rows = {"runs": [{"id": "r1", "state": "running", "launched_by": "aico-widget-1", "goal": "mine", "step_counts": {"running": 1}}]}
    monkeypatch.delenv("AICO_SESSION_ID", raising=False)
    with patch.object(workflow, "agent_hub_request", return_value=rows) as request:
        assert runner.invoke(workflow.app, ["list", "--mine"]).exit_code == 2
        everyone = runner.invoke(workflow.app, ["list"])
        assert "r1" in everyone.output
        assert "launched_by" not in request.call_args.kwargs["params"]
        monkeypatch.setenv("AICO_SESSION_ID", "aico-widget-1")
        mine = runner.invoke(workflow.app, ["list", "--mine", "--limit", "5"])
    assert "r1" in mine.output
    assert request.call_args.kwargs["params"] == {"limit": 5, "offset": 0, "launched_by": "aico-widget-1"}


# --- text view --------------------------------------------------------------------------------------------------


def test_step_line_shows_models_fallback_attempts_live_phase_and_cost() -> None:
    running = step("a", "running", attempts=2, attempt_limit=3, attempt_history=[
        attempt(requested_model="m/pro", served_model="m/flash", fallback_used=True, fallback_reason="usage_limit",
                decision={"action": "retry", "reason": "usage_limit"})],
        live={"phase": "tool:write", "last_event_at": "2026-10-28T10:00:00+00:00", "harness_alive": True})
    from datetime import datetime
    line = step_line(running, datetime.fromisoformat("2026-10-28T10:00:12+00:00"))
    for part in ("a | running", "m/pro→m/flash", "fallback(usage_limit)", "attempt 2/3", "live=tool:write last=12s ago", "$0.0023 metered"):
        assert part in line
    unpriced = step("b", "completed", attempt_history=[attempt(cost={"usd": None, "basis": "unknown"})])
    assert "$? unknown" in step_line(unpriced)


def test_a_pause_with_several_waiting_steps_lists_each_one_once() -> None:
    from agent_hub_st.workflow_format import pause_text

    pause = {"reason": "chain_exhausted", "step_key": "a", "waiting": {
        "a": {"reason": "chain_exhausted"}, "b": {"reason": "tools_unavailable", "error": "x"}}}
    text = pause_text(pause)
    assert text == "chain_exhausted step_key=a | waiting: a (chain_exhausted), b (tools_unavailable)"
    one = {"reason": "chain_exhausted", "step_key": "a", "waiting": {"a": {"reason": "chain_exhausted"}}}
    assert pause_text(one) == "chain_exhausted step_key=a"


def test_the_same_model_spelled_two_ways_is_not_shown_as_a_switch_and_a_real_switch_is() -> None:
    same = step("a", "completed", attempt_history=[
        attempt(requested_model="opencode-go/deepseek-v4.1-flash", served_model="deepseek-v4.1-flash")])
    assert "→" not in step_line(same)
    real = step("a", "completed", attempt_history=[
        attempt(requested_model="opencode-go/deepseek-v4.1-flash", served_model="opencode-go/kimi-k3")])
    assert "opencode-go/deepseek-v4.1-flash→opencode-go/kimi-k3" in step_line(real)


def test_step_line_shows_the_tools_the_last_attempt_got_and_says_none_when_it_got_none() -> None:
    narrowed = step("a", "needs_owner", attempt_history=[attempt(tools=["read_file"])])
    assert "tools=read_file" in step_line(narrowed)
    assert "tools=none" in step_line(step("a", "failed", attempt_history=[attempt(tools=[])]))
    assert "tools=" not in step_line(step("a", "failed", attempt_history=[attempt()]))  # not reported is not "none"


def test_a_fresh_run_and_a_just_started_attempt_format_without_numbers_or_cost() -> None:
    fresh = view(usage_totals={"total_tokens": None, "cost": {}})
    started = step("a", "running", attempts=1, attempt_history=[
        {"status": "active", "requested_model": None, "served_model": None, "usage": None,
         "cost": {"usd": None, "basis": "unknown"}}])
    text = run_text(view(steps=[started], usage_totals=fresh["usage_totals"]))
    assert "a | running | m/flash | attempt 1/2" in text and "$?" not in text
    assert "totals: 0 tokens; cost no usage yet" in text


def test_run_text_has_header_steps_totals_and_pause() -> None:
    paused = view("needs_owner", [step("a", "needs_owner")], pause={"reason": "chain_exhausted", "step_key": "a", "at": 1},
                  usage_totals={"total_tokens": 12345, "cost": {"by_basis": {"metered": {"usd": 0.5, "attempts": 2}}}})
    text = run_text(paused, "http://x/y")
    assert "needs owner: chain_exhausted step_key=a" in text and "page: http://x/y" in text
    assert "totals: 12,345 tokens; cost $0.5000 metered (2 attempts)" in text


# --- wait ------------------------------------------------------------------------------------------------------


class Script:
    """Feeds wait_for a sequence of run views and records sleeps, output and a fake clock."""

    def __init__(self, views: list[Any]) -> None:
        self.views: Iterator[Any] = iter(views)
        self.last: Any = None
        self.slept: list[float] = []
        self.out: list[str] = []
        self.now = 0.0

    def fetch(self) -> dict[str, Any]:
        item = next(self.views, self.last)
        self.last = item
        if isinstance(item, Exception):
            raise item
        return item

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds

    def run(self, until: str, **kwargs: Any) -> int:
        return workflow_wait.wait_for(self.fetch, until, emit=self.out.append, sleep=self.sleep, clock=lambda: self.now, **kwargs)


def test_wait_done_prints_changes_backs_off_and_resets_on_change() -> None:
    running = view(steps=[step("a", "running", attempts=1)])
    script = Script([
        view(steps=[step("a", "pending")]), view(steps=[step("a", "pending")]), view(steps=[step("a", "pending")]),
        running, running,
        view("completed", [step("a", "completed", attempts=1, attempt_history=[attempt()])]),
    ])
    assert script.run("done") == workflow_wait.EXIT_DONE
    assert script.slept == [2.0, 3.0, 4.5, 2.0, 3.0]  # backoff x1.5 from poll_min, reset when the step started
    text = "\n".join(script.out)
    assert "step a: pending → running, attempt 1" in text
    assert "run: running → completed" in text
    assert text.count("run run-1") == 2  # first line and the final view only; no repeat per poll


@pytest.mark.parametrize(
    ("final", "code"),
    [
        (view("failed", failure="boom"), workflow_wait.EXIT_FAILED),
        (view("cancelled"), workflow_wait.EXIT_CANCELLED),
        (view("needs_owner", pause={"reason": "chain_exhausted", "step_key": "a"}), workflow_wait.EXIT_NEEDS_OWNER),
    ],
)
def test_wait_exit_code_per_end_condition(final: dict[str, Any], code: int) -> None:
    assert Script([view(), final]).run("done") == code
    assert Script([view(), final]).run("needs_owner") == code


def test_wait_keeps_waiting_through_a_pause_that_clears_itself() -> None:
    waiting = view("needs_owner", pause={"reason": "usage_limit_wait", "step_key": "a"})
    script = Script([view(), waiting, waiting, view("completed")])
    assert script.run("needs_owner") == workflow_wait.EXIT_DONE
    assert "run: running → needs_owner (usage_limit_wait step_key=a)" in "\n".join(script.out)


def test_wait_returns_for_the_owner_when_any_waiting_entry_needs_them() -> None:
    mixed = view("needs_owner", pause={"reason": "usage_limit_wait", "step_key": "a", "waiting": {
        "a": {"reason": "usage_limit_wait"}, "b": {"reason": "owner_only_category"}}})
    assert workflow_wait.needs_decision(mixed)
    assert Script([view(), mixed]).run("needs_owner") == workflow_wait.EXIT_NEEDS_OWNER
    resets = view("needs_owner", pause={"reason": "usage_limit_wait", "step_key": "a", "waiting": {
        "a": {"reason": "usage_limit_wait"}, "b": {"reason": "usage_limit_wait"}}})
    assert not workflow_wait.needs_decision(resets)


def test_wait_step_condition_codes() -> None:
    steps_done = view(steps=[step("a", "completed"), step("b", "pending")])
    assert Script([view(steps=[step("a", "running"), step("b", "pending")]), steps_done]).run("step:a") == workflow_wait.EXIT_STEP_DONE
    failed = view(steps=[step("a", "failed"), step("b", "pending")])
    assert Script([view(steps=[step("a", "running")]), failed]).run("step:a") == workflow_wait.EXIT_STEP_ENDED
    # a step added later can still be awaited; a finished run without it is an error
    assert Script([view(), view(steps=[step("a"), step("late", "completed")])]).run("step:late") == workflow_wait.EXIT_STEP_DONE
    assert Script([view("completed")]).run("step:nope") == workflow_wait.EXIT_ERROR
    # a pause for the owner ends a step wait too
    paused = view("needs_owner", pause={"reason": "chain_exhausted", "step_key": "a"})
    assert Script([view(), paused]).run("step:b") == workflow_wait.EXIT_NEEDS_OWNER


def test_wait_any_change_ignores_live_phase_but_sees_plan_and_status() -> None:
    quiet = view(steps=[step("a", "running", live={"phase": "thinking"})])
    chatty = view(steps=[step("a", "running", live={"phase": "tool:bash"})])
    script = Script([quiet, chatty, chatty, view(steps=[step("a", "running"), step("b")], plan_revision=1)])
    assert script.run("any-change") == workflow_wait.EXIT_CHANGED
    text = "\n".join(script.out)
    assert "plan: revision 0 → 1" in text and "step b: added (pending)" in text and "tool:bash" not in text


def test_wait_max_wait_returns_control_without_cancelling() -> None:
    script = Script([view()])
    with patch.object(workflow, "_api") as api:
        code = script.run("done", max_wait=25.0)
    assert code == workflow_wait.EXIT_MAX_WAIT
    assert script.now >= 25.0
    api.assert_not_called()
    assert "still running" in script.out[-1]


def test_wait_has_no_time_limit_by_default() -> None:
    script = Script([view()] * 500 + [view("completed")])
    assert script.run("done") == workflow_wait.EXIT_DONE
    assert script.now > 3600  # over an hour of fake time, still waiting


def test_wait_survives_read_failures_and_gives_up_only_on_consecutive_ones() -> None:
    recovered = Script([view(), typer.Exit(1), typer.Exit(1), view("completed")])
    assert recovered.run("done") == workflow_wait.EXIT_DONE
    assert Script([view(), typer.Exit(1)]).run("done", max_errors=3) == workflow_wait.EXIT_LOST_CONTACT
    with pytest.raises(typer.Exit):  # the first read is strict: a wrong run id fails at once
        Script([typer.Exit(1)]).run("done")


def test_wait_command_exits_with_the_wait_code() -> None:
    with patch.object(workflow, "agent_hub_request", side_effect=[view(), view("failed", failure="x")]):
        result = runner.invoke(workflow.app, ["wait", "run-1", "--poll-min", "0.5"])
    assert result.exit_code == workflow_wait.EXIT_FAILED
    assert runner.invoke(workflow.app, ["wait", "run-1", "--until", "later"]).exit_code == 2


def test_guide_command_prints_a_short_reference_that_names_every_command() -> None:
    result = runner.invoke(workflow.app, ["guide"])
    assert result.exit_code == 0
    lines = result.output.strip().splitlines()
    assert 0 < len(lines) <= 40
    for command in ("create", "wait", "get", "revise", "add-step", "remove-step", "resume", "cancel", "list --mine"):
        assert command in result.output


def test_usage_lines_stay_terse_and_the_guide_is_not_in_the_manifest() -> None:
    from agent_hub_st.__main__ import OWNED_APPS
    from st_sdk.runtime import describe_app

    for spec in describe_app(OWNED_APPS["workflow"], "workflow")["usage"]:
        text = " — ".join([spec["cmd"], spec.get("when", ""), "; ".join(spec.get("precautions", ()))])
        assert len(text) // 4 <= 120, spec["surface"]  # the line cap every ST manifest line must fit


def test_shipped_manifest_matches_the_command_tree() -> None:
    """Regenerate st-extensions/workflow.json (describe_app at COLUMNS=80) whenever a command or its help changes."""
    from agent_hub_st.__main__ import OWNED_APPS
    from st_sdk.runtime import describe_app

    manifest = json.loads((Path(__file__).resolve().parents[3] / "st-extensions/workflow.json").read_text())
    described = describe_app(OWNED_APPS["workflow"], "workflow")
    assert (manifest["id"], manifest["namespace"]) == ("agent-hub.workflow", "workflow")
    assert manifest["help"] == described["help"]
    assert manifest["usage"] == described["usage"]
    assert manifest["help_options"] == described["help_options"]
