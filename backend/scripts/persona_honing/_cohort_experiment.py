"""Cohort experiment orchestration: running cohorts, persisting, and evaluating experiments."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

from app.db import async_session
from app.services.agent_benchmark_service import (
    get_benchmark_experiment_summary_by_key,
    summarize_benchmark_experiment,
)
from scripts.completion_review_benchmark_eval import CompletionReviewBenchmarkRun
from scripts.persona_benchmark_eval import PersonaBenchmarkRun
from scripts.persona_benchmark_persistence import build_persistence_payload
from scripts.persona_honing._benchmarks import (
    _get_config_snapshot,
    _run_cohort_benchmarks,
    _run_review_cohort_benchmarks,
)
from scripts.persona_honing._constants import RUN_KIND_HONING_BASELINE, RUN_KIND_HONING_CANDIDATE
from scripts.persona_honing._models import PersonaHoningIteration, _IterationConfig
from scripts.persona_honing._persistence import (
    _persist_review_cohort_pair,
    _persist_runs,
)
from scripts.persona_honing._run_helpers import _cohort_run_summary
from scripts.run_completion_review_model_benchmark import derive_suite_id as derive_review_suite_id


async def _evaluate_experiment(
    *,
    experiment_key: str,
    iteration: int,
    suite_name: str,
    baseline_runs: list[Any],
    candidate_runs: list[Any],
    baseline_config: dict[str, Any],
    candidate_config: dict[str, Any],
    cohort_repetitions: int,
    persist_results: bool,
) -> dict[str, Any]:
    experiment = SimpleNamespace(
        experiment_key=experiment_key,
        name=f"Persona honing iteration {iteration}",
        suite_id=suite_name, status="open",
        hypothesis=f"Candidate self-edit for iteration {iteration} should improve {suite_name}.",
        baseline_label="baseline", candidate_label="candidate",
        min_runs_per_cohort=cohort_repetitions,
        updated_at=datetime.now(UTC), created_at=datetime.now(UTC),
    )
    local_runs = [
        *[_cohort_run_summary(r, cohort="baseline", config_snapshot=dict(baseline_config)) for r in baseline_runs],
        *[_cohort_run_summary(r, cohort="candidate", config_snapshot=dict(candidate_config)) for r in candidate_runs],
    ]
    summary = summarize_benchmark_experiment(experiment, local_runs)
    if not persist_results:
        return summary
    async with async_session() as db:
        persisted = await get_benchmark_experiment_summary_by_key(db, experiment_key)
    return persisted if persisted else summary


async def _run_and_evaluate_main_cohorts(
    *,
    record: PersonaHoningIteration,
    benchmark_run: PersonaBenchmarkRun,
    baseline_config: dict[str, Any],
    suite_name: str,
    iteration: int,
    cfg: _IterationConfig,
) -> tuple[list[PersonaBenchmarkRun], list[PersonaBenchmarkRun], str]:
    """Run cohort benchmarks, generate experiment key, persist if needed, and evaluate."""
    cohort_kw: dict[str, Any] = dict(
        models=cfg["models"], case_ids=cfg["case_ids"], runs_per_case=cfg["runs_per_case"],
        project_id=cfg["project_id"], working_root=cfg["working_root"],
        timeout_seconds=cfg["timeout_seconds"], base_url=cfg["base_url"],
        client_id=cfg["client_id"], use_memory=cfg["use_memory"],
        benchmark_task_type=cfg["benchmark_task_type"], count=cfg["cohort_repetitions"],
    )
    baseline_runs = await _run_cohort_benchmarks(
        **cohort_kw, seed_base=cfg["seed"] + iteration * 100, first_run=benchmark_run,
    )
    candidate_runs = await _run_cohort_benchmarks(
        **cohort_kw, seed_base=cfg["seed"] + iteration * 1000,
    )
    experiment_key = f"persona-honing-{suite_name}-iter-{iteration}-{uuid.uuid4().hex[:8]}"
    record.experiment_key = experiment_key
    candidate_config = await _get_config_snapshot(cfg["agent_slug"], cfg["benchmark_task_type"])
    if cfg["persist_results"]:
        await _persist_main_cohort_runs(
            record=record, baseline_runs=baseline_runs, candidate_runs=candidate_runs,
            experiment_key=experiment_key, suite_name=suite_name,
            baseline_config=baseline_config, candidate_config=candidate_config,
            iteration=iteration, cfg=cfg,
        )
    record.experiment_summary = await _evaluate_experiment(
        experiment_key=experiment_key, iteration=iteration, suite_name=suite_name,
        baseline_runs=baseline_runs, candidate_runs=candidate_runs,
        baseline_config=baseline_config, candidate_config=candidate_config,
        cohort_repetitions=cfg["cohort_repetitions"], persist_results=cfg["persist_results"],
    )
    return baseline_runs, candidate_runs, experiment_key


async def _persist_main_cohort_runs(
    *,
    record: PersonaHoningIteration,
    baseline_runs: list[PersonaBenchmarkRun],
    candidate_runs: list[PersonaBenchmarkRun],
    experiment_key: str,
    suite_name: str,
    baseline_config: dict[str, Any],
    candidate_config: dict[str, Any],
    iteration: int,
    cfg: _IterationConfig,
) -> None:
    shared: dict[str, Any] = dict(
        payload_builder=build_persistence_payload,
        experiment_key=experiment_key, experiment_name=f"Persona honing iteration {iteration}",
        hypothesis=f"Candidate self-edit for iteration {iteration} should improve {suite_name}.",
        suite_id=suite_name, project_id=cfg["project_id"], agent_slug=cfg["agent_slug"],
        use_memory=cfg["use_memory"], min_runs_per_cohort=cfg["cohort_repetitions"],
    )
    record.baseline_run_ids = await _persist_runs(
        baseline_runs, cohort="baseline", run_kind=RUN_KIND_HONING_BASELINE,
        seed_start=cfg["seed"] + iteration * 100, config_snapshot=baseline_config, **shared,
    )
    record.candidate_run_ids = await _persist_runs(
        candidate_runs, cohort="candidate", run_kind=RUN_KIND_HONING_CANDIDATE,
        seed_start=cfg["seed"] + iteration * 1000, config_snapshot=candidate_config, **shared,
    )


async def _run_review_cohort_experiment(
    *,
    record: PersonaHoningIteration,
    review_run: CompletionReviewBenchmarkRun,
    review_baseline_config: dict[str, Any],
    experiment_key: str,
    iteration: int,
    cfg: _IterationConfig,
) -> tuple[list[CompletionReviewBenchmarkRun], list[CompletionReviewBenchmarkRun], dict[str, Any] | None]:
    """Run review cohort benchmarks, optionally persist, evaluate, and mutate record."""
    review_suite_name = derive_review_suite_id(cfg["reviewer_case_ids"])
    common: dict[str, Any] = dict(
        models=cfg["reviewer_models"], case_ids=cfg["reviewer_case_ids"],
        runs_per_case=cfg["reviewer_runs_per_case"], project_id=cfg["project_id"],
        timeout_seconds=cfg["timeout_seconds"], base_url=cfg["base_url"],
        client_id=cfg["client_id"], use_memory=cfg["use_memory"], count=cfg["cohort_repetitions"],
    )
    review_baseline_runs = await _run_review_cohort_benchmarks(
        **common, seed_base=cfg["seed"] + iteration * 10000, first_run=review_run,
    )
    review_candidate_runs = await _run_review_cohort_benchmarks(
        **common, seed_base=cfg["seed"] + iteration * 20000,
    )
    review_experiment_key = (
        f"persona-honing-review-{review_suite_name}-iter-{iteration}-{uuid.uuid4().hex[:8]}"
    )
    record.review_experiment_key = review_experiment_key
    review_candidate_config = await _get_config_snapshot(cfg["agent_slug"], "review")
    if cfg["persist_results"]:
        await _persist_review_cohort_pair(
            record=record, review_baseline_runs=review_baseline_runs,
            review_candidate_runs=review_candidate_runs,
            review_experiment_key=review_experiment_key, review_suite_name=review_suite_name,
            review_baseline_config=review_baseline_config,
            review_candidate_config=review_candidate_config, iteration=iteration, cfg=cfg,
        )
    review_summary = await _evaluate_experiment(
        experiment_key=review_experiment_key, iteration=iteration, suite_name=review_suite_name,
        baseline_runs=review_baseline_runs, candidate_runs=review_candidate_runs,
        baseline_config=review_baseline_config, candidate_config=review_candidate_config,
        cohort_repetitions=cfg["cohort_repetitions"], persist_results=cfg["persist_results"],
    )
    record.review_experiment_summary = review_summary
    return review_baseline_runs, review_candidate_runs, review_summary


async def _maybe_run_review_cohorts(
    *,
    record: PersonaHoningIteration,
    review_run: CompletionReviewBenchmarkRun | None,
    review_baseline_config: dict[str, Any] | None,
    experiment_key: str,
    iteration: int,
    cfg: _IterationConfig,
) -> tuple[list[CompletionReviewBenchmarkRun], list[CompletionReviewBenchmarkRun], dict[str, Any] | None]:
    """Run review cohorts only when enabled and review data is available."""
    if (
        cfg["disable_completion_review"]
        or review_run is None
        or not cfg["reviewer_models"]
        or not cfg["reviewer_case_ids"]
        or review_baseline_config is None
    ):
        return [], [], None
    return await _run_review_cohort_experiment(
        record=record, review_run=review_run, review_baseline_config=review_baseline_config,
        experiment_key=experiment_key, iteration=iteration, cfg=cfg,
    )
