"""Agentic automation commands retain revision and API ownership boundaries."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

from agent_hub_st.automations import _api, app

runner = CliRunner()


def test_all_automation_calls_use_verified_internal_transport() -> None:
    with patch("agent_hub_st.automations.agent_hub_request", return_value={}) as request:
        _api("GET", "/api/automations/registry")

    request.assert_called_once_with(
        "GET",
        "/api/automations/registry",
        params=None,
        json=None,
        tool_name="st automations",
        internal=True,
    )


def test_apply_rejects_update_without_revision(tmp_path: Path) -> None:
    path = tmp_path / "profile.json"
    path.write_text(json.dumps({"id": "profile-1", "enabled": False}), encoding="utf-8")

    with patch("agent_hub_st.automations._api") as api:
        result = runner.invoke(app, ["apply", "--file", str(path)])

    assert result.exit_code == 2
    assert "expected_revision" in result.output
    api.assert_not_called()


def test_apply_updates_canonical_api_with_expected_revision(tmp_path: Path) -> None:
    path = tmp_path / "profile.json"
    path.write_text(
        json.dumps({"id": "profile-1", "enabled": False, "expected_revision": 7}),
        encoding="utf-8",
    )

    with patch(
        "agent_hub_st.automations._api",
        return_value={"id": "profile-1", "revision": 8, "enabled": False},
    ) as api:
        result = runner.invoke(app, ["apply", "--file", str(path), "--json"])

    assert result.exit_code == 0
    assert json.loads(result.output)["revision"] == 8
    api.assert_called_once_with(
        "PATCH",
        "/api/automations/profiles/profile-1",
        payload={"enabled": False, "expected_revision": 7},
    )


def test_list_preserves_effective_gate_information() -> None:
    with patch(
        "agent_hub_st.automations._api",
        return_value={
            "items": [
                {
                    "id": "profile-1",
                    "enabled": True,
                    "effective_enabled": False,
                    "gate_reasons": ["project_disabled"],
                }
            ],
            "total": 1,
        },
    ):
        result = runner.invoke(app, ["list", "--json"])

    assert result.exit_code == 0
    item = json.loads(result.output)["items"][0]
    assert item["enabled"] is True
    assert item["effective_enabled"] is False
    assert item["gate_reasons"] == ["project_disabled"]


def test_import_preserves_owner_state_and_legacy_clock(tmp_path: Path) -> None:
    path = tmp_path / "owner.json"
    payload = {
        "project_id": "portfolio-ai",
        "workflow_key": "portfolio-ai/weekly_price_check",
        "source_ref": "portfolio:price_check",
        "schedule_type": "every",
        "schedule_value": "300000",
        "enabled": True,
        "next_run_at": "2026-09-23T15:30:00Z",
        "config": {},
    }
    path.write_text(json.dumps(payload), encoding="utf-8")

    with patch(
        "agent_hub_st.automations._api",
        return_value={"id": "profile-1", "clock_owner": "legacy", "revision": 1},
    ) as api:
        result = runner.invoke(app, ["import", "--file", str(path), "--json"])

    assert result.exit_code == 0
    assert json.loads(result.output)["clock_owner"] == "legacy"
    api.assert_called_once_with("POST", "/api/automations/profiles/import", payload=payload)


def test_cutover_requires_owner_fence_receipt() -> None:
    with patch(
        "agent_hub_st.automations._api",
        return_value={"id": "profile-1", "clock_owner": "central", "revision": 2},
    ) as api:
        result = runner.invoke(
            app,
            ["cutover", "profile-1", "--revision", "1", "--fence-receipt", "owner-fenced"],
        )

    assert result.exit_code == 0
    api.assert_called_once_with(
        "POST",
        "/api/automations/profiles/profile-1/cutover",
        payload={"expected_revision": 1, "fence_receipt": "owner-fenced"},
    )
