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
