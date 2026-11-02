"""The public selector is advisory, capability-aware, and metadata-only."""
from copy import deepcopy
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.routing import model_selection
from app.routing.model_selection import SelectionRequest, select_model


@pytest.mark.asyncio
async def test_advice_shadow_and_override_use_catalog_and_preflight() -> None:
    with patch.object(model_selection, "route_preflight_error", new_callable=AsyncMock, return_value=None):
        result = await select_model(SelectionRequest(task_type="visual_reasoning", mode="shadow", assigned_model="codex-gpt-6.1-sol"))
        assert result["model"] == "codex/gpt-6.1-terra"
        assert result["available"] and not result["apply"] and not result["automatic_eligible"]
        assert result["shadow_comparison"] == {"assigned_model": "codex/gpt-6.1-sol", "same_model": False}
        assert result["provenance"]["benchmark_evidence"] is None
        override = await select_model(SelectionRequest(task_type="coding", override_model="gpt-6.1-terra", override_effort="low"))
        assert override["model"] == "openai/gpt-6.1-terra"
        assert not override["available"] and "tool execution" in str(override["unavailable_reasons"])
        assert override["provenance"]["kind"] == "explicit_override"


@pytest.mark.asyncio
async def test_cooldown_and_inactive_cannot_be_selected() -> None:
    with patch.object(model_selection, "route_preflight_error", new_callable=AsyncMock, return_value=RuntimeError("provider cooldown active")):
        result = await select_model(SelectionRequest(task_type="general"))
        assert not result["available"] and "cooldown" in str(result["unavailable_reasons"])
    missing = await select_model(SelectionRequest(task_type="general", override_model="codex/unknown", override_effort="low"))
    assert not missing["available"] and not missing["apply"]


@pytest.mark.asyncio
async def test_automatic_requires_current_exact_benchmark_qualification(monkeypatch) -> None:
    policy = deepcopy(model_selection._load_policy())
    candidate = policy["policies"]["general"]["candidates"][0]
    evidence = {"source": "https://example.org/evidence", "assessed_at": "2026-01-01",
                "valid_until": "9999-12-31", "model": "codex/gpt-6.1-sol", "effort": "medium", "task_type": "general"}
    candidate["qualification"] = {"benchmark": dict(evidence, kind="task_benchmark")}
    monkeypatch.setattr(model_selection, "_load_policy", lambda: policy)
    with patch.object(model_selection, "route_preflight_error", new_callable=AsyncMock, return_value=None):
        result = await select_model(SelectionRequest(task_type="general", mode="automatic"))
        assert not result["automatic_eligible"] and not result["apply"]
        candidate["qualification"]["local_route"] = dict(evidence, kind="local_route_qualification", effective_effort="medium")
        result = await select_model(SelectionRequest(task_type="general", mode="automatic"))
        assert result["automatic_eligible"] and result["apply"]
        override = await select_model(SelectionRequest(task_type="general", mode="automatic", override_model="codex/gpt-6.1-sol", override_effort="medium"))
        assert not override["apply"]
        candidate["qualification"]["local_route"]["valid_until"] = "2020-01-01"
        assert not (await select_model(SelectionRequest(task_type="general", mode="automatic")))["apply"]



@pytest.mark.asyncio
async def test_api_rejects_content_and_missing_shadow_baseline() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test", headers={"X-Agent-Hub-Internal": "agent-hub-internal-v1"}) as client:
        assert (await client.post("/api/models/select", json={"task_type": "coding", "content": "private task"})).status_code == 422
        assert (await client.post("/api/models/select", json={"task_type": "coding", "mode": "shadow"})).status_code == 422
        assert (await client.post("/api/models/select", json={"task_type": "general", "override_model": "codex/gpt-6.1-sol"})).status_code == 422


@pytest.mark.asyncio
async def test_api_reports_stale_catalog_and_never_applies_unqualified_route() -> None:
    from datetime import UTC, datetime
    from types import SimpleNamespace

    catalog = SimpleNamespace(catalog_health=SimpleNamespace(is_stale=True),
                              last_sync=datetime(2026, 10, 18, tzinfo=UTC), last_model_review=None)
    with (patch("app.api.models.list_models", new_callable=AsyncMock, return_value=catalog),
          patch.object(model_selection, "route_preflight_error", new_callable=AsyncMock, return_value=None)):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test", headers={"X-Agent-Hub-Internal": "agent-hub-internal-v1"}) as client:
            response = await client.post("/api/models/select", json={"task_type": "writing", "mode": "automatic"})
    assert response.status_code == 200
    result = response.json()
    assert result["catalog_health"]["is_stale"] is True
    assert result["available"] and not result["apply"]
    assert result["provenance"]["benchmark_evidence"] is None
    assert "not directly comparable" in result["cost_comparison"]


@pytest.mark.asyncio
async def test_policy_can_add_task_types_without_code_change(monkeypatch) -> None:
    policy = deepcopy(model_selection._load_policy())
    policy["policies"]["coordinator_triage"] = policy["policies"]["general"]
    monkeypatch.setattr(model_selection, "_load_policy", lambda: policy)
    with patch.object(model_selection, "route_preflight_error", new_callable=AsyncMock, return_value=None):
        assert (await select_model(SelectionRequest(task_type="coordinator_triage")))["model"] == "codex/gpt-6.1-sol"
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test", headers={"X-Agent-Hub-Internal": "agent-hub-internal-v1"}) as client:
        assert "coordinator_triage" in (await client.get("/api/models/selection-policy")).json()["task_types"]
        assert (await client.post("/api/models/select", json={"task_type": "unknown"})).status_code == 422


@pytest.mark.asyncio
async def test_external_policy_is_reloaded(monkeypatch, tmp_path) -> None:
    import json

    from app.config import settings
    policy = model_selection._load_policy()
    path = tmp_path / "policy.json"
    path.write_text(json.dumps(policy))
    monkeypatch.setattr(settings, "agent_hub_model_selection_policy_path", str(path))
    assert "new_category" not in (await model_selection.selection_policy())["policies"]
    policy["policies"]["new_category"] = policy["policies"]["general"]
    path.write_text(json.dumps(policy))
    assert "new_category" in (await model_selection.selection_policy())["policies"]


@pytest.mark.asyncio
async def test_fallback_skips_unavailable_routes_but_override_is_a_pin() -> None:
    async def preflight(model):
        return RuntimeError("cooldown") if model.startswith("codex/") else None
    with patch.object(model_selection, "route_preflight_error", side_effect=preflight):
        advice = await select_model(SelectionRequest(task_type="coding"))
        assert advice["available"] and advice["model"] == "gemini-3.8-flash"
        assert len(advice["candidates_checked"]) == 2
        assert "cooldown" in str(advice["candidates_checked"][0]["reasons"])
        pinned = await select_model(SelectionRequest(task_type="coding", override_model="codex/gpt-6.1-sol", override_effort="medium"))
        assert not pinned["available"] and len(pinned["candidates_checked"]) == 1
        assert pinned["model"] == "codex/gpt-6.1-sol"


def test_effort_reports_adapter_mapping_and_unknown_harnesses() -> None:
    from dataclasses import replace

    from app.constants import catalog
    terra = catalog.get_model_entry("codex/gpt-6.1-terra")
    assert terra is not None
    caps = replace(terra.capabilities, thinking_level_map={"medium": "high"})
    catalog.MODEL_CATALOG_BY_ID[terra.id] = replace(terra, capabilities=caps)
    details = model_selection._effort_details(terra.id, "medium")
    assert (details["requested"], details["effective"]) == ("medium", "high")
    assert model_selection._effort_details("gemini-3.8-flash", "medium")["effective"] == "medium"
    assert model_selection._effort_details("claude-sonnet-5-5", "medium")["effective"] is None
    assert "unsupported" in details["max_ultra"]


# ---- launch table: model, effort, Daybreak and context by job and tool ----------------------

def _row(role: str, tool: str, model: str | None = None, project: str | None = None) -> dict:
    (row,) = model_selection.launch_defaults(model_selection._load_policy(), role=role, tool=tool,
                                             model=model, project=project)["rows"]
    return row


def test_every_work_role_launches_as_exactly_one_job_and_every_tool_resolves() -> None:
    from app.services.session_roles import WORK_ROLES

    launch = model_selection._load_policy()["launch"]
    claimed = [role for job in launch["jobs"].values() for role in job["work_roles"]]
    assert sorted(claimed) == sorted(WORK_ROLES)
    for key, job in launch["jobs"].items():
        assert job["context"] in {"full", "blank-slate"}
        for tool in launch["tools"]:
            row = _row(key, tool)
            assert row["why"], (key, tool)
            if row["use"] and row["launchable"] and row["allowed"] and tool != "agent-hub":
                assert row["model"] and row["effort"], (key, tool)


def test_owner_table_rows() -> None:
    assert (_row("verification", "claude-code")["model"], _row("testing", "claude-code")["job"]) == ("claude-haiku-5-5", "testing")
    tester = _row("testing", "claude-code")
    assert (tester["effort"], tester["context"], tester["subagent"]) == ("high", "blank-slate", "user-tester")
    assert [alt["model"] for alt in tester["alternates"]] == ["claude-sonnet-5-5", "claude-opus-5-5"]
    assert (_row("implementation", "claude-code")["model"], _row("implementation", "claude-code")["effort"]) == ("claude-sonnet-5-5", "high")
    assert (_row("coordinator", "claude-code")["model"], _row("coordinator", "claude-code")["effort"]) == ("claude-opus-5-5", "xhigh")
    review = _row("review", "claude-code")
    assert (review["model"], review["effort"], review["subagent"], review["context"]) == ("claude-opus-5-5", "high", "code-reviewer", "blank-slate")
    assert (_row("review", "codex")["model"], _row("review", "codex")["use"]) == ("gpt-6.1-sol", True)
    hunter = _row("hunting", "codex")
    assert (hunter["model"], hunter["effort"], hunter["daybreak"]) == ("gpt-6-sol", "xhigh", True)
    builder = _row("implementation", "codex")
    assert (builder["model"], builder["effort"], builder["daybreak"]) == ("gpt-6.1-sol", "xhigh", False)
    pi = _row("hunting", "pi")
    assert (pi["model"], pi["effort"], pi["allowed"]) == ("opencode-go/deepseek-v4.1-flash", "high", True)
    assert [alt["model"] for alt in pi["alternates"]] == ["opencode-go/glm-5.3", "opencode-go/glm-5.3-flash"]
    assert "last choice" in _row("implementation", "pi")["note"] and "rank" not in pi and "prefer" not in pi
    assert _row("lookup", "claude-code")["model"] == "claude-haiku-5-5" and _row("lookup", "claude-code")["work_roles"] == []
    assert not _row("other", "antigravity")["launchable"] and _row("other", "agent-hub")["model"] is None


def test_launch_table_names_the_registered_work_role_and_refuses_unknown_keys() -> None:
    policy = model_selection._load_policy()
    assert model_selection.launch_defaults(policy, role="verification")["work_role"] == "verification"
    assert model_selection.launch_defaults(policy, role="testing")["work_role"] is None
    assert len(model_selection.launch_defaults(policy)["rows"]) == len(policy["launch"]["jobs"]) * len(policy["launch"]["tools"])
    with pytest.raises(model_selection.UnknownLaunchKey, match="tester"):
        model_selection.launch_defaults(policy, role="tester")
    with pytest.raises(model_selection.UnknownLaunchKey, match="cursor"):
        model_selection.launch_defaults(policy, tool="cursor")


@pytest.mark.asyncio
async def test_launch_defaults_api() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test", headers={"X-Agent-Hub-Internal": "agent-hub-internal-v1"}) as client:
        one = await client.get("/api/models/launch-defaults", params={"role": "research", "tool": "claude-code"})
        typo = await client.get("/api/models/launch-defaults", params={"role": "tester"})
    assert one.status_code == 200 and one.json()["rows"][0]["model"] == "claude-opus-5-5"
    assert typo.status_code == 422 and "tester" in typo.text and "verification" in typo.text


# ---- launch deny rows: hard rules checked for every tool and an explicit model ----------------

HUNT_DENY = "Owner 2026-11-01: Claude never for active hunting or recon"


@pytest.mark.parametrize(("role", "tool", "model"), [
    ("hunting", "claude-code", None),
    ("hunting", "claude-code", "gpt-6-sol"),  # Claude Code always runs Claude
    ("recon", "claude-code", None),
    ("hunting", "pi", "anthropic/claude-opus-5-5"),  # not in the catalog: the id names Claude
    ("hunting", "agent-hub", "claude-opus-5-5"),
    ("hunting", "codex", "claude-sonnet-5-5"),
    ("recon", "antigravity", "claude-opus-4-8"),
    ("hunting", "pi", "openrouter/opus-7"),
])
def test_deny_covers_every_tool_and_an_explicit_model(role: str, tool: str, model: str | None) -> None:
    row = _row(role, tool, model=model)
    assert (row["allowed"], row["deny_reason"], row["use"]) == (False, HUNT_DENY, False)
    assert row["why"] == HUNT_DENY  # a denied row's why is the deny reason, never a contradicting table note


def test_hunting_rows_without_claude_and_unknown_non_claude_ids_stay_allowed() -> None:
    for tool, model in [("codex", None), ("pi", None), ("pi", "opencode-go/some-new-hunter-9"),
                        ("agent-hub", None), ("codex", "gpt-7-unlisted")]:
        row = _row("hunting", tool, model=model)
        assert (row["allowed"], row["deny_reason"]) == (True, None), (tool, model)
    assert _row("hunting", "codex")["model"] == "gpt-6-sol"  # today's fields are unchanged
    assert _row("research", "claude-code", model="claude-opus-5-5", project="neri-hunters")["allowed"] is True


def test_verification_is_denied_on_claude_only_in_neri_hunters() -> None:
    denied = _row("verification", "claude-code", project="neri-hunters")
    assert (denied["allowed"], denied["deny_reason"]) == (False, "Owner 2026-11-01: Claude never for full case/hunt review")
    assert _row("verification", "pi", model="anthropic/claude-haiku-5-5", project="neri-hunters")["allowed"] is False
    assert _row("verification", "codex", project="neri-hunters")["allowed"] is True
    for project in (None, "neri", "summitflow"):
        row = _row("verification", "claude-code", project=project)
        assert (row["allowed"], row["model"], row["use"]) == (True, "claude-haiku-5-5", True), project


def test_shipped_launch_policy_is_consistent_and_refuses_a_tools_row_a_deny_row_contradicts() -> None:
    from app.routing.launch_policy import launch_policy_problems

    policy = model_selection._load_policy()
    assert launch_policy_problems(policy) == []
    bad = deepcopy(policy)
    bad["launch"]["jobs"]["hunting"]["tools"]["claude-code"] = {"model": "claude-opus-5-5", "effort": "high", "why": "x"}
    bad["launch"]["jobs"]["recon"]["tools"]["pi"]["alternates"] = [{"model": "anthropic/claude-sonnet-5-5", "effort": "high"}]
    bad["launch"]["jobs"]["review"]["tools"]["codex"] = {"model": None, "use": False, "why": "x"}
    problems = launch_policy_problems(bad)
    assert any("hunting.tools.claude-code" in p and "contradicts" in p for p in problems)
    assert any("recon.tools.pi" in p and "contradicts" in p for p in problems)
    assert any("'use' is retired" in p for p in problems)
    # A deny scoped to one project leaves the job's Claude row valid elsewhere.
    assert not any("testing.tools.claude-code" in p for p in problems)


def test_a_project_default_replaces_the_row_for_that_project_only_and_drops_the_matching_alternate() -> None:
    plain = _row("implementation", "claude-code")
    assert (plain["model"], plain["effort"], plain["project_default"]) == ("claude-sonnet-5-5", "high", None)
    assert [alt["model"] for alt in plain["alternates"]] == ["claude-opus-5-5"]
    neri = _row("implementation", "claude-code", project="neri")
    assert (neri["model"], neri["effort"], neri["project_default"]) == ("claude-opus-5-5", "high", "neri")
    assert neri["alternates"] == [] and neri["why"].startswith("Owner 2026-10-31") and neri["allowed"] is True
    assert "projects" not in neri
    other = _row("implementation", "claude-code", project="summitflow")
    assert (other["model"], other["project_default"]) == ("claude-sonnet-5-5", None)
    assert _row("implementation", "codex", project="neri")["project_default"] is None


def test_project_default_that_differs_from_every_alternate_keeps_them() -> None:
    policy = deepcopy(model_selection._load_policy())
    policy["launch"]["jobs"]["implementation"]["tools"]["claude-code"]["projects"]["neri"]["model"] = "claude-haiku-5-5"
    (row,) = model_selection.launch_defaults(policy, role="implementation", tool="claude-code", project="neri")["rows"]
    assert (row["model"], [alt["model"] for alt in row["alternates"]]) == ("claude-haiku-5-5", ["claude-opus-5-5"])


def test_project_defaults_are_validated_against_projects_and_deny_rows() -> None:
    from app.routing.launch_policy import launch_policy_problems

    policy = model_selection._load_policy()
    assert launch_policy_problems(policy, known_projects={"neri", "summitflow"}) == []
    assert any("unknown project 'neri'" in p for p in launch_policy_problems(policy, known_projects={"summitflow"}))
    bad = deepcopy(policy)
    jobs = bad["launch"]["jobs"]
    jobs["implementation"]["tools"]["claude-code"]["projects"]["bad key"] = {"model": "claude-opus-5-5", "effort": "high", "why": "x"}
    jobs["implementation"]["tools"]["claude-code"]["projects"]["neri"] = {"model": "claude-opus-5-5", "effort": "high"}
    jobs["implementation"]["tools"]["claude-code"]["projects"]["extra"] = {"model": "m", "effort": "high", "why": "x", "use": True}
    # A deny row scoped to one project still refuses a default set for that project.
    jobs["testing"]["tools"]["claude-code"]["projects"] = {
        "neri-hunters": {"model": "claude-haiku-5-5", "effort": "high", "why": "x"}}
    problems = launch_policy_problems(bad)
    assert any("'bad key' is not a project id" in p for p in problems)
    assert any("projects.neri: model, effort and why are required" in p for p in problems)
    assert any("projects.extra: unknown keys ['use']" in p for p in problems)
    assert any("testing.tools.claude-code.projects.neri-hunters" in p and "contradicts deny row" in p for p in problems)


def test_design_is_a_registered_work_role_with_owners_three_routes() -> None:
    from app.services.session_roles import WORK_ROLES

    assert "design" in WORK_ROLES
    claude = _row("design", "claude-code")
    assert (claude["job"], claude["model"], claude["effort"], claude["context"]) == ("design", "claude-opus-5-5", "high", "full")
    assert [(alt["model"], alt["effort"], alt["when"]) for alt in claude["alternates"]] == [
        ("claude-sonnet-5-5", "high", "small copy or styling tweaks")]
    codex = _row("design", "codex")
    assert (codex["model"], codex["effort"], codex["daybreak"], codex["when"]) == (
        "gpt-6.1-sol", "xhigh", False, "Claude is unavailable or out of usage")
    assert codex["why"].startswith("when Claude is unavailable or out of usage")
    assert _row("design", "pi")["model"] == "opencode-go/deepseek-v4.1-flash"
    assert model_selection.launch_defaults(model_selection._load_policy(), role="design")["work_role"] == "design"
    assert _row("implementation", "claude-code")["when"] is None


def test_model_notes_are_shown_for_models_in_the_rows_and_validated() -> None:
    from app.routing.launch_policy import launch_policy_problems, model_notes

    policy = model_selection._load_policy()
    assert {note["date"] for note in model_notes(policy, "gemini-3.7-flash")} == {"2026-09-04", "2026-09-20"}
    assert model_notes(policy, "claude-opus-5-5") == [] and model_notes(policy, None) == []
    payload = model_selection.launch_defaults(policy, role="research")
    assert payload["model_notes"] == {}
    bad = deepcopy(policy)
    bad["launch"]["jobs"]["research"]["tools"]["claude-code"]["model"] = "gemini-3.8-flash"
    shown = model_selection.launch_defaults(bad, role="research", tool="claude-code")["model_notes"]
    assert list(shown) == ["gemini-3.8-flash"] and len(shown["gemini-3.8-flash"]) == 2
    bad["model_notes"]["gemini-3.8-flash"] = [{"date": "yesterday", "fact": "", "source": "s"}, {"date": "2026-09-04"}]
    bad["model_notes"]["empty"] = []
    problems = launch_policy_problems(bad)
    assert any("date must be YYYY-MM-DD" in p for p in problems) and any("fact and source are required" in p for p in problems)
    assert any("exactly date, fact and source" in p for p in problems) and any("'empty'" in p for p in problems)


@pytest.mark.asyncio
async def test_models_list_carries_policy_notes_and_the_task_route_names_them() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test", headers={"X-Agent-Hub-Internal": "agent-hub-internal-v1"}) as client:
        listed = (await client.get("/api/models")).json()["models"]
    notes = {m["id"]: m["notes"] for m in listed if m.get("notes")}
    assert notes and all({"date", "fact", "source"} == set(n) for items in notes.values() for n in items)
    assert set(notes) <= {"gemini-3.1-flash-lite", "gemini-3.7-flash", "gemini-3.8-flash"}
    with patch("app.routing.model_selection._unavailable", AsyncMock(return_value=[])):
        advice = await select_model(SelectionRequest(task_type="coding"))
    assert advice["model"].endswith("gpt-6.1-sol") and advice["model_notes"] == {}  # the first candidate has no notes
    with patch("app.routing.model_selection._unavailable", AsyncMock(side_effect=[["down"], []])):
        advice = await select_model(SelectionRequest(task_type="coding"))
    assert list(advice["model_notes"]) == ["gemini-3.8-flash"]


@pytest.mark.asyncio
async def test_launch_defaults_api_checks_an_explicit_model_and_project() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test", headers={"X-Agent-Hub-Internal": "agent-hub-internal-v1"}) as client:
        pi = await client.get("/api/models/launch-defaults", params={"role": "hunting", "tool": "pi", "model": "anthropic/claude-opus-5-5"})
        tester = await client.get("/api/models/launch-defaults", params={"role": "verification", "tool": "claude-code", "project": "neri-hunters"})
    assert pi.status_code == 200 and pi.json()["rows"][0]["deny_reason"] == HUNT_DENY
    assert tester.status_code == 200 and tester.json()["rows"][0]["allowed"] is False


# ---- usage facts per option: windows, reading age, credits, last refusal ---------------------

def _facts_payload(role: str, readings, *, credits=None, refusals=None, project=None, tool=None) -> dict:
    from datetime import UTC, datetime

    from app.routing.launch_facts import Facts, attach

    policy = model_selection._load_policy()
    payload = model_selection.launch_defaults(policy, role=role, tool=tool, project=project)
    now = datetime(2026, 11, 1, 20, 0, tzinfo=UTC)
    return attach(payload, Facts(readings=readings, credits=credits or {}, refusals=refusals or []), policy["launch"], now)


def _reading(provider: str, minutes: int, used: float, *, observed: str, resets: str | None):
    from datetime import datetime

    from app.models import SubscriptionUsageSnapshot

    return SubscriptionUsageSnapshot(provider=provider, window_minutes=minutes, used_percent=used,
                                     observed_at=datetime.fromisoformat(observed),
                                     resets_at=datetime.fromisoformat(resets) if resets else None, source="test")


def _usage(payload: dict, tool: str) -> dict:
    return next(row for row in payload["rows"] if row["tool"] == tool)["usage"]


def test_a_reading_whose_reset_passed_is_unknown_not_zero_percent_used() -> None:
    old = _reading("claude", 300, 40, observed="2026-10-31T02:00:00+00:00", resets="2026-10-31T05:00:00+00:00")
    usage = _usage(_facts_payload("research", [old]), "claude-code")
    (window,) = usage["windows"]
    assert usage["status"] == "unknown"
    assert window["state"] == "unknown" and window["left_percent"] is None and window["used_percent"] is None
    assert window["resets_at"] is None and window["age_seconds"] == 42 * 3600


def test_a_window_missing_from_the_latest_reading_is_not_reported_and_does_not_make_the_option_unknown() -> None:
    five = _reading("claude", 300, 1, observed="2026-10-31T02:00:00+00:00", resets="2026-10-31T05:00:00+00:00")
    week = _reading("claude", 10080, 70, observed="2026-11-01T19:55:00+00:00", resets="2026-11-06T10:00:00+00:00")
    usage = _usage(_facts_payload("research", [five, week]), "claude-code")
    states = {w["label"]: w["state"] for w in usage["windows"]}
    assert states == {"5h": "not_reported", "weekly": "ok"}
    assert usage["status"] == "ok"
    weekly = usage["windows"][1]
    assert weekly["left_percent"] == 30 and weekly["age_seconds"] == 5 * 60 and weekly["resets_in_seconds"] == 4 * 86400 + 14 * 3600


def test_an_old_reading_is_shown_with_its_age_while_its_reset_is_ahead() -> None:
    week = _reading("claude", 10080, 20, observed="2026-10-30T20:00:00+00:00", resets="2026-11-06T10:00:00+00:00")
    usage = _usage(_facts_payload("research", [week]), "claude-code")
    assert usage["status"] == "ok" and usage["windows"][0]["age_seconds"] == 48 * 3600


def test_a_window_at_100_percent_is_used_up_until_it_resets() -> None:
    week = _reading("claude", 10080, 100, observed="2026-11-01T19:55:00+00:00", resets="2026-11-06T10:00:00+00:00")
    usage = _usage(_facts_payload("research", [week]), "claude-code")
    assert usage["status"] == "used_up" and usage["windows"][0]["state"] == "used_up"
    assert usage["windows"][0]["left_percent"] == 0 and usage["windows"][0]["resets_at"].startswith("2026-11-06T10:00")


def test_codex_week_at_100_percent_with_a_balance_runs_on_credits_and_says_how_long_they_last() -> None:
    week = _reading("codex", 10080, 100, observed="2026-11-01T19:31:00+00:00", resets="2026-11-04T10:28:00+00:00")
    five = _reading("codex", 300, 0, observed="2026-11-01T19:25:00+00:00", resets="2026-11-02T00:09:00+00:00")
    credits = {"codex": {"balance": 12652.0, "pace_per_day_7d": 2803.0, "earliest_expiry": "2026-12-31T23:59:59+00:00"}}
    usage = _usage(_facts_payload("coordinator", [week, five], credits=credits), "codex")
    assert usage["status"] == "on_credits"
    assert usage["credits"]["lasts_past_reset"] is True and usage["credits"]["reset_at"].startswith("2026-11-04T10:28")
    assert usage["credits"]["earliest_expiry"].startswith("2026-12-31") and usage["credits"]["lasts_days"] == 4.5
    # Same week at 100% with a fast pace: the credits do not reach the reset.
    fast = {"codex": credits["codex"] | {"pace_per_day_7d": 9000.0}}
    assert _usage(_facts_payload("coordinator", [week, five], credits=fast), "codex")["credits"]["lasts_past_reset"] is False
    # Week at 100% and no balance: used up, not credits.
    empty = {"codex": credits["codex"] | {"balance": 0.0}}
    assert _usage(_facts_payload("coordinator", [week, five], credits=empty), "codex")["status"] == "used_up"


def test_pi_usage_follows_the_provider_named_in_the_model_and_untracked_tools_say_so() -> None:
    month = _reading("opencode-go", 43200, 45, observed="2026-11-01T19:55:00+00:00", resets="2026-11-26T20:32:00+00:00")
    payload = _facts_payload("hunting", [month])
    assert _usage(payload, "pi")["provider"] == "opencode-go" and _usage(payload, "pi")["status"] == "ok"
    assert _usage(payload, "antigravity")["status"] == "untracked" and _usage(payload, "agent-hub")["status"] == "untracked"


def test_last_refusal_is_keyed_on_the_requested_model_and_never_changes_allowed() -> None:
    refusals = [
        {"requested_model": "claude-opus-5-5", "at": "2026-11-01T17:10:11+00:00", "role": "coordinator", "project": "neri", "category": "cyber"},
        {"requested_model": "claude-opus-5-5", "at": "2026-11-01T04:30:10+00:00", "role": None, "project": "neri", "category": "cyber"},
        {"requested_model": "claude-sonnet-5-5", "at": "2026-10-30T01:00:00+00:00", "role": None, "project": None, "category": "cyber"},
    ]
    payload = _facts_payload("coordinator", [], refusals=refusals, project="neri", tool="claude-code")
    (row,) = payload["rows"]
    assert row["allowed"] is True and row["use"] is True
    assert row["last_refusal"] == refusals[0] | {"count": 2}
    # Not the model the row launches: no refusal shown.
    sonnet = _facts_payload("implementation", [], refusals=refusals[:2], tool="claude-code")["rows"][0]
    assert sonnet["last_refusal"] is None
    assert sonnet["alternates"][0]["last_refusal"]["count"] == 2  # its Opus alternate


def test_a_denied_option_keeps_its_deny_reason_and_shows_no_refusal_line() -> None:
    refusals = [{"requested_model": "claude-opus-5-5", "at": "2026-11-01T17:10:11+00:00", "role": None, "project": None, "category": "cyber"}]
    payload = _facts_payload("hunting", [], refusals=refusals)
    claude = next(row for row in payload["rows"] if row["tool"] == "claude-code")
    assert claude["allowed"] is False and "never for active hunting" in claude["deny_reason"]
    assert claude["last_refusal"] is None


@pytest.mark.asyncio
async def test_launch_defaults_api_carries_facts_and_survives_unreadable_usage_tables() -> None:
    from app.routing import launch_facts

    async def broken(db):
        raise RuntimeError("usage tables unreadable")

    headers = {"X-Agent-Hub-Internal": "agent-hub-internal-v1"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test", headers=headers) as client:
        with patch.object(launch_facts, "load_facts", new=AsyncMock(return_value=launch_facts.Facts())):
            ok = await client.get("/api/models/launch-defaults", params={"role": "research", "facts": 1})
        with patch.object(launch_facts, "load_facts", new=broken):
            down = await client.get("/api/models/launch-defaults", params={"role": "research", "facts": 1})
    assert ok.status_code == 200 and all("usage" in row and "last_refusal" in row for row in ok.json()["rows"])
    assert ok.json()["rows"][0]["model"] == "claude-opus-5-5"  # existing fields kept
    assert down.status_code == 200 and "unreadable" in down.json()["facts_error"] and down.json()["rows"][0]["allowed"] is True


@pytest.mark.asyncio
async def test_launch_defaults_reads_no_usage_facts_unless_asked() -> None:
    """st aico create and the host shim call this on every start; they need allowed and the table, not the usage tables."""
    from app.routing import launch_facts

    load = AsyncMock(return_value=launch_facts.Facts())
    headers = {"X-Agent-Hub-Internal": "agent-hub-internal-v1"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test", headers=headers) as client:
        with patch.object(launch_facts, "load_facts", new=load):
            plain = await client.get("/api/models/launch-defaults", params={"role": "hunting", "tool": "claude-code"})
    load.assert_not_awaited()
    row = plain.json()["rows"][0]
    assert plain.status_code == 200 and row["allowed"] is False and row["deny_reason"] == HUNT_DENY
    assert {"model", "effort", "daybreak", "context", "launchable"} <= set(row)  # the table defaults stay in the answer
    assert "usage" not in row and "last_refusal" not in row and "facts_as_of" not in plain.json()


def test_a_window_with_room_beside_an_unknown_one_is_partly_unknown_never_plain_room() -> None:
    # The 5h reading's reset passed and the provider has not read it since; the week still has room.
    five = _reading("claude", 300, 10, observed="2026-11-01T10:00:00+00:00", resets="2026-11-01T15:00:00+00:00")
    week = _reading("claude", 10080, 30, observed="2026-11-01T08:00:00+00:00", resets="2026-11-06T10:00:00+00:00")
    usage = _usage(_facts_payload("research", [five, week]), "claude-code")
    assert {w["label"]: w["state"] for w in usage["windows"]} == {"5h": "unknown", "weekly": "ok"}
    assert usage["status"] == "partly_unknown" and usage["unknown_windows"] == ["5h"]
    assert _usage(_facts_payload("research", [week]), "claude-code")["status"] == "ok"


def test_an_empty_credit_balance_never_lasts_past_the_reset() -> None:
    week = _reading("codex", 10080, 100, observed="2026-11-01T19:31:00+00:00", resets="2026-11-04T10:28:00+00:00")
    for pace in (0.0, 2803.0):
        empty = {"codex": {"balance": 0.0, "pace_per_day_7d": pace, "earliest_expiry": None}}
        credits = _usage(_facts_payload("coordinator", [week], credits=empty), "codex")["credits"]
        assert credits["lasts_past_reset"] is False and credits["lasts_days"] == 0.0
    # Credits with no draw in the last 7 days still last past the reset.
    idle = {"codex": {"balance": 500.0, "pace_per_day_7d": 0.0, "earliest_expiry": None}}
    assert _usage(_facts_payload("coordinator", [week], credits=idle), "codex")["credits"]["lasts_past_reset"] is True
