"""Focused owner tests for the root note and mandates callbacks."""

from __future__ import annotations

import hashlib
import json
from unittest.mock import patch

import typer
from agent_hub_st import mandates as mandates_mod
from agent_hub_st import note as note_mod
from st_sdk.context import OutputContext
from typer.testing import CliRunner

runner = CliRunner()
mandates_app = typer.Typer()
mandates_app.command("mandates")(mandates_mod.mandates)
note_app = typer.Typer()
note_app.command("note")(note_mod.note)


def test_mandates_preserves_compact_and_json_contracts(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv(mandates_mod._CONTRACT_ENV, raising=False)
    fake = {
        "status": "ok", "estimated_tokens": 7, "payload_hash": hashlib.sha256(b"x").hexdigest(), "rendered": "x",
        "blocks": [{"block_id": "prompt:a", "kind": "global_guardrail", "title": "A", "estimated_tokens": 7}],
    }
    artifact = tmp_path / "saved.json"
    artifact.write_text(json.dumps(fake), encoding="utf-8")
    monkeypatch.setenv(mandates_mod._CONTRACT_ENV, str(artifact))
    with patch("socket.socket.connect", side_effect=AssertionError("unexpected network")):
        compact = runner.invoke(mandates_app, [], obj=OutputContext(compact=True))
        structured = runner.invoke(mandates_app, [], obj=OutputContext(compact=False))

    assert compact.exit_code == structured.exit_code == 0
    assert "prompt:a global_guardrail tokens=7 A" in compact.stdout
    data = json.loads(structured.stdout)
    assert data["items"] == fake["blocks"]
    assert data["count"] == 1
    assert data["payload_hash"] == fake["payload_hash"]
    assert data["source"] == "saved"


def test_note_saves_a_reference_episode_with_kind_tag() -> None:
    with patch.object(note_mod, "save_impl") as save:
        result = runner.invoke(note_app, ["Check the deploy after merge"])

    assert result.exit_code == 0
    args = save.call_args.args
    assert args[1] == "**Note**: Check the deploy after merge."
    assert args[3] == "reference"
    assert args[16] == "#kind:note"
