"""Tests for controlled benchmark experiment comparison logic."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.services.agent_benchmark_service import (
    _should_update_regression_clusters,
    capture_benchmark_config_snapshot,
    summarize_benchmark_experiment,
)


def _make_run(
    *,
    cohort: str,
    avg_score: float,
    pass_rate: float,
    completed_at: str = "2026-03-11T12:00:00+00:00",
    config_snapshot: dict[str, object] | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        experiment_cohort=cohort,
        avg_score=avg_score,
        pass_rate=pass_rate,
        config_snapshot=config_snapshot or {"primary_model_id": "codex/gpt-5.4", "thinking_level": "medium"},
        completed_at=datetime.fromisoformat(completed_at),
        models=["codex/gpt-5.4"],
        case_ids=["jenny-patience"],
        runs_per_case=1,
        use_memory=False,
        run_kind="benchmark",
    )


def _make_experiment(**overrides) -> SimpleNamespace:
    defaults = {
        "experiment_key": "jenny-patience-ab",
        "name": "Jenny patience harness A/B",
        "suite_id": "jenny-patience",
        "status": "open",
        "hypothesis": "Candidate harness should reduce false redispatches.",
        "baseline_label": "baseline",
        "candidate_label": "candidate",
        "min_runs_per_cohort": 3,
        "updated_at": datetime.now(UTC),
        "created_at": datetime.now(UTC),
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def test_summarize_benchmark_experiment_holds_when_underpowered() -> None:
    experiment = _make_experiment(min_runs_per_cohort=3)
    runs = [
        _make_run(cohort="baseline", avg_score=91.0, pass_rate=66.7),
        _make_run(cohort="candidate", avg_score=95.0, pass_rate=83.3),
    ]

    summary = summarize_benchmark_experiment(experiment, runs)

    assert summary["decision"] == "hold"
    assert summary["decision_reason"] == "underpowered"
    assert summary["baseline"]["run_count"] == 1
    assert summary["candidate"]["run_count"] == 1


def test_summarize_benchmark_experiment_holds_when_candidate_config_drifts() -> None:
    experiment = _make_experiment()
    runs = [
        _make_run(cohort="baseline", avg_score=90.0, pass_rate=60.0),
        _make_run(cohort="baseline", avg_score=91.0, pass_rate=66.7),
        _make_run(cohort="baseline", avg_score=90.5, pass_rate=66.7),
        _make_run(
            cohort="candidate",
            avg_score=95.0,
            pass_rate=83.3,
            config_snapshot={"primary_model_id": "codex/gpt-5.4", "thinking_level": "medium"},
        ),
        _make_run(
            cohort="candidate",
            avg_score=96.0,
            pass_rate=83.3,
            config_snapshot={"primary_model_id": "codex/gpt-5.4", "thinking_level": "high"},
        ),
        _make_run(
            cohort="candidate",
            avg_score=95.5,
            pass_rate=83.3,
            config_snapshot={"primary_model_id": "codex/gpt-5.4", "thinking_level": "medium"},
        ),
    ]

    summary = summarize_benchmark_experiment(experiment, runs)

    assert summary["decision"] == "hold"
    assert summary["decision_reason"] == "mixed_config"
    assert summary["candidate"]["config_stable"] is False


def test_summarize_benchmark_experiment_promotes_clear_candidate_win() -> None:
    experiment = _make_experiment()
    runs = [
        _make_run(cohort="baseline", avg_score=88.0, pass_rate=50.0),
        _make_run(cohort="baseline", avg_score=89.0, pass_rate=58.3),
        _make_run(cohort="baseline", avg_score=87.5, pass_rate=50.0),
        _make_run(cohort="candidate", avg_score=95.5, pass_rate=83.3),
        _make_run(cohort="candidate", avg_score=96.0, pass_rate=91.7),
        _make_run(cohort="candidate", avg_score=95.0, pass_rate=83.3),
    ]

    summary = summarize_benchmark_experiment(experiment, runs)

    assert summary["decision"] == "promote"
    assert summary["decision_reason"] == "candidate_outperforms_baseline"
    assert summary["score_delta"]["mean_delta"] and summary["score_delta"]["mean_delta"] > 0
    assert summary["pass_rate_delta"]["mean_delta"] and summary["pass_rate_delta"]["mean_delta"] > 0


def test_summarize_benchmark_experiment_rolls_back_clear_candidate_loss() -> None:
    experiment = _make_experiment()
    runs = [
        _make_run(cohort="baseline", avg_score=95.0, pass_rate=91.7),
        _make_run(cohort="baseline", avg_score=94.5, pass_rate=83.3),
        _make_run(cohort="baseline", avg_score=95.5, pass_rate=91.7),
        _make_run(cohort="candidate", avg_score=88.0, pass_rate=58.3),
        _make_run(cohort="candidate", avg_score=87.5, pass_rate=50.0),
        _make_run(cohort="candidate", avg_score=88.5, pass_rate=58.3),
    ]

    summary = summarize_benchmark_experiment(experiment, runs)

    assert summary["decision"] == "rollback"
    assert summary["decision_reason"] == "candidate_underperforms_baseline"
    assert summary["score_delta"]["mean_delta"] and summary["score_delta"]["mean_delta"] < 0


def test_summarize_benchmark_experiment_rolls_back_when_candidate_never_catches_up() -> None:
    experiment = _make_experiment()
    runs = [
        _make_run(cohort="baseline", avg_score=100.0, pass_rate=100.0),
        _make_run(cohort="baseline", avg_score=100.0, pass_rate=100.0),
        _make_run(cohort="baseline", avg_score=100.0, pass_rate=100.0),
        _make_run(cohort="candidate", avg_score=100.0, pass_rate=100.0),
        _make_run(cohort="candidate", avg_score=88.9, pass_rate=83.3),
        _make_run(cohort="candidate", avg_score=88.9, pass_rate=83.3),
    ]

    summary = summarize_benchmark_experiment(experiment, runs)

    assert summary["decision"] == "rollback"
    assert summary["decision_reason"] == "candidate_underperforms_baseline"
    assert summary["score_delta"]["ci_high"] == 0.0


def test_summarize_benchmark_experiment_ignores_captured_at_snapshot_drift() -> None:
    experiment = _make_experiment()
    runs = [
        _make_run(
            cohort="baseline",
            avg_score=100.0,
            pass_rate=100.0,
            config_snapshot={
                "primary_model_id": "codex/gpt-5.4",
                "thinking_level": "medium",
                "captured_at": "2026-03-11T12:00:00Z",
            },
        ),
        _make_run(
            cohort="baseline",
            avg_score=100.0,
            pass_rate=100.0,
            config_snapshot={
                "primary_model_id": "codex/gpt-5.4",
                "thinking_level": "medium",
                "captured_at": "2026-03-11T12:10:00Z",
            },
        ),
        _make_run(
            cohort="baseline",
            avg_score=100.0,
            pass_rate=100.0,
            config_snapshot={
                "primary_model_id": "codex/gpt-5.4",
                "thinking_level": "medium",
                "captured_at": "2026-03-11T12:20:00Z",
            },
        ),
        _make_run(
            cohort="candidate",
            avg_score=100.0,
            pass_rate=100.0,
            config_snapshot={
                "primary_model_id": "claude-opus-4-6",
                "thinking_level": "medium",
                "captured_at": "2026-03-11T12:30:00Z",
            },
        ),
        _make_run(
            cohort="candidate",
            avg_score=100.0,
            pass_rate=100.0,
            config_snapshot={
                "primary_model_id": "claude-opus-4-6",
                "thinking_level": "medium",
                "captured_at": "2026-03-11T12:40:00Z",
            },
        ),
        _make_run(
            cohort="candidate",
            avg_score=100.0,
            pass_rate=100.0,
            config_snapshot={
                "primary_model_id": "claude-opus-4-6",
                "thinking_level": "medium",
                "captured_at": "2026-03-11T12:50:00Z",
            },
        ),
    ]

    summary = summarize_benchmark_experiment(experiment, runs)

    assert summary["baseline"]["config_stable"] is True
    assert summary["candidate"]["config_stable"] is True
    assert summary["decision_reason"] == "no_clear_winner"


def test_summarize_benchmark_experiment_holds_when_candidate_model_roster_drifts() -> None:
    experiment = _make_experiment()
    runs = [
        _make_run(cohort="baseline", avg_score=90.0, pass_rate=60.0),
        _make_run(cohort="baseline", avg_score=90.5, pass_rate=66.7),
        _make_run(cohort="baseline", avg_score=91.0, pass_rate=66.7),
        _make_run(cohort="candidate", avg_score=95.0, pass_rate=83.3),
        _make_run(
            cohort="candidate",
            avg_score=95.5,
            pass_rate=83.3,
            config_snapshot={"primary_model_id": "codex/gpt-5.4", "thinking_level": "medium"},
        ),
        _make_run(
            cohort="candidate",
            avg_score=95.0,
            pass_rate=83.3,
            config_snapshot={"primary_model_id": "codex/gpt-5.4", "thinking_level": "medium"},
        ),
    ]
    runs[3].models = ["codex/gpt-5.4"]
    runs[4].models = ["claude-opus-4-6"]
    runs[5].models = ["codex/gpt-5.4"]

    summary = summarize_benchmark_experiment(experiment, runs)

    assert summary["decision"] == "hold"
    assert summary["decision_reason"] == "mixed_config"
    assert summary["candidate"]["config_stable"] is False


def test_should_update_regression_clusters_skips_candidate_experiment_runs_by_default() -> None:
    assert _should_update_regression_clusters(experiment_cohort="candidate", metadata={}) is False
    assert _should_update_regression_clusters(experiment_cohort="baseline", metadata={}) is True


def test_should_update_regression_clusters_honors_explicit_override() -> None:
    assert _should_update_regression_clusters(
        experiment_cohort="candidate",
        metadata={"update_regression_clusters": True},
    ) is True


@pytest.mark.asyncio
async def test_capture_benchmark_config_snapshot_includes_completion_reviewer_for_persona() -> None:
    persona_agent = SimpleNamespace(
        id=17,
        slug="persona",
        version=7,
        primary_model_id="codex/gpt-5.4",
        fallback_models=["claude-sonnet-4-6"],
        escalation_model_id="claude-sonnet-4-6",
        thinking_level="medium",
        temperature=0.3,
    )
    heartbeat_prompt = SimpleNamespace(
        slug="persona-heartbeat-instructions",
        content="Focus on cleanup first",
        updated_at=datetime.fromisoformat("2026-03-11T12:00:00+00:00"),
    )
    supervisor_agent = SimpleNamespace(
        slug="supervisor",
        version=3,
        primary_model_id="claude-opus-4-6",
        fallback_models=["codex/gpt-5.4"],
        escalation_model_id=None,
        thinking_level="high",
        temperature=0.2,
    )

    persona = SimpleNamespace(
        personality="Warm, direct, adaptive.",
        user_context="Prefers concise release updates.",
        user_profile={"timezone": "America/New_York", "autonomy_level": "high"},
        onboarding_phase="complete",
    )
    memory_revision = SimpleNamespace(
        id=42,
        created_at=datetime.fromisoformat("2026-03-12T08:00:00+00:00"),
        memory_uuid="mem-uuid-001",
    )
    mock_db = AsyncMock()
    mock_db.scalar = AsyncMock(
        side_effect=[persona_agent, memory_revision, 5, persona, heartbeat_prompt, supervisor_agent]
    )

    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def _session():
        yield mock_db

    with (
        patch("app.services.agent_benchmark_service.async_session", _session),
        patch(
            "app.services.persona_document_prompt_service.get_persona_personality_document",
            new=AsyncMock(return_value=persona.personality),
        ),
        patch(
            "app.services.persona_document_prompt_service.get_persona_user_context_document",
            new=AsyncMock(return_value=persona.user_context),
        ),
        patch(
            "app.services.agent_benchmark_service.collect_runtime_prompt_sections",
            new=AsyncMock(
                return_value=[
                    SimpleNamespace(
                        source_kind="agent_system_prompt",
                        source_id="persona",
                        content_hash="abcd1234",
                        to_snapshot_dict=lambda: {
                            "label": "Agent System Prompt",
                            "source_kind": "agent_system_prompt",
                            "source_id": "persona",
                            "content_hash": "abcd1234",
                            "chars": 32,
                            "estimated_tokens": 8,
                        },
                    )
                ]
            ),
        ),
        patch("app.services.agent_benchmark_service._task_prompt_slugs", return_value=[]),
    ):
        snapshot = await capture_benchmark_config_snapshot("persona", task_type="heartbeat")

    assert snapshot["primary_model_id"] == "codex/gpt-5.4"
    assert snapshot["prompt_stack"]["task_type"] == "heartbeat"
    assert snapshot["prompt_stack"]["descriptors"] == ["agent_system_prompt:persona:abcd1234"]
    assert snapshot["heartbeat_prompt"]["slug"] == "persona-heartbeat-instructions"
    assert snapshot["completion_reviewer"]["agent_slug"] == "supervisor"
    assert snapshot["completion_reviewer"]["primary_model_id"] == "claude-opus-4-6"
    assert snapshot["persona_documents"]["user_profile"]["field_count"] == 2
