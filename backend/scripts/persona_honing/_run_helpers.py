"""Benchmark run helpers: merging, counting, and summary helpers."""
from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from typing import Any

from scripts.completion_review_benchmark_eval import (
    CompletionReviewBenchmarkRun,
    summarize_completion_review_attempts,
)
from scripts.persona_benchmark_eval import PersonaBenchmarkRun, summarize_attempts


def _count_failures(run: Any) -> int:
    return sum(1 for a in run.attempts if not a.passed)


def _cohort_run_summary(run: Any, *, cohort: str, config_snapshot: dict[str, Any]) -> SimpleNamespace:
    count = len(run.attempts)
    passed = sum(1 for a in run.attempts if a.passed)
    return SimpleNamespace(
        experiment_cohort=cohort,
        avg_score=(sum(float(a.composite_score) for a in run.attempts) / count) if count else 0.0,
        pass_rate=((passed / count) * 100) if count else 0.0,
        config_snapshot=config_snapshot,
        completed_at=datetime.fromisoformat(run.completed_at.replace("Z", "+00:00")),
    )


def _merge_benchmark_runs(runs: list[Any], *, benchmark_id: str, summarize_fn: Any) -> Any:
    """Generic run merger for PersonaBenchmarkRun and CompletionReviewBenchmarkRun."""
    if not runs:
        raise ValueError("Cannot merge empty benchmark run list")
    attempts: list[Any] = []
    models: list[str] = []
    case_ids: list[str] = []
    for run in runs:
        attempts.extend(run.attempts)
        for m in run.models:
            if m not in models:
                models.append(m)
        for c in run.case_ids:
            if c not in case_ids:
                case_ids.append(c)
    return type(runs[0])(
        benchmark_id=benchmark_id, project_id=runs[0].project_id, models=models,
        case_ids=case_ids, runs_per_case=sum(r.runs_per_case for r in runs),
        started_at=runs[0].started_at, completed_at=runs[-1].completed_at,
        attempts=attempts, summaries=summarize_fn(attempts),
    )


def _merge_runs(runs: list[PersonaBenchmarkRun], *, benchmark_id: str) -> PersonaBenchmarkRun:
    return _merge_benchmark_runs(  # type: ignore[return-value]
        runs, benchmark_id=benchmark_id, summarize_fn=summarize_attempts,
    )


def _merge_review_runs(
    runs: list[CompletionReviewBenchmarkRun], *, benchmark_id: str,
) -> CompletionReviewBenchmarkRun:
    return _merge_benchmark_runs(  # type: ignore[return-value]
        runs, benchmark_id=benchmark_id, summarize_fn=summarize_completion_review_attempts,
    )
