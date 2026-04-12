"""Tests for controlled benchmark experiment comparison logic."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.dialects import postgresql

from app.services._benchmark_dashboard import is_signal_run_kind
from app.services._benchmark_persistence import (
    _group_attempt_failures,
    _has_scored_attempts,
    _refresh_experiment_decision,
)
from app.services.agent_benchmark_service import (
    _should_update_regression_clusters,
    capture_benchmark_config_snapshot,
    get_benchmark_experiment_summary_by_key,
    memory_state_descriptor,
    summarize_benchmark_experiment,
)
from app.services.persona_improvement import build_persona_improvement_metadata


def _make_run(
    *,
    cohort: str,
    avg_score: float | None,
    pass_rate: float | None,
    avg_tool_calls: float | None = None,
    avg_total_tokens: float | None = None,
    avg_turns: float | None = None,
    completed_at: str = "2026-03-11T12:00:00+00:00",
    config_snapshot: dict[str, object] | None = None,
    attempt_count: int = 6,
    infra_failure_count: int = 0,
) -> SimpleNamespace:
    run_metadata = {}
    if any(metric is not None for metric in (avg_tool_calls, avg_total_tokens, avg_turns)):
        run_metadata["efficiency"] = {
            "avg_tool_calls": avg_tool_calls,
            "avg_total_tokens": avg_total_tokens,
            "avg_turns": avg_turns,
        }
    return SimpleNamespace(
        experiment_cohort=cohort,
        avg_score=avg_score,
        pass_rate=pass_rate,
        attempt_count=attempt_count,
        infra_failure_count=infra_failure_count,
        run_metadata=run_metadata,
        config_snapshot=config_snapshot or {"primary_model_id": "codex/gpt-5.4", "thinking_level": "medium"},
        completed_at=datetime.fromisoformat(completed_at),
        models=["codex/gpt-5.4"],
        case_ids=["persona-patience"],
        runs_per_case=1,
        use_memory=False,
        run_kind="benchmark",
    )


def _make_experiment(**overrides) -> SimpleNamespace:
    defaults = {
        "id": 1,
        "experiment_key": "persona-patience-ab",
        "name": "Persona patience harness A/B",
        "suite_id": "persona-patience",
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
    assert summary["status"] == "open"
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
    assert summary["status"] == "closed"
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
    assert summary["status"] == "closed"
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


def test_summarize_benchmark_experiment_promotes_non_inferior_candidate_with_fewer_tool_calls() -> None:
    experiment = _make_experiment()
    runs = [
        _make_run(cohort="baseline", avg_score=100.0, pass_rate=100.0, avg_tool_calls=6.0),
        _make_run(cohort="baseline", avg_score=100.0, pass_rate=100.0, avg_tool_calls=5.5),
        _make_run(cohort="baseline", avg_score=100.0, pass_rate=100.0, avg_tool_calls=6.5),
        _make_run(cohort="candidate", avg_score=100.0, pass_rate=100.0, avg_tool_calls=3.0),
        _make_run(cohort="candidate", avg_score=100.0, pass_rate=100.0, avg_tool_calls=3.5),
        _make_run(cohort="candidate", avg_score=100.0, pass_rate=100.0, avg_tool_calls=2.5),
    ]

    summary = summarize_benchmark_experiment(experiment, runs)

    assert summary["decision"] == "promote"
    assert summary["decision_reason"] == "candidate_matches_quality_with_fewer_tool_calls"
    assert summary["tool_call_delta"]["mean_delta"] and summary["tool_call_delta"]["mean_delta"] < 0


def test_summarize_benchmark_experiment_rolls_back_non_superior_candidate_with_more_tool_calls() -> None:
    experiment = _make_experiment()
    runs = [
        _make_run(cohort="baseline", avg_score=100.0, pass_rate=100.0, avg_tool_calls=2.0),
        _make_run(cohort="baseline", avg_score=100.0, pass_rate=100.0, avg_tool_calls=2.5),
        _make_run(cohort="baseline", avg_score=100.0, pass_rate=100.0, avg_tool_calls=1.5),
        _make_run(cohort="candidate", avg_score=100.0, pass_rate=100.0, avg_tool_calls=6.0),
        _make_run(cohort="candidate", avg_score=100.0, pass_rate=100.0, avg_tool_calls=5.5),
        _make_run(cohort="candidate", avg_score=100.0, pass_rate=100.0, avg_tool_calls=6.5),
    ]

    summary = summarize_benchmark_experiment(experiment, runs)

    assert summary["decision"] == "rollback"
    assert summary["decision_reason"] == "candidate_matches_quality_with_more_tool_calls"
    assert summary["tool_call_delta"]["mean_delta"] and summary["tool_call_delta"]["mean_delta"] > 0


def test_build_persona_improvement_metadata_tracks_reliability_effectiveness_and_prompt_tokens() -> None:
    metadata = build_persona_improvement_metadata(
        [
            {
                "case_id": "ready_task_dispatch",
                "passed": True,
                "infra_failure": False,
                "failure_kind": None,
                "failure_detail": None,
                "composite_score": 100.0,
                "correctness_score": 1.0,
                "total_tokens": 1200,
                "latency_ms": 200,
                "turns": 2,
                "tool_calls_count": 2,
            },
            {
                "case_id": "same_task_overlap",
                "passed": False,
                "infra_failure": False,
                "failure_kind": "model",
                "failure_detail": "wrong_fields: primary_action",
                "composite_score": 0.0,
                "correctness_score": 0.0,
                "total_tokens": 900,
                "latency_ms": 180,
                "turns": 1,
                "tool_calls_count": 1,
            },
            {
                "case_id": "cleanup_blocks_closeout",
                "passed": True,
                "infra_failure": False,
                "failure_kind": None,
                "failure_detail": None,
                "composite_score": 100.0,
                "correctness_score": 1.0,
                "total_tokens": 800,
                "latency_ms": 160,
                "turns": 1,
                "tool_calls_count": 1,
            },
        ],
        config_snapshot={
            "preview_summary": {
                "total_estimated_tokens": 16000,
                "by_source_kind": {
                    "agent_system_prompt": 6400,
                    "memory_context": 4600,
                    "task_prompt": 4200,
                },
            }
        },
    )

    assert metadata["reliability"] == 66.7
    assert metadata["effectiveness"] == 50.0
    assert metadata["tokens_per_passed_attempt"] == 1450.0
    assert metadata["prompt_tokens"] == 16000
    assert metadata["top_failure_detail"] == "wrong_fields: primary_action"


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


def test_is_signal_run_kind_excludes_honing_iteration() -> None:
    assert is_signal_run_kind("benchmark") is True
    assert is_signal_run_kind("completion_review_benchmark") is True
    assert is_signal_run_kind("honing_baseline") is True
    assert is_signal_run_kind("honing_candidate") is True
    assert is_signal_run_kind("honing_iteration") is False


def test_group_attempt_failures_skips_infra_failures() -> None:
    grouped = _group_attempt_failures([
        {
            "case_id": "precision_search_architecture",
            "failure_detail": "All connection attempts failed",
            "failure_kind": "infra",
            "infra_failure": True,
            "passed": False,
            "composite_score": 0.0,
            "model_id": "codex/gpt-5.4",
        },
        {
            "case_id": "precision_search_architecture",
            "failure_detail": "wrong_fields: should_dispatch",
            "failure_kind": "model",
            "infra_failure": False,
            "passed": False,
            "composite_score": 20.0,
            "model_id": "codex/gpt-5.4",
        },
    ])

    assert list(grouped) == [("precision_search_architecture", "wrong_fields: should_dispatch")]


def test_has_scored_attempts_returns_false_for_infra_only_payloads() -> None:
    assert _has_scored_attempts([
        {
            "infra_failure": True,
            "failure_kind": "infra",
            "failure_detail": "All connection attempts failed",
            "passed": False,
        }
    ]) is False
    assert _has_scored_attempts([
        {
            "infra_failure": False,
            "failure_kind": "model",
            "failure_detail": "wrong_fields: should_dispatch",
            "passed": False,
        }
    ]) is True


def test_summarize_benchmark_experiment_ignores_infra_only_runs() -> None:
    experiment = _make_experiment(min_runs_per_cohort=1)
    runs = [
        _make_run(
            cohort="baseline",
            avg_score=None,
            pass_rate=None,
            attempt_count=6,
            infra_failure_count=6,
        ),
        _make_run(
            cohort="baseline",
            avg_score=90.0,
            pass_rate=60.0,
        ),
        _make_run(
            cohort="candidate",
            avg_score=95.0,
            pass_rate=80.0,
        ),
    ]

    summary = summarize_benchmark_experiment(experiment, runs)

    assert summary["baseline"]["run_count"] == 1
    assert summary["baseline"]["infra_only_run_count"] == 1
    assert summary["decision"] == "promote"


@pytest.mark.asyncio
async def test_get_benchmark_experiment_summary_by_key_filters_to_signal_runs() -> None:
    experiment = _make_experiment(id="exp-1")
    mock_db = AsyncMock()
    run_result = MagicMock()
    run_result.scalars.return_value.all.return_value = []
    mock_db.scalar = AsyncMock(return_value=experiment)
    mock_db.execute.return_value = run_result

    with patch(
        "app.services.agent_benchmark_service.summarize_benchmark_experiment",
        return_value={"decision": "hold"},
    ) as mock_summarize:
        await get_benchmark_experiment_summary_by_key(mock_db, experiment.experiment_key)

    stmt = mock_db.execute.await_args.args[0]
    compiled = stmt.compile(dialect=postgresql.dialect())
    sql = str(compiled)

    assert "agent_benchmark_runs.completed_at IS NOT NULL" in sql
    assert "agent_benchmark_runs.run_kind" in sql
    assert any(
        "honing_iteration" in (value if isinstance(value, list) else [value])
        for value in compiled.params.values()
    )
    mock_summarize.assert_called_once()


@pytest.mark.asyncio
async def test_refresh_experiment_decision_closes_finished_experiments() -> None:
    experiment = _make_experiment(status="open", decision="hold", decision_reason=None, evidence={})
    mock_db = AsyncMock()
    run_result = MagicMock()
    run_result.scalars.return_value.all.return_value = []
    mock_db.execute.return_value = run_result

    with patch(
        "app.services._benchmark_persistence.summarize_benchmark_experiment",
        return_value={
            "decision": "promote",
            "decision_reason": "candidate_outperforms_baseline",
            "baseline": {},
            "candidate": {},
            "score_delta": {"mean_delta": 2.0},
            "pass_rate_delta": {"mean_delta": 5.0},
            "min_runs_per_cohort": 3,
        },
    ):
        await _refresh_experiment_decision(mock_db, experiment)

    assert experiment.decision == "promote"
    assert experiment.status == "closed"


@pytest.mark.asyncio
async def test_refresh_experiment_decision_filters_to_signal_runs() -> None:
    experiment = _make_experiment(status="open", decision="hold", decision_reason=None, evidence={})
    mock_db = AsyncMock()
    run_result = MagicMock()
    run_result.scalars.return_value.all.return_value = []
    mock_db.execute.return_value = run_result

    with patch(
        "app.services._benchmark_persistence.summarize_benchmark_experiment",
        return_value={
            "decision": "hold",
            "decision_reason": "underpowered",
            "baseline": {},
            "candidate": {},
            "score_delta": {"mean_delta": 0.0},
            "pass_rate_delta": {"mean_delta": 0.0},
            "min_runs_per_cohort": 3,
        },
    ):
        await _refresh_experiment_decision(mock_db, experiment)

    stmt = mock_db.execute.await_args.args[0]
    compiled = stmt.compile(dialect=postgresql.dialect())
    sql = str(compiled)

    assert "agent_benchmark_runs.completed_at IS NOT NULL" in sql
    assert "agent_benchmark_runs.run_kind" in sql
    assert any(
        "honing_iteration" in (value if isinstance(value, list) else [value])
        for value in compiled.params.values()
    )


@pytest.mark.asyncio
async def test_get_agent_benchmark_dashboard_scopes_open_clusters_and_experiments_to_requested_window() -> None:
    from app.services.agent_benchmark_service import get_agent_benchmark_dashboard

    mock_db = AsyncMock()
    runs_result = MagicMock()
    runs_result.scalars.return_value.all.return_value = []
    clusters_result = MagicMock()
    clusters_result.scalars.return_value.all.return_value = []
    model_result = MagicMock()
    model_result.all.return_value = []
    case_result = MagicMock()
    case_result.all.return_value = []
    experiments_result = MagicMock()
    experiments_result.all.return_value = []
    mock_db.execute.side_effect = [
        runs_result,
        clusters_result,
        model_result,
        case_result,
        experiments_result,
    ]

    await get_agent_benchmark_dashboard(mock_db, "persona", days=7, suite_id="persona-suite")

    cluster_stmt = mock_db.execute.await_args_list[1].args[0]
    experiment_stmt = mock_db.execute.await_args_list[4].args[0]
    cluster_compiled = cluster_stmt.compile(dialect=postgresql.dialect())
    experiment_compiled = experiment_stmt.compile(dialect=postgresql.dialect())
    cluster_sql = str(cluster_compiled)
    experiment_sql = str(experiment_compiled)

    assert "JOIN agent_benchmark_runs" in cluster_sql
    assert "agent_regression_clusters.last_seen_at >=" in cluster_sql
    assert "agent_benchmark_runs.run_kind" in cluster_sql
    assert "persona-suite" in cluster_compiled.params.values()
    assert any(
        "honing_iteration" in (value if isinstance(value, list) else [value])
        for value in cluster_compiled.params.values()
    )

    assert "JOIN agent_benchmark_runs" in experiment_sql
    assert "agent_benchmark_runs.completed_at >=" in experiment_sql
    assert "agent_benchmark_runs.run_kind" in experiment_sql
    assert "max(agent_benchmark_runs.completed_at)" in experiment_sql
    assert "persona-suite" in experiment_compiled.params.values()
    assert any(
        "honing_iteration" in (value if isinstance(value, list) else [value])
        for value in experiment_compiled.params.values()
    )


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
    mock_db.scalar = AsyncMock(side_effect=[memory_revision, 5, persona, heartbeat_prompt, supervisor_agent])

    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def _session():
        yield mock_db

    with (
        patch("app.services._benchmark_config.async_session", _session),
        patch(
            "app.services._benchmark_config.get_agent_by_slug",
            new=AsyncMock(return_value=persona_agent),
        ),
        patch(
            "app.services.persona_document_prompt_service.get_persona_personality_document",
            new=AsyncMock(return_value=persona.personality),
        ),
        patch(
            "app.services.persona_document_prompt_service.get_persona_user_context_document",
            new=AsyncMock(return_value=persona.user_context),
        ),
        patch(
            "app.services._benchmark_config.collect_runtime_prompt_sections",
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
        patch("app.services._benchmark_config._task_prompt_slugs", return_value=[]),
        patch(
            "app.services._benchmark_config.collect_memory_governance_snapshot",
            new=AsyncMock(return_value={"active_count": 5, "issue_count": 0}),
        ),
        patch(
            "app.services._benchmark_config.format_project_index_context",
            return_value="<project-index>\nproject: agent-hub\n</project-index>",
        ),
        patch(
            "app.services._benchmark_config.format_tool_capability_context",
            return_value="<tool-capabilities>\ntools:\n- tool: st\n</tool-capabilities>",
        ),
        patch(
            "app.services._benchmark_config._capture_preview_summary",
            new=AsyncMock(
                return_value={
                    "task_type": "heartbeat",
                    "total_estimated_tokens": 1234,
                    "sections": [
                        {
                            "label": "Persona Context",
                            "source_kind": "agent_system_prompt",
                            "estimated_tokens": 640,
                            "chars": 2560,
                        }
                    ],
                    "by_source_kind": {"agent_system_prompt": 640},
                }
            ),
        ),
    ):
        snapshot = await capture_benchmark_config_snapshot("persona", task_type="heartbeat")

    assert snapshot["primary_model_id"] == "codex/gpt-5.4"
    assert snapshot["prompt_stack"]["task_type"] == "heartbeat"
    assert snapshot["prompt_stack"]["descriptors"] == ["agent_system_prompt:persona:abcd1234"]
    assert snapshot["generated_context"]["project_index"]["content_hash"] is not None
    assert snapshot["generated_context"]["tool_capabilities"]["content_hash"] is not None
    assert len(snapshot["generated_context"]["descriptors"]) == 2
    assert snapshot["preview_summary"]["total_estimated_tokens"] == 1234
    assert snapshot["heartbeat_prompt"]["slug"] == "persona-heartbeat-instructions"
    assert snapshot["completion_reviewer"]["agent_slug"] == "supervisor"
    assert snapshot["completion_reviewer"]["primary_model_id"] == "claude-opus-4-6"
    assert snapshot["persona_documents"]["user_profile"]["field_count"] == 2


@pytest.mark.asyncio
async def test_capture_benchmark_config_snapshot_includes_memory_variant_override() -> None:
    agent = SimpleNamespace(
        id=17,
        slug="coder",
        version=7,
        primary_model_id="codex/gpt-5.4",
        fallback_models=["claude-sonnet-4-6"],
        escalation_model_id=None,
        thinking_level="medium",
        temperature=0.3,
        memory_config={
            "tool_capabilities_enabled": False,
            "runtime_consumer_profile": "agent_coding",
        },
    )
    memory_revision = SimpleNamespace(
        id=42,
        created_at=datetime.fromisoformat("2026-03-12T08:00:00+00:00"),
        memory_uuid="mem-uuid-001",
    )
    mock_db = AsyncMock()
    mock_db.scalar = AsyncMock(side_effect=[memory_revision, 5])

    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def _session():
        yield mock_db

    with (
        patch("app.services._benchmark_config.async_session", _session),
        patch(
            "app.services._benchmark_config.get_agent_by_slug",
            new=AsyncMock(return_value=agent),
        ),
        patch(
            "app.services._benchmark_config.collect_runtime_prompt_sections",
            new=AsyncMock(return_value=[]),
        ),
        patch("app.services._benchmark_config._task_prompt_slugs", return_value=[]),
        patch(
            "app.services._benchmark_config.collect_memory_governance_snapshot",
            new=AsyncMock(return_value={"active_count": 5, "issue_count": 0}),
        ),
        patch(
            "app.services._benchmark_config.format_project_index_context",
            return_value="",
        ) as format_project_index_context,
        patch(
            "app.services._benchmark_config.format_tool_capability_context",
            return_value="<tool-capabilities>\ntools:\n- tool: st\n</tool-capabilities>",
        ) as format_tool_capability_context,
        patch(
            "app.services._benchmark_config._capture_preview_summary",
            new=AsyncMock(return_value={"task_type": "wake", "total_estimated_tokens": 480}),
        ),
    ):
        snapshot = await capture_benchmark_config_snapshot(
            "coder",
            task_type="wake",
            memory_variant_override="MINIMAL",
        )

    assert snapshot["memory_state"]["variant_override"] == "MINIMAL"
    assert snapshot["generated_context"]["consumer_profile"] == "agent_coding"
    assert snapshot["generated_context"]["tool_capabilities"]["enabled"] is False
    assert snapshot["generated_context"]["tool_capabilities"]["content_hash"] is None
    assert format_project_index_context.call_args.kwargs["consumer_profile"] == "agent_coding"
    assert format_tool_capability_context.call_args is None
    assert memory_state_descriptor(snapshot) == "2026-03-12T08:00:00+00:00:42:MINIMAL"


@pytest.mark.asyncio
async def test_capture_benchmark_config_snapshot_skips_inactive_agents() -> None:
    mock_db = AsyncMock()

    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def _session():
        yield mock_db

    with (
        patch("app.services._benchmark_config.async_session", _session),
        patch(
            "app.services._benchmark_config.get_agent_by_slug",
            new=AsyncMock(return_value=None),
        ),
    ):
        snapshot = await capture_benchmark_config_snapshot("worker", task_type="task")

    assert snapshot == {}
    mock_db.scalar.assert_not_called()
