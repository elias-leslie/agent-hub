"""Tests for st agents CLI memory-config controls."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from agent_hub_st.agents import app
from typer.testing import CliRunner

runner = CliRunner()


def _agent(
    slug: str,
    model: str,
    *,
    coding: bool = False,
    name: str | None = None,
    fallbacks: list[str] | None = None,
) -> dict[str, object]:
    return {
        "slug": slug,
        "name": name or slug.replace("-", " ").title(),
        "description": "",
        "primary_model_id": model,
        "fallback_models": fallbacks or [],
        "escalation_model_id": None,
        "is_coding_agent": coding,
        "is_active": True,
        "thinking_level": "medium",
        "temperature": 0.1,
        "timeout_seconds": None,
        "version": 1,
        "memory_config": None,
    }


def _model(model_id: str, **scores: int) -> dict[str, object]:
    return {
        "id": model_id,
        "scores": {
            "coding": scores.get("coding", 1),
            "reasoning": scores.get("reasoning", 2),
            "planning": scores.get("planning", 3),
            "tool_use": scores.get("tool_use", 4),
            "instruction": scores.get("instruction", 5),
            "design": scores.get("design", 6),
        },
    }


def test_list_agents_defaults_to_compact_scored_rows() -> None:
    agents_payload = {
        "agents": [
            _agent("coder", "kimi-code/kimi-for-coding", coding=True, fallbacks=["minimax/MiniMax-M2.7"]),
            _agent("designer", "claude-sonnet-4-6", name="UI Designer"),
        ],
        "total": 2,
    }
    models_payload = {
        "models": [
            _model("kimi-code/kimi-for-coding", coding=90, design=82),
            _model("claude-sonnet-4-6", coding=80, design=72),
        ]
    }

    with (
        patch("agent_hub_st.agents.agents_api", return_value=agents_payload) as mock_agents_api,
        patch("agent_hub_st.agents.models_api", return_value=models_payload),
    ):
        result = runner.invoke(app, ["list"])

    assert result.exit_code == 0
    assert mock_agents_api.call_args.kwargs["params"] == {
        "active_only": "true",
        "limit": 100,
        "offset": 0,
    }
    assert "AGENTS[2 shown/2 total]" in result.output
    assert "slug" in result.output
    assert "primary" in result.output
    assert "coder" in result.output
    assert "kimi-code/kimi-for-coding" in result.output
    assert " C " in result.output
    assert " 90 " in result.output
    assert "designer" in result.output
    assert " D " in result.output
    assert " 72 " in result.output
    assert '"agents"' not in result.output


def test_list_agents_focus_matching_uses_words_not_substrings() -> None:
    agents_payload = {
        "agents": [
            _agent("equity-analyst", "minimax/MiniMax-M2.7", name="Equity Analyst"),
            _agent("prompt-builder", "minimax/MiniMax-M2.7", name="Prompt Builder"),
        ],
        "total": 2,
    }
    models_payload = {"models": [_model("minimax/MiniMax-M2.7", reasoning=88, planning=80, instruction=86, design=64)]}

    with (
        patch("agent_hub_st.agents.agents_api", return_value=agents_payload),
        patch("agent_hub_st.agents.models_api", return_value=models_payload),
    ):
        result = runner.invoke(app, ["list"])

    assert result.exit_code == 0
    assert "equity-analyst" in result.output
    assert " F " in result.output
    assert " 86 " in result.output
    assert "prompt-builder" in result.output
    assert " I " in result.output
    assert " 86 " in result.output
    assert " D " not in result.output


def test_list_agents_scores_use_workload_fit_for_persona_and_verifier() -> None:
    agents_payload = {
        "agents": [
            _agent("persona", "codex/gpt-5.5", name="Jenny"),
            _agent("verifier", "codex/gpt-5.5", name="Verifier"),
        ],
        "total": 2,
    }
    models_payload = {
        "models": [
            _model(
                "codex/gpt-5.5",
                reasoning=100,
                planning=90,
                tool_use=56,
                instruction=74,
            )
        ]
    }

    with (
        patch("agent_hub_st.agents.agents_api", return_value=agents_payload),
        patch("agent_hub_st.agents.models_api", return_value=models_payload),
    ):
        result = runner.invoke(app, ["list"])

    assert result.exit_code == 0
    assert "persona" in result.output
    assert " J " in result.output
    assert " 87 " in result.output
    assert "verifier" in result.output
    assert " V " in result.output
    assert " 85 " in result.output


def test_list_agents_scores_view_includes_score_vector() -> None:
    agents_payload = {"agents": [_agent("reviewer", "minimax/MiniMax-M2.7")], "total": 1}
    models_payload = {"models": [_model("minimax/MiniMax-M2.7", coding=84, reasoning=88, planning=80)]}

    with (
        patch("agent_hub_st.agents.agents_api", return_value=agents_payload),
        patch("agent_hub_st.agents.models_api", return_value=models_payload),
    ):
        result = runner.invoke(app, ["list", "--scores"])

    assert result.exit_code == 0
    assert "scores" in result.output
    assert "C84 R88 P80 T4 I5 D6" in result.output


def test_list_agents_by_model_groups_assignments() -> None:
    agents_payload = {
        "agents": [
            _agent("coder", "kimi-code/kimi-for-coding", coding=True),
            _agent("debugger", "kimi-code/kimi-for-coding", coding=True),
            _agent("planner", "minimax/MiniMax-M2.7"),
        ],
        "total": 3,
    }
    models_payload = {
        "models": [
            _model("kimi-code/kimi-for-coding", coding=90),
            _model("minimax/MiniMax-M2.7", planning=80),
        ]
    }

    with (
        patch("agent_hub_st.agents.agents_api", return_value=agents_payload),
        patch("agent_hub_st.agents.models_api", return_value=models_payload),
    ):
        result = runner.invoke(app, ["list", "--by-model"])

    assert result.exit_code == 0
    assert "AGENT_MODELS[2 primary models/3 agents]" in result.output
    assert "kimi-code/kimi-for-coding" in result.output
    assert "coder,debugger" in result.output
    assert "minimax/MiniMax-M2.7" in result.output


def test_list_agents_json_preserves_full_payload() -> None:
    agents_payload = {"agents": [_agent("coder", "kimi-code/kimi-for-coding", coding=True)], "total": 1}

    with (
        patch("agent_hub_st.agents.agents_api", return_value=agents_payload),
        patch("agent_hub_st.agents.models_api") as mock_models_api,
    ):
        result = runner.invoke(app, ["list", "--json"])

    assert result.exit_code == 0
    assert json.loads(result.output) == agents_payload
    mock_models_api.assert_not_called()


def test_get_agent_prints_token_efficient_routing_detail() -> None:
    agent_payload = _agent(
        "refactor",
        "kimi-code/kimi-for-coding",
        coding=True,
        fallbacks=["minimax/MiniMax-M2.7", "codex/gpt-5.4-mini"],
    )
    agent_payload["escalation_model_id"] = "codex/gpt-5.5"
    agent_payload["memory_config"] = {
        "injection_enabled": True,
        "include_mandates": True,
        "include_references": False,
        "audience_tags": ["coding", "tooling"],
    }

    with patch("agent_hub_st.agents.agents_api", return_value=agent_payload):
        result = runner.invoke(app, ["get", "refactor"])

    assert result.exit_code == 0
    assert "primary=kimi-code/kimi-for-coding" in result.output
    assert "fallbacks=minimax/MiniMax-M2.7,codex/gpt-5.4-mini" in result.output
    assert "escalation=codex/gpt-5.5" in result.output
    assert "memory=inject=true mandates=true refs=false audience=coding,tooling" in result.output
    assert "memory_config" not in result.output


def test_get_agent_json_preserves_full_payload() -> None:
    agent_payload = _agent("refactor", "codex/gpt-5.4", coding=True)

    with patch("agent_hub_st.agents.agents_api", return_value=agent_payload):
        result = runner.invoke(app, ["get", "refactor", "--json"])

    assert result.exit_code == 0
    assert json.loads(result.output) == agent_payload


def test_agent_versions_uses_api_and_prints_compact_history() -> None:
    versions_payload = [
        {
            "version": 2,
            "config_snapshot": {
                "primary_model_id": "kimi-code/kimi-for-coding",
                "fallback_models": ["minimax/MiniMax-M2.7"],
                "escalation_model_id": "codex/gpt-5.5",
                "thinking_level": "medium",
            },
            "change_reason": "Prefer subscription coding route",
            "created_at": "2026-05-14T12:00:00Z",
        }
    ]

    with patch("agent_hub_st.agents.agents_api", return_value=versions_payload) as mock_api:
        result = runner.invoke(app, ["versions", "refactor", "--limit", "5"])

    assert result.exit_code == 0
    assert mock_api.call_args.args[:2] == ("GET", "/refactor/versions")
    assert mock_api.call_args.kwargs["params"] == {"limit": 5}
    assert "AGENT_VERSIONS[1]" in result.output
    assert "kimi-code/kimi-for-coding" in result.output
    assert "minimax/MiniMax-M2.7" in result.output


def test_agent_activity_uses_api_and_prints_sessions_and_requests() -> None:
    activity_payload = {
        "agent_slug": "refactor",
        "sessions": [
            {
                "created_at": "2026-05-14T12:00:00Z",
                "id": "session-1",
                "external_id": "task-1",
                "model": "kimi-code/kimi-for-coding",
                "models_used": ["kimi-code/kimi-for-coding"],
                "status": "completed",
                "health_detail": None,
            }
        ],
        "requests": [
            {
                "created_at": "2026-05-14T12:00:10Z",
                "session_id": "session-1",
                "model": "kimi-code/kimi-for-coding",
                "status_code": 200,
                "latency_ms": 1234,
                "timed_out": False,
                "used_fallback": False,
                "fallback_model": None,
            }
        ],
    }

    with patch("agent_hub_st.agents.agents_api", return_value=activity_payload) as mock_api:
        result = runner.invoke(app, ["activity", "refactor", "--external-id", "task-1", "--limit", "3"])

    assert result.exit_code == 0
    assert mock_api.call_args.args[:2] == ("GET", "/refactor/activity")
    assert mock_api.call_args.kwargs["params"] == {"limit": 3, "external_id": "task-1"}
    assert "AGENT_ACTIVITY[refactor]" in result.output
    assert "session-1" in result.output
    assert "kimi-code/kimi-for-coding" in result.output


def test_update_agent_can_clear_fallback_models() -> None:
    updated_payload = _agent("refactor", "kimi-code/kimi-for-coding", coding=True)

    with patch("agent_hub_st.agents.agents_api", return_value=updated_payload) as mock_api:
        result = runner.invoke(app, ["update", "refactor", "--clear-fallback-models"])

    assert result.exit_code == 0
    assert mock_api.call_args.args[:2] == ("PUT", "/refactor")
    assert mock_api.call_args.kwargs["json"]["fallback_models"] == []


def test_update_agent_rejects_clear_and_set_fallback_models_together() -> None:
    result = runner.invoke(
        app,
        [
            "update",
            "refactor",
            "--clear-fallback-models",
            "--fallback-model",
            "codex/gpt-5.4-mini",
        ],
    )

    assert result.exit_code == 1
    assert "Use either --fallback-model or --clear-fallback-models" in result.output


def test_preview_agent_defaults_to_compact_summary() -> None:
    preview_payload = {
        "name": "Code Generator",
        "task_type": "chat",
        "sections": [
            {
                "label": "Coder Agent",
                "source_kind": "agent_prompt",
                "source_id": "coder",
                "estimated_tokens": 253,
                "share_of_total": 0.42,
                "content": "FULL SECTION BODY",
            }
        ],
        "mandate_count": 2,
        "guardrail_count": 1,
        "full_context": "FULL CONTEXT",
        "prompt_budget": {
            "severity": "ok",
            "total_estimated_tokens": 600,
            "low_yield_estimated_tokens": 0,
            "warning_count": 0,
        },
    }

    with patch("agent_hub_st.agents.agent_preview_api", return_value=preview_payload):
        result = runner.invoke(app, ["preview", "coder"])

    assert result.exit_code == 0
    assert "Code Generator preview | mode=chat | sections=1 | mandates=2 | guardrails=1" in result.output
    assert "prompt=600 tok | severity=ok" in result.output
    assert "Coder Agent" in result.output
    assert "FULL SECTION BODY" not in result.output
    assert "FULL CONTEXT" not in result.output


def test_preview_agent_show_content_preserves_full_detail() -> None:
    preview_payload = {
        "name": "Code Generator",
        "task_type": "chat",
        "sections": [
            {
                "label": "Coder Agent",
                "placement": "system",
                "source_kind": "agent_prompt",
                "source_id": "coder",
                "estimated_tokens": 253,
                "content": "FULL SECTION BODY",
            }
        ],
        "mandate_count": 0,
        "guardrail_count": 0,
        "full_context": "FULL CONTEXT",
    }

    with patch("agent_hub_st.agents.agent_preview_api", return_value=preview_payload):
        result = runner.invoke(app, ["preview", "coder", "--show-content"])

    assert result.exit_code == 0
    assert "=== Coder Agent | system | agent_prompt | coder | 253 tok ===" in result.output
    assert "FULL SECTION BODY" in result.output
    assert "=== Full Context ===" in result.output
    assert "FULL CONTEXT" in result.output


def test_create_agent_posts_full_payload(tmp_path: Path) -> None:
    prompt_path = tmp_path / "prompt.md"
    prompt_path.write_text("You are purpose built.", encoding="utf-8")
    memory_path = tmp_path / "memory.json"
    memory_path.write_text(json.dumps({"include_mandates": True}), encoding="utf-8")

    with (
        patch("agent_hub_st.agents.agents_api", return_value={"slug": "graphify-semantic-extractor"}) as mock_agents_api,
        patch("agent_hub_st.agents._print_agent"),
    ):
        result = runner.invoke(
            app,
            [
                "create",
                "graphify-semantic-extractor",
                "Graphify Semantic Extractor",
                "--primary-model",
                "served-scout-model",
                "--fallback-model",
                "served-reasoner-model",
                "--fallback-model",
                "served-code-model",
                "--escalation-model",
                "served-code-model",
                "--temperature",
                "0.1",
                "--timeout-seconds",
                "300",
                "--thinking-level",
                "high",
                "--verbosity-level",
                "low",
                "--non-coding-agent",
                "--system-prompt-file",
                str(prompt_path),
                "--memory-config-file",
                str(memory_path),
            ],
        )

    assert result.exit_code == 0
    assert mock_agents_api.call_args.args == ("POST", "")
    assert mock_agents_api.call_args.kwargs["json"] == {
        "slug": "graphify-semantic-extractor",
        "name": "Graphify Semantic Extractor",
        "system_prompt": "You are purpose built.",
        "primary_model_id": "served-scout-model",
        "temperature": 0.1,
        "timeout_seconds": 300.0,
        "is_active": True,
        "is_coding_agent": False,
        "thinking_level": "high",
        "verbosity_level": "low",
        "fallback_models": ["served-reasoner-model", "served-code-model"],
        "escalation_model_id": "served-code-model",
        "memory_config": {"include_mandates": True},
    }


def test_update_agent_model_flags_update_assignment_and_routing_mode_only() -> None:
    with (
        patch(
            "agent_hub_st.agents.agents_api",
            side_effect=[
                {"slug": "verifier"},
                {"agent_slug": "verifier"},
            ],
        ) as mock_agents_api,
        patch("agent_hub_st.agents._print_agent"),
    ):
        result = runner.invoke(
            app,
            [
                "update",
                "verifier",
                "--primary-model",
                "codex/gpt-5.5",
                "--fallback-model",
                "claude-opus-4-7",
                "--escalation-model",
                "claude-opus-4-7",
                "--timeout-seconds",
                "300",
                "--routing-mode",
                "manual_locked",
                "--change-reason",
                "critical verification route",
            ],
        )

    assert result.exit_code == 0
    assert mock_agents_api.call_args_list[0].args == ("PUT", "/verifier")
    assert mock_agents_api.call_args_list[0].kwargs["json"] == {
        "primary_model_id": "codex/gpt-5.5",
        "escalation_model_id": "claude-opus-4-7",
        "timeout_seconds": 300.0,
        "fallback_models": ["claude-opus-4-7"],
        "change_reason": "critical verification route",
    }
    assert mock_agents_api.call_args_list[1].args == ("PUT", "/verifier/routing")
    assert mock_agents_api.call_args_list[1].kwargs["json"] == {
        "default_routing_mode": "manual_locked",
    }


def test_update_agent_model_flags_do_not_create_manual_route_by_default() -> None:
    with (
        patch(
            "agent_hub_st.agents.agents_api",
            return_value={"slug": "planner"},
        ) as mock_agents_api,
        patch("agent_hub_st.agents._print_agent"),
    ):
        result = runner.invoke(
            app,
            [
                "update",
                "planner",
                "--primary-model",
                "minimax/MiniMax-M2.7",
                "--change-reason",
                "manual test route",
            ],
        )

    assert result.exit_code == 0
    assert [call.args for call in mock_agents_api.call_args_list] == [("PUT", "/planner")]


def test_update_agent_fallback_only_does_not_sync_manual_route() -> None:
    with (
        patch(
            "agent_hub_st.agents.agents_api",
            return_value={"slug": "portfolio-mgr-v1"},
        ) as mock_agents_api,
        patch("agent_hub_st.agents._print_agent"),
    ):
        result = runner.invoke(
            app,
            [
                "update",
                "portfolio-mgr-v1",
                "--fallback-model",
                "codex/gpt-5.5",
                "--fallback-model",
                "gemini-3.1-pro-preview",
                "--change-reason",
                "fallbacks only",
            ],
        )

    assert result.exit_code == 0
    assert [call.args for call in mock_agents_api.call_args_list] == [("PUT", "/portfolio-mgr-v1")]
    assert mock_agents_api.call_args.kwargs["json"] == {
        "fallback_models": ["codex/gpt-5.5", "gemini-3.1-pro-preview"],
        "change_reason": "fallbacks only",
    }


def test_update_agent_routing_mode_does_not_sync_manual_route() -> None:
    with (
        patch(
            "agent_hub_st.agents.agents_api",
            side_effect=[
                {"slug": "portfolio-mgr-v1"},
                {"agent_slug": "portfolio-mgr-v1"},
            ],
        ) as mock_agents_api,
        patch("agent_hub_st.agents._print_agent"),
    ):
        result = runner.invoke(
            app,
            [
                "update",
                "portfolio-mgr-v1",
                "--routing-mode",
                "manual_locked",
            ],
        )

    assert result.exit_code == 0
    assert [call.args for call in mock_agents_api.call_args_list] == [
        ("GET", "/portfolio-mgr-v1"),
        ("PUT", "/portfolio-mgr-v1/routing"),
    ]
    assert mock_agents_api.call_args_list[1].kwargs["json"] == {
        "default_routing_mode": "manual_locked",
    }


class TestAgentMemoryConfigUpdate:
    """Tests for granular memory-config updates on `st agents update`."""

    def test_update_merges_memory_config_flags_into_existing_agent(self) -> None:
        current_agent = {
            "slug": "debugger",
            "memory_config": {
                "include_references": True,
                "continuity_enabled": False,
                "audience_tags": ["existing-tag"],
                "exclude_tags": ["deprecated"],
            },
        }

        with (
            patch("agent_hub_st.agents.agents_api", side_effect=[current_agent, {"slug": "debugger"}]) as mock_agents_api,
            patch("agent_hub_st.agents._print_agent"),
        ):
            result = runner.invoke(
                app,
                [
                    "update",
                    "debugger",
                    "--memory-enabled",
                    "--continuity-enabled",
                    "--continuity-max-sessions",
                    "7",
                    "--add-audience-tags",
                    "jenny-relevant,memory-system",
                    "--remove-exclude-tags",
                    "deprecated",
                    "--change-reason",
                    "route memory to debugger",
                ],
            )

        assert result.exit_code == 0
        assert mock_agents_api.call_args_list[0].args == ("GET", "/debugger")
        assert mock_agents_api.call_args_list[1].args == ("PUT", "/debugger")
        assert mock_agents_api.call_args_list[1].kwargs["json"] == {
            "memory_config": {
                "include_references": True,
                "continuity_enabled": True,
                "audience_tags": ["existing-tag", "jenny-relevant", "memory-system"],
                "exclude_tags": [],
                "injection_enabled": True,
                "continuity_max_sessions": 7,
            },
            "change_reason": "route memory to debugger",
        }

    def test_update_initializes_memory_config_when_agent_has_none(self) -> None:
        current_agent = {"slug": "persona", "memory_config": None}

        with (
            patch("agent_hub_st.agents.agents_api", side_effect=[current_agent, {"slug": "persona"}]) as mock_agents_api,
            patch("agent_hub_st.agents._print_agent"),
        ):
            result = runner.invoke(
                app,
                [
                    "update",
                    "persona",
                    "--memory-disabled",
                    "--include-references",
                    "--no-include-guardrails",
                    "--audience-tags",
                    "jenny-relevant,memory-system",
                    "--exclude-tags",
                    "stale",
                ],
            )

        assert result.exit_code == 0
        assert mock_agents_api.call_args_list[1].kwargs["json"]["memory_config"] == {
            "injection_enabled": False,
            "include_references": True,
            "include_guardrails": False,
            "audience_tags": ["jenny-relevant", "memory-system"],
            "exclude_tags": ["stale"],
        }

    def test_update_rejects_granular_memory_flags_with_memory_config_file(self, tmp_path: Path) -> None:
        config_path = tmp_path / "memory.json"

        with patch("agent_hub_st.agents.agents_api") as mock_agents_api:
            result = runner.invoke(
                app,
                [
                    "update",
                    "debugger",
                    "--memory-config-file",
                    str(config_path),
                    "--add-audience-tags",
                    "memory-system",
                ],
            )

        assert result.exit_code == 1
        assert "Use either granular memory-config flags or --memory-config-file/--clear-memory-config, not both" in result.output
        mock_agents_api.assert_not_called()
