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


@pytest.mark.asyncio
async def test_launch_defaults_api_checks_an_explicit_model_and_project() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test", headers={"X-Agent-Hub-Internal": "agent-hub-internal-v1"}) as client:
        pi = await client.get("/api/models/launch-defaults", params={"role": "hunting", "tool": "pi", "model": "anthropic/claude-opus-5-5"})
        tester = await client.get("/api/models/launch-defaults", params={"role": "verification", "tool": "claude-code", "project": "neri-hunters"})
    assert pi.status_code == 200 and pi.json()["rows"][0]["deny_reason"] == HUNT_DENY
    assert tester.status_code == 200 and tester.json()["rows"][0]["allowed"] is False
