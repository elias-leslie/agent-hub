"""Tests for controlled benchmark experiment comparison logic."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

from app.services.agent_benchmark_service import summarize_benchmark_experiment


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
