"""The registered owner command prints one bounded export page as JSON."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from agent_hub_st.agents import app
from st_sdk.runtime import describe_app
from typer.testing import CliRunner

runner = CliRunner()


def test_context_export_uses_the_approved_internal_service_helper_and_prints_only_json() -> None:
    payload = {"rows": ['{"slug":"fixture-role"}'], "next_offset": 2}
    with patch("agent_hub_st.memory_api.agent_hub_request", return_value=payload) as request:
        result = runner.invoke(app, ["context-export", "agents", "--offset", "1", "--limit", "1", "--agent-role", "fixture-role", "--agent-role", "other-role"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == payload
    request.assert_called_once_with("GET", "/api/context-export/agents", params={"offset": 1, "limit": 1, "agent_role": ["fixture-role", "other-role"]}, internal=True, tool_name="st agents context-export")


@pytest.mark.parametrize("arguments", [["clients"], ["memories", "--offset", "-1"], ["memories", "--limit", "0"], ["memories", "--limit", "1001"]])
def test_context_export_rejects_bad_collection_or_page_bounds_without_request(arguments: list[str]) -> None:
    with patch("agent_hub_st.memory_api.agent_hub_request") as request:
        result = runner.invoke(app, ["context-export", *arguments])
    assert result.exit_code == 2
    request.assert_not_called()


def test_agents_manifest_registers_export_without_changing_its_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COLUMNS", "80")
    manifest = json.loads((Path(__file__).resolve().parents[3] / "st-extensions/agents.json").read_text())
    described = describe_app(app, "agents")
    assert (manifest["id"], manifest["namespace"], manifest["version"], manifest["st_contract_versions"]) == ("agent-hub.agents", "agents", "0.4.1", [1])
    assert "context-export" in manifest["help"]
    assert any(spec["surface"] == "st.agents.context-export" for spec in manifest["usage"])
    assert manifest["help"] == described["help"]
    assert manifest["usage"] == described["usage"]
    assert manifest["help_options"] == described["help_options"]
