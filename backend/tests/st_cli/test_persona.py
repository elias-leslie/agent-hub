"""Tests for st persona CLI helpers."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from agent_hub_st.persona import app
from typer.testing import CliRunner

runner = CliRunner()


class TestPersonaInstructionsCommand:
    def test_instructions_prints_db_backed_text(self) -> None:
        with patch("agent_hub_st.persona._api") as mock_api:
            mock_api.return_value = {"heartbeat_instructions": "DB text"}

            result = runner.invoke(app, ["instructions"])

        assert result.exit_code == 0
        assert "DB text" in result.output

    def test_instructions_exports_db_backed_text(self, tmp_path: Path) -> None:
        target = tmp_path / "heartbeat.md"

        with patch("agent_hub_st.persona._api") as mock_api:
            mock_api.return_value = {"heartbeat_instructions": "DB text"}

            result = runner.invoke(app, ["instructions", "--export", str(target)])

        assert result.exit_code == 0
        assert target.read_text(encoding="utf-8") == "DB text"
        assert f"Heartbeat instructions exported to {target} (7 chars)" in result.output

    def test_instructions_rejects_conflicting_modes(self) -> None:
        result = runner.invoke(app, ["instructions", "--edit", "--export", "heartbeat.md"])

        assert result.exit_code == 1
        assert "--edit, --set, and --export are mutually exclusive" in result.output


class TestPersonaPreviewCommand:
    def test_preview_defaults_to_compact_summary(self) -> None:
        preview = {
            "name": "Jenny",
            "task_type": "chat",
            "sections": [
                {
                    "label": "Persona Context",
                    "source_kind": "persona_context",
                    "source_id": "persona",
                    "estimated_tokens": 2342,
                    "share_of_total": 0.4,
                    "content": "FULL PERSONA CONTEXT",
                }
            ],
            "mandate_count": 1,
            "guardrail_count": 1,
            "full_context": "FULL",
            "prompt_budget": {
                "severity": "danger",
                "total_estimated_tokens": 5853,
                "low_yield_estimated_tokens": 3935,
                "warning_count": 1,
                "warnings": ["Prompt budget danger"],
            },
        }

        with (
            patch("agent_hub_st.persona.agent_preview_api", return_value=preview),
            patch("agent_hub_st.persona._api", side_effect=lambda fn, _: fn()),
        ):
            result = runner.invoke(app, ["preview"])

        assert result.exit_code == 0
        assert "Jenny preview | mode=chat | sections=1 | mandates=1 | guardrails=1" in result.output
        assert "prompt=5853 tok | severity=danger | low_yield=3935 tok | warnings=1" in result.output
        assert "warn: Prompt budget danger" in result.output
        assert "Persona Context" in result.output
        assert "FULL PERSONA CONTEXT" not in result.output
        assert "FULL" not in result.output

    def test_preview_uses_shared_agent_preview_api(self) -> None:
        preview = {
            "name": "Jenny",
            "task_type": "chat",
            "sections": [],
            "mandate_count": 0,
            "guardrail_count": 0,
            "full_context": "FULL",
            "combined_prompt": "COMBINED",
        }

        with (
            patch("agent_hub_st.persona.agent_preview_api", return_value=preview) as mock_preview,
            patch("agent_hub_st.persona._api", side_effect=lambda fn, _: fn()),
        ):
            result = runner.invoke(app, ["preview", "--combined-only"])

        assert result.exit_code == 0
        assert result.output.strip() == "FULL"
        mock_preview.assert_called_once_with(
            "persona",
            task_type="chat",
            project_id=None,
            phase=None,
            prompt_input=None,
        )


class TestPersonaStatusCommand:
    def test_status_reads_only_the_persona_row(self) -> None:
        with patch(
            "agent_hub_st.persona_api.get_persona",
            return_value={"name": "Jenny", "onboarding_phase": "complete"},
        ):
            result = runner.invoke(app, ["status"])

        assert result.exit_code == 0
        assert result.output.strip() == "Persona: Jenny | Onboarding: complete"
