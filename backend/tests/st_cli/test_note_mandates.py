"""Focused owner tests for the root note and mandates callbacks."""

from __future__ import annotations

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


def test_mandates_preserves_compact_and_json_contracts() -> None:
    fake = {"mandates": {"items": ["**A**: do x.", "**B**: do y."], "count": 2}}
    with patch.object(mandates_mod, "agent_hub_request", return_value=fake):
        compact = runner.invoke(mandates_app, [], obj=OutputContext(compact=True))
        structured = runner.invoke(mandates_app, [], obj=OutputContext(compact=False))

    assert compact.exit_code == structured.exit_code == 0
    assert "**A**: do x." in compact.stdout
    assert json.loads(structured.stdout) == fake["mandates"]


def test_note_saves_a_reference_episode_with_kind_tag() -> None:
    with patch.object(note_mod, "save_impl") as save:
        result = runner.invoke(note_app, ["Check the deploy after merge"])

    assert result.exit_code == 0
    args = save.call_args.args
    assert args[1] == "**Note**: Check the deploy after merge."
    assert args[3] == "reference"
    assert args[16] == "#kind:note"
