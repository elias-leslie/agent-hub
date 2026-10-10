"""`st mandates` reports the canonical startup delivery and injected-hash drift."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import typer
from typer.testing import CliRunner

from agent_hub_st import mandates as module

DELIVERY = {
    "status": "ok",
    "estimated_tokens": 12,
    "payload_hash": "abc123",
    "rendered": "## Safety\nbody\n",
    "blocks": [{"block_id": "prompt:safety", "kind": "global_guardrail", "title": "Safety", "estimated_tokens": 12}],
}


def _invoke(monkeypatch: pytest.MonkeyPatch, *args: str) -> tuple[str, list[dict[str, Any]]]:
    calls: list[dict[str, Any]] = []

    def fake_request(method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        calls.append({"method": method, "path": path, **kwargs})
        return DELIVERY

    monkeypatch.setattr(module, "agent_hub_request", fake_request)
    app = typer.Typer()
    app.command()(module.mandates)
    result = CliRunner().invoke(app, list(args))
    assert result.exit_code == 0, result.output
    return result.output, calls


def test_replays_injected_contract_and_reports_match(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    contract = tmp_path / "contract.json"
    contract.write_text(json.dumps({"payload_hash": "abc123", "metadata": {
        "consumer_surface": "codex", "cwd": "/repo", "query_hash": "derived", "task": None, "capabilities": ["bash"],
    }}))
    monkeypatch.setenv(module._CONTRACT_ENV, str(contract))

    output, calls = _invoke(monkeypatch)

    assert calls[0]["path"] == module._DELIVER_PATH and calls[0]["internal"] is True
    assert calls[0]["json"] == {"consumer_surface": "codex", "cwd": "/repo", "capabilities": ["bash"]}
    assert "prompt:safety global_guardrail tokens=12 Safety" in output
    assert output.rstrip().endswith("|injected=match")


def test_without_contract_detects_surface_and_prints_full_text(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(module._CONTRACT_ENV, raising=False)
    monkeypatch.delenv("CLAUDECODE", raising=False)
    monkeypatch.setenv("CODEX_THREAD_ID", "thread")

    output, calls = _invoke(monkeypatch, "--full")

    assert calls[0]["json"]["consumer_surface"] == "codex"
    assert output == DELIVERY["rendered"]


def test_compact_output_prints_bloat_warning_only_when_over_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(module._CONTRACT_ENV, raising=False)
    assert "CONTEXT_WARN" not in _invoke(monkeypatch)[0]
    big = {**DELIVERY, "estimated_tokens": 9_000}

    def fake_request(method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        return big

    monkeypatch.setattr(module, "agent_hub_request", fake_request)
    app = typer.Typer()
    app.command()(module.mandates)
    output = CliRunner().invoke(app, []).output
    assert output.rstrip().endswith("CONTEXT_WARN:total=9000tok>budget=3000")
