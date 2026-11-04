"""Tests for st models CLI."""

from __future__ import annotations

import json
import time
from unittest.mock import patch

import pytest
from agent_hub_st.models import app
from typer.testing import CliRunner

runner = CliRunner()


def _model(model_id: str, *, provider: str, availability: str = "") -> dict[str, object]:
    return {
        "id": model_id,
        "alias": model_id.rsplit("/", 1)[-1],
        "provider": provider,
        "scores": {"coding": 90, "tool_use": 88, "reasoning": 82},
        "cost": {"input_per_m": 0.3, "output_per_m": 1.2},
        "speed_tier": "fast",
        "capabilities": {"supports_tool_execution": True},
        "availability": availability,
    }


def test_models_lists_compact_catalog_rows() -> None:
    payload = {
        "models": [
            _model("kimi-code/kimi-for-coding", provider="kimi-code", availability="subscription"),
            _model("gemini-3-flash-preview", provider="gemini", availability="free_tier"),
        ]
    }

    with patch("agent_hub_st.models._models_api", return_value=payload):
        result = runner.invoke(app, ["--provider", "gemini", "--free", "--coding"])

    assert result.exit_code == 0
    assert "MODELS[1 shown/1 total]" in result.output
    assert "gemini-3-flash-preview" in result.output
    assert "kimi-code/kimi-for-coding" not in result.output
    assert "$/M in/out" in result.output


def test_models_json_preserves_filtered_payload() -> None:
    payload = {"models": [_model("minimax/MiniMax-M2.7", provider="minimax")], "providers": {"minimax": "MiniMax"}}

    with patch("agent_hub_st.models._models_api", return_value=payload):
        result = runner.invoke(app, ["--id", "minimax/MiniMax-M2.7", "--json"])

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["total"] == 1
    assert data["models"][0]["id"] == "minimax/MiniMax-M2.7"


def _advice(**changes: object) -> dict[str, object]:
    return {
        "task_type": "coding",
        "mode": "advisory",
        "model": "gemini-3.8-flash",
        "effort": "medium",
        "effort_details": {"effective": None, "basis": "Provider or harness mapping not established"},
        "available": True,
        "candidates_checked": [
            {"model": "codex/gpt-6.1-sol", "effort": "medium", "available": False,
             "reasons": ["Model is not active in the catalog", "Provider is cooling down"]},
            {"model": "gemini-3.8-flash", "effort": "medium", "available": True, "reasons": []},
        ],
        "provenance": {"policy_version": 2, "rationale": "Operator starting point."},
        "automatic_eligible": False,
        "automatic_reason": "Current task benchmark and local route qualification are both required.",
        "catalog_health": {"is_stale": None, "last_sync": None},
        **changes,
    }


def test_route_shows_advice_effort_candidate_reasons_and_qualification() -> None:
    with patch("agent_hub_st.models._select_api", return_value=_advice()) as select:
        result = runner.invoke(app, ["route", "--task", "coding"])

    assert result.exit_code == 0
    select.assert_called_once_with("coding")
    lines = result.output.splitlines()
    assert lines[0] == "ROUTE[coding] policy=v2 mode=advisory"
    assert "model=gemini-3.8-flash effort=medium effective=unmapped" in lines[1]
    assert "automatic=not qualified: Current task benchmark" in result.output
    assert "catalog=unknown last_sync=-" in result.output
    assert "CANDIDATES[2 checked]" in result.output
    assert "Model is not active in the catalog; Provider is cooling down" in result.output


def test_route_says_when_no_candidate_is_available_and_when_automatic_qualifies() -> None:
    advice = _advice(available=False, automatic_eligible=True, automatic_reason="Evidence is current.",
                     catalog_health={"is_stale": False, "last_sync": "2026-10-28T06:00:00+00:00"})
    with patch("agent_hub_st.models._select_api", return_value=advice):
        result = runner.invoke(app, ["route", "--task", "coding"])

    assert result.exit_code == 0
    assert "none available; first candidate model=gemini-3.8-flash" in result.output
    assert "automatic=qualified: Evidence is current." in result.output
    assert "catalog=fresh last_sync=2026-10-28" in result.output


def _launch(role: str | None = None, tool: str | None = None) -> dict:
    from app.routing.model_selection import _load_policy, launch_defaults

    return launch_defaults(_load_policy(), role=role, tool=tool)


def test_route_without_task_lists_task_types_and_the_launch_table() -> None:
    policy = {"version": 2, "task_types": ["coding", "writing"]}
    with (patch("agent_hub_st.models._selection_policy_api", return_value=policy),
          patch("agent_hub_st.models._launch_api", return_value=_launch())):
        listed = runner.invoke(app, ["route"])
        as_json = runner.invoke(app, ["route", "--json"])
    with patch("agent_hub_st.models._select_api", return_value=_advice()):
        advice_json = runner.invoke(app, ["route", "--task", "coding", "--json"])

    assert listed.output.splitlines()[:2] == ["TASK_TYPES[2] policy=v2", "  coding  writing"]
    assert "LAUNCH[60 rows]" in listed.output and "claude-haiku-5-5" in listed.output
    # Daybreak reads on, off (a Codex row that turns it off) or - (no Daybreak for that tool).
    daybreak = {tuple(line.split()[:2]): line.split()[4] for line in listed.output.splitlines()
                if line.split()[:2] in (["hunting", "codex"], ["coordinator", "codex"], ["coordinator", "claude-code"])}
    assert daybreak == {("hunting", "codex"): "on", ("coordinator", "codex"): "off",
                        ("coordinator", "claude-code"): "-"}
    assert json.loads(as_json.output)["task_types"] == policy
    assert json.loads(advice_json.output)["candidates_checked"][0]["available"] is False


def test_route_posts_only_the_task_type_in_advisory_mode() -> None:
    with patch("agent_hub_st.models.agent_hub_request", return_value=_advice()) as request:
        runner.invoke(app, ["route", "--task", "coding"])

    request.assert_called_once_with(
        "POST", "/api/models/select", json={"task_type": "coding", "mode": "advisory"},
        tool_name="st models route",
    )


def test_route_role_and_tool_prints_one_launch_row_with_reasons() -> None:
    with patch("agent_hub_st.models._launch_api", return_value=_launch("verification", "claude-code")) as launch:
        result = runner.invoke(app, ["route", "--role", "verification", "--tool", "claude-code"])

    assert result.exit_code == 0
    launch.assert_called_once_with("verification", "claude-code", None, None, facts=True)
    lines = result.output.splitlines()
    assert lines[0].startswith("LAUNCH[verification claude-code] job=testing (Testing)")
    assert lines[1] == "  model=claude-haiku-5-5 effort=high daybreak=- context=blank-slate"
    assert "instead: claude-sonnet-5-5 high when the task truly needs it after the help, prompts or system were fixed" in result.output
    assert "native subagent: user-tester" in result.output and "why=Owner 2026-11-01" in result.output


def test_route_marks_denied_launches_with_the_reason() -> None:
    with patch("agent_hub_st.models._launch_api", return_value=_launch("hunting", "claude-code")):
        result = runner.invoke(app, ["route", "--role", "hunting", "--tool", "claude-code"])
    assert "(not used: no default applies)" in result.output
    assert "DENIED: Owner 2026-11-01: Claude never for active hunting or recon" in result.output


def test_route_passes_an_explicit_model_and_project() -> None:
    with patch("agent_hub_st.models.agent_hub_request", return_value=_launch("hunting", "pi")) as request:
        runner.invoke(app, ["route", "--role", "hunting", "--tool", "pi", "--model", "anthropic/claude-opus-5-5",
                            "--project", "neri-hunters", "--json"])
    request.assert_called_once_with(
        "GET", "/api/models/launch-defaults",
        params={"role": "hunting", "tool": "pi", "model": "anthropic/claude-opus-5-5", "project": "neri-hunters",
                "facts": "1"},
        tool_name="st models route")
    assert runner.invoke(app, ["route", "--model", "claude-opus-5-5"]).exit_code != 0


def test_route_sends_role_and_tool_as_query_and_refuses_task_with_role() -> None:
    with patch("agent_hub_st.models.agent_hub_request", return_value=_launch("hunting", "codex")) as request:
        result = runner.invoke(app, ["route", "--role", "hunting", "--tool", "codex", "--json"])
    request.assert_called_once_with("GET", "/api/models/launch-defaults", params={"role": "hunting", "tool": "codex", "facts": "1"},
                                    tool_name="st models route")
    assert json.loads(result.output)["rows"][0]["daybreak"] is True
    assert runner.invoke(app, ["route", "--task", "coding", "--role", "review"]).exit_code != 0


# ---- options view: st models route --role JOB [--project P] ----------------------------------

def _options(role: str, readings, *, credits=None, refusals=None, project=None, tool=None) -> dict:
    from datetime import UTC, datetime

    from app.models import SubscriptionUsageSnapshot
    from app.routing.launch_facts import Facts, attach
    from app.routing.model_selection import _load_policy, launch_defaults

    policy = _load_policy()
    snaps = [SubscriptionUsageSnapshot(provider=p, window_minutes=m, used_percent=u, source="test",
                                       observed_at=datetime.fromisoformat(o),
                                       resets_at=datetime.fromisoformat(r) if r else None)
             for p, m, u, o, r in readings]
    payload = launch_defaults(policy, role=role, tool=tool, project=project)
    now = datetime(2026, 11, 1, 20, 0, tzinfo=UTC)
    return attach(payload, Facts(readings=snaps, credits=credits or {}, refusals=refusals or []), policy["launch"], now)


READINGS = [
    ("codex", 10080, 100, "2026-11-01T19:31:00+00:00", "2026-11-04T10:28:00+00:00"),
    ("codex", 300, 0, "2026-11-01T19:25:00+00:00", "2026-11-02T00:09:00+00:00"),
    ("opencode-go", 10080, 91, "2026-11-01T19:55:00+00:00", "2026-11-02T00:00:00+00:00"),
    ("opencode-go", 43200, 45, "2026-11-01T19:55:00+00:00", "2026-11-26T20:32:00+00:00"),
    ("claude", 300, 1, "2026-10-31T02:13:00+00:00", "2026-10-31T05:10:00+00:00"),
    ("claude", 10080, 70, "2026-11-01T20:05:00+00:00", "2026-11-06T10:00:00+00:00"),
]
CREDITS = {"codex": {"balance": 12652.0, "pace_per_day_7d": 2803.0, "earliest_expiry": "2026-12-31T23:59:59+00:00"}}
REFUSAL = [{"requested_model": "claude-opus-5-5", "at": "2026-11-01T17:10:11+00:00", "role": "coordinator",
            "project": "neri", "category": "cyber"}]


@pytest.fixture(autouse=True)
def _utc(monkeypatch: pytest.MonkeyPatch):
    """Times print in the caller's zone; the tests read them in UTC."""
    monkeypatch.setenv("TZ", "UTC")
    time.tzset()
    yield
    monkeypatch.undo()
    time.tzset()


def _route_options(role: str, *args: str, **kwargs):
    with patch("agent_hub_st.models._launch_api", return_value=_options(role, READINGS, credits=CREDITS,
                                                                         refusals=REFUSAL, **kwargs)):
        return runner.invoke(app, ["route", "--role", role, *args])


def test_options_view_is_short_and_shows_each_tools_usage_credits_and_reading_age() -> None:
    result = _route_options("research")
    assert result.exit_code == 0
    lines = result.output.splitlines()
    assert 1 < len(lines) <= 15 and lines[0].startswith("OPTIONS[research] policy=v")
    out = result.output
    assert "claude-code  claude-opus-5-5 high  has room" in out and "| also: claude-sonnet-5-5 high" in out
    assert "weekly 30% left, resets" in out and "read " in out and "5h not reported" in out
    assert "codex  gpt-6.1-sol xhigh  running on credits" in out and "weekly used up until" in out
    assert "12.7K credits; at the last-7-day pace they last past the 11-04 reset; the earliest credits expire 12-31" in out
    assert "pi  deepseek-v4.1-flash high" in out.replace("opencode-go/", "") and "monthly 55% left" in out
    assert "antigravity  not launchable" in out
    assert "5h unknown" not in out  # a window missing from the latest reading is not reported, not unknown


def test_options_view_shows_the_last_refusal_and_a_denied_option_only_its_reason() -> None:
    coordinator = _route_options("coordinator", "--project", "neri", project="neri").output
    assert "last refusal 11-01" in coordinator and "(cyber), coordinator/neri" in coordinator
    assert "st aico create --work-role coordinator --project neri --tool T" in coordinator
    hunting = _route_options("hunting").output
    (claude,) = [line for line in hunting.splitlines() if line.startswith("claude-code")]
    assert claude == "claude-code  DENIED: Owner 2026-11-01: Claude never for active hunting or recon"
    assert "last refusal" not in hunting and "claude-opus" not in hunting


def test_options_view_says_unknown_when_a_reset_passed_and_when_facts_could_not_be_read() -> None:
    old = [("claude", 10080, 20, "2026-10-31T02:00:00+00:00", "2026-10-31T05:00:00+00:00")]
    payload = _options("research", old)
    with patch("agent_hub_st.models._launch_api", return_value=payload):
        out = runner.invoke(app, ["route", "--role", "research"]).output
    assert "usage unknown" in out and "weekly unknown (its reset passed; last read 1.8d ago)" in out
    assert "0%" not in out
    payload["facts_error"] = "RuntimeError: down"
    with patch("agent_hub_st.models._launch_api", return_value=payload):
        assert "usage facts unavailable (RuntimeError: down)" in runner.invoke(app, ["route", "--role", "research"]).output


def test_options_json_is_a_superset_of_the_launch_rows_and_tool_keeps_the_single_row_with_facts() -> None:
    plain = _launch("research")
    payload = _options("research", READINGS, credits=CREDITS)
    with patch("agent_hub_st.models._launch_api", return_value=payload):
        data = json.loads(runner.invoke(app, ["route", "--role", "research", "--json"]).output)
    for old_row, row in zip(plain["rows"], data["rows"], strict=True):
        assert {k: v for k, v in old_row.items() if k != "alternates"}.items() <= row.items()
        for old_alt, alt in zip(old_row["alternates"], row["alternates"], strict=True):
            assert old_alt.items() <= alt.items()
        assert {"usage", "last_refusal"} <= set(row)
    assert set(plain) <= set(data)
    one = _options("research", READINGS, credits=CREDITS, tool="claude-code")
    with patch("agent_hub_st.models._launch_api", return_value=one):
        out = runner.invoke(app, ["route", "--role", "research", "--tool", "claude-code"]).output
    assert out.startswith("LAUNCH[research claude-code] job=research") and "  usage: has room" in out
    assert "weekly 30% left, resets" in out


def test_options_view_names_the_unknown_window_beside_one_with_room() -> None:
    readings = [("claude", 300, 10, "2026-11-01T10:00:00+00:00", "2026-11-01T15:00:00+00:00"),
                ("claude", 10080, 30, "2026-11-01T08:00:00+00:00", "2026-11-06T10:00:00+00:00")]
    with patch("agent_hub_st.models._launch_api", return_value=_options("research", readings)):
        out = runner.invoke(app, ["route", "--role", "research"]).output
    assert "claude-code  claude-opus-5-5 high  has room in one window, 5h unknown" in out
    assert "5h unknown (its reset passed" in out


def test_options_view_tags_a_project_default_and_shows_a_when_for_a_fallback_tool() -> None:
    neri = _route_options("implementation", "--project", "neri", project="neri").output
    (claude,) = [line for line in neri.splitlines() if line.startswith("claude-code")]
    assert claude.startswith("claude-code  claude-opus-5-5 high (neri default)  has room")
    assert "also:" not in claude  # Opus is now the default, so it drops out of the alternates
    plain = _route_options("implementation").output
    assert "claude-code  claude-sonnet-5-5 high  has room  | also: claude-opus-5-5 high (when design," in plain
    assert "(neri default)" not in plain
    design = _route_options("design").output
    assert "claude-code  claude-opus-5-5 high  has room  | also: claude-sonnet-5-5 high (when small copy or styling tweaks)" in design
    assert "codex  gpt-6.1-sol xhigh (when Claude is unavailable or out of usage)" in design
    assert "pi  opencode-go/deepseek-v4.1-flash high" in design


def test_pi_alternative_reads_as_when_deepseek_is_unavailable_or_stuck() -> None:
    out = _route_options("implementation").output
    assert "also: opencode-go/glm-5.3 high (when DeepSeek is unavailable or stuck)" in out


def test_dated_model_notes_print_under_the_options_the_models_view_and_the_task_route() -> None:
    note = {"date": "2026-09-04", "fact": "503 on every attempt", "source": "incident"}
    payload = _options("design", READINGS)
    payload["model_notes"] = {"claude-opus-5-5": [note]}
    with patch("agent_hub_st.models._launch_api", return_value=payload):
        out = runner.invoke(app, ["route", "--role", "design"]).output
    assert out.splitlines()[-1] == "NOTE[claude-opus-5-5] 2026-09-04: 503 on every attempt (incident)"
    advice = _advice() | {"model_notes": {"gemini-3.8-flash": [note]}}
    with patch("agent_hub_st.models._select_api", return_value=advice):
        assert "NOTE[gemini-3.8-flash] 2026-09-04" in runner.invoke(app, ["route", "--task", "coding"]).output
    catalog = {"models": [{"id": "gemini-3.8-flash", "provider": "google", "notes": [note]},
                          {"id": "claude-opus-5-5", "provider": "claude", "notes": []}]}
    with patch("agent_hub_st.models._models_api", return_value=catalog):
        listed = runner.invoke(app, ["--id", "gemini-3.8-flash"]).output
    assert "NOTE[gemini-3.8-flash] 2026-09-04: 503 on every attempt (incident)" in listed
    assert "NOTE[claude-opus-5-5]" not in listed
