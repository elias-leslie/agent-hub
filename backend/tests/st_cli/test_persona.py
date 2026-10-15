"""Tests for st persona CLI helpers."""

from __future__ import annotations

from unittest.mock import patch

from agent_hub_st.persona import app
from typer.testing import CliRunner

runner = CliRunner()


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


class TestPersonaUpdateProfile:
    def test_profile_field_merges_into_current_profile(self) -> None:
        current = {"user_profile": {"timezone": "America/New_York", "communication_style": "old"}}
        saved = {"version": 7, "user_profile": {"timezone": "America/New_York", "communication_style": "Plain prose."}}
        with (
            patch("agent_hub_st.persona_api.get_persona", return_value=current),
            patch("agent_hub_st.persona_api.update_persona", return_value=saved) as update,
        ):
            result = runner.invoke(app, ["update", "--profile", "communication_style=Plain prose."])

        assert result.exit_code == 0, result.output
        update.assert_called_once_with(
            {"user_profile": {"timezone": "America/New_York", "communication_style": "Plain prose."}}
        )
        assert "user_profile.communication_style: Plain prose." in result.output

    def test_unknown_profile_field_fails(self) -> None:
        with (
            patch("agent_hub_st.persona_api.get_persona", return_value={"user_profile": None}),
            patch("agent_hub_st.persona_api.update_persona", return_value={"user_profile": None}),
        ):
            result = runner.invoke(app, ["update", "--profile", "favourite_colour=blue"])

        assert result.exit_code == 1
        assert "favourite_colour" in result.output

    def test_profile_requires_field_equals_text(self) -> None:
        result = runner.invoke(app, ["update", "--profile", "communication_style"])

        assert result.exit_code == 1
