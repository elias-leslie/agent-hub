"""Tests for st models CLI."""

from __future__ import annotations

import json
from unittest.mock import patch

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


def test_route_without_task_lists_task_types_and_json_is_the_raw_payload() -> None:
    policy = {"version": 2, "task_types": ["coding", "writing"]}
    with patch("agent_hub_st.models._selection_policy_api", return_value=policy):
        listed = runner.invoke(app, ["route"])
        as_json = runner.invoke(app, ["route", "--json"])
    with patch("agent_hub_st.models._select_api", return_value=_advice()):
        advice_json = runner.invoke(app, ["route", "--task", "coding", "--json"])

    assert listed.output.splitlines() == ["TASK_TYPES[2] policy=v2", "  coding  writing"]
    assert json.loads(as_json.output) == policy
    assert json.loads(advice_json.output)["candidates_checked"][0]["available"] is False


def test_route_posts_only_the_task_type_in_advisory_mode() -> None:
    with patch("agent_hub_st.models.agent_hub_request", return_value=_advice()) as request:
        runner.invoke(app, ["route", "--task", "coding"])

    request.assert_called_once_with(
        "POST", "/api/models/select", json={"task_type": "coding", "mode": "advisory"},
        tool_name="st models route",
    )
