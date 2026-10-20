"""Saved startup inspection never requests a new delivery or credentials."""
from __future__ import annotations

import hashlib
import json

import pytest
import typer
from st_sdk.context import OutputContext
from typer.testing import CliRunner

from agent_hub_st import mandates as module

TEXT = "## Safety\r\nCafé 🏔\nbody\n\n"
DELIVERY = {
    "status": "ok", "estimated_tokens": 12,
    "payload_hash": hashlib.sha256(TEXT.encode("utf-8")).hexdigest(),
    "rendered": TEXT,
    "blocks": [{"block_id": "prompt:safety", "kind": "global_guardrail", "title": "Safety", "estimated_tokens": 12}],
    "metadata": {"project_id": "summitflow", "cwd": "/original/repo", "consumer_surface": "codex"},
}
app = typer.Typer()
app.command()(module.mandates)


@pytest.fixture(autouse=True)
def no_remote_access(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("saved inspection attempted network or credential access")
    monkeypatch.setattr("agent_hub_st.memory_api.agent_hub_request", forbidden)
    monkeypatch.setattr("socket.socket.connect", forbidden)
    monkeypatch.delenv("INTERNAL_SERVICE_SECRET", raising=False)
    monkeypatch.delenv(module._CONTRACT_ENV, raising=False)


def save(monkeypatch, tmp_path, delivery):
    path = tmp_path / "launch.json"
    path.write_text(json.dumps(delivery), encoding="utf-8")
    monkeypatch.setenv(module._CONTRACT_ENV, str(path))


def test_saved_compact_json_and_exact_full_text(monkeypatch, tmp_path):
    save(monkeypatch, tmp_path, DELIVERY)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    compact = CliRunner().invoke(app, [])
    assert compact.exit_code == 0, compact.output
    assert "prompt:safety global_guardrail tokens=12 Safety" in compact.output
    assert "|source=saved|scope=summitflow|" in compact.output
    assert "injected=" not in compact.output
    structured = CliRunner().invoke(app, [], obj=OutputContext(compact=False))
    assert structured.exit_code == 0, structured.output
    data = json.loads(structured.stdout)
    assert data["source"] == "saved"
    assert data["items"] == DELIVERY["blocks"] and data["count"] == 1
    assert data["payload_hash"] == DELIVERY["payload_hash"]
    assert data["rendered_bytes"] == len(TEXT.encode("utf-8"))
    full = CliRunner().invoke(app, ["--full"])
    assert full.exit_code == 0
    # CliRunner's text view normalizes CRLF; its bytes retain the exact payload.
    assert full.stdout_bytes == TEXT.encode("utf-8")


@pytest.mark.parametrize("patch", [
    {"rendered": "changed"}, {"payload_hash": "wrong"}, {"payload_hash_algorithm": "sha1"},
    {"rendered": None}, {"rendered": ""}, {"blocks": None}, {"blocks": [None]},
    {"metadata": []}, {"status": {}}, {"estimated_tokens": "12"},
    {"blocks": [{**DELIVERY["blocks"][0], "estimated_tokens": "bad"}]},
    {"blocks": [{**DELIVERY["blocks"][0], "kind": []}]},
])
def test_invalid_artifact_errors_without_inference_about_receipt(monkeypatch, tmp_path, patch):
    save(monkeypatch, tmp_path, {**DELIVERY, **patch})
    result = CliRunner().invoke(app, ["--full"])
    assert result.exit_code == 1, result.output
    assert "Saved startup artifact unavailable or invalid" in result.output
    assert "does not establish what instructions the model received" in result.output


@pytest.mark.parametrize("contents", ["{", "null", "[]", "{}", b"\xff"])
def test_malformed_artifact(monkeypatch, tmp_path, contents):
    path = tmp_path / "bad.json"
    path.write_bytes(contents if isinstance(contents, bytes) else contents.encode())
    monkeypatch.setenv(module._CONTRACT_ENV, str(path))
    result = CliRunner().invoke(app, [])
    assert result.exit_code == 1
    assert "Saved startup artifact unavailable or invalid" in result.output


def test_unset_and_missing_artifact(monkeypatch, tmp_path):
    for path in (None, str(tmp_path / "missing.json")):
        if path:
            monkeypatch.setenv(module._CONTRACT_ENV, path)
        result = CliRunner().invoke(app, [])
        assert result.exit_code == 1
        assert "does not establish what instructions the model received" in result.output


def test_saved_warnings_and_removed_surface_option(monkeypatch, tmp_path):
    save(monkeypatch, tmp_path, {**DELIVERY, "estimated_tokens": 9000})
    result = CliRunner().invoke(app, [])
    assert result.exit_code == 0
    assert "CONTEXT_WARN:total=9000tok>budget=3000 scope=summitflow" in result.output
    assert CliRunner().invoke(app, ["--surface", "codex"]).exit_code == 2
