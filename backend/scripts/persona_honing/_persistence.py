"""Persistence helpers for persona honing benchmark runs."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.services.agent_benchmark_service import persist_benchmark_payload
from scripts.completion_review_benchmark_eval import CompletionReviewBenchmarkRun
from scripts.persona_benchmark_eval import PersonaBenchmarkRun
from scripts.persona_benchmark_persistence import build_persistence_payload
from scripts.persona_honing._constants import (
    RUN_KIND_HONING_BASELINE,
    RUN_KIND_HONING_CANDIDATE,
    RUN_KIND_HONING_ITERATION,
)
from scripts.persona_honing._models import PersonaHoningIteration, _IterationConfig
from scripts.run_completion_review_model_benchmark import (
    build_persistence_payload as build_review_persistence_payload,
)


async def _persist_runs(
    runs: list[Any],
    *,
    payload_builder: Callable[..., Any],
    cohort: str,
    experiment_key: str,
    experiment_name: str,
    hypothesis: str,
    suite_id: str,
    project_id: str,
    agent_slug: str,
    use_memory: bool,
    seed_start: int,
    run_kind: str,
    min_runs_per_cohort: int,
    config_snapshot: dict[str, Any],
    metadata_extra: Callable[[Any], dict[str, Any]] | None = None,
) -> list[str]:
    """Persist a list of benchmark runs under a shared experiment definition."""
    run_ids: list[str] = []
    experiment = {
        "experiment_key": experiment_key, "name": experiment_name, "cohort": cohort,
        "hypothesis": hypothesis, "suite_id": suite_id, "project_id": project_id,
        "min_runs_per_cohort": min_runs_per_cohort,
    }
    for offset, run in enumerate(runs):
        meta: dict[str, Any] = {"honing_cohort": cohort}
        if metadata_extra:
            meta.update(metadata_extra(run))
        payload = payload_builder(
            run, agent_slug=agent_slug, suite_id=suite_id, run_kind=run_kind,
            use_memory=use_memory, seed=seed_start + offset,
            config_snapshot=dict(config_snapshot), metadata=meta, experiment=experiment,
        )
        run_ids.append(await persist_benchmark_payload(payload))
    return run_ids


def _review_run_metadata(run: Any) -> dict[str, Any]:
    return {"reviewer_role": True, "reviewer_agent_slug": "supervisor", "reviewer_models": list(run.models)}


async def _persist_review_cohort_pair(
    *,
    record: PersonaHoningIteration,
    review_baseline_runs: list[CompletionReviewBenchmarkRun],
    review_candidate_runs: list[CompletionReviewBenchmarkRun],
    review_experiment_key: str,
    review_suite_name: str,
    review_baseline_config: dict[str, Any],
    review_candidate_config: dict[str, Any],
    iteration: int,
    cfg: _IterationConfig,
) -> None:
    shared = dict(
        payload_builder=build_review_persistence_payload,
        metadata_extra=_review_run_metadata,
        experiment_key=review_experiment_key,
        experiment_name=f"Persona completion-review honing iteration {iteration}",
        hypothesis=(
            f"Candidate self-edit for iteration {iteration} should improve "
            f"completion-review benchmark {review_suite_name}."
        ),
        suite_id=review_suite_name, project_id=cfg["project_id"], agent_slug=cfg["agent_slug"],
        use_memory=cfg["use_memory"], min_runs_per_cohort=cfg["cohort_repetitions"],
    )
    record.review_baseline_run_ids = await _persist_runs(
        review_baseline_runs, cohort="baseline", run_kind=RUN_KIND_HONING_BASELINE,
        seed_start=cfg["seed"] + iteration * 10000, config_snapshot=review_baseline_config, **shared,
    )
    record.review_candidate_run_ids = await _persist_runs(
        review_candidate_runs, cohort="candidate", run_kind=RUN_KIND_HONING_CANDIDATE,
        seed_start=cfg["seed"] + iteration * 20000, config_snapshot=review_candidate_config, **shared,
    )


async def _persist_iteration_record(
    *,
    record: PersonaHoningIteration,
    benchmark_run: PersonaBenchmarkRun,
    config_snapshot: dict[str, Any],
    suite_name: str,
    agent_slug: str,
    use_memory: bool,
    seed: int,
    iteration: int,
    report_path: str,
    failure_clusters: list[dict[str, Any]],
    persistent_clusters: list[dict[str, Any]],
    stop_reason: str | None,
    persist_results: bool,
) -> None:
    if not persist_results:
        return
    metadata: dict[str, Any] = {
        "iteration": iteration,
        "benchmark_report_path": report_path,
        "source_benchmark_id": benchmark_run.benchmark_id,
        "failure_clusters": failure_clusters,
        "persistent_failure_clusters": persistent_clusters,
        "improvement": None,
    }
    if record.review_benchmark_id or record.review_failure_clusters is not None:
        metadata["review_surface"] = {
            "benchmark_id": record.review_benchmark_id,
            "top_model": record.review_top_model,
            "top_score": record.review_top_score,
            "failing_attempts": record.review_failing_attempts,
            "failure_clusters": record.review_failure_clusters,
            "persistent_failure_clusters": record.review_persistent_failure_clusters,
            "experiment_key": record.review_experiment_key,
            "experiment_summary": record.review_experiment_summary,
        }
    if stop_reason:
        metadata["stop_reason"] = stop_reason
    payload = build_persistence_payload(
        benchmark_run, agent_slug=agent_slug, suite_id=suite_name,
        run_kind=RUN_KIND_HONING_ITERATION, use_memory=use_memory, seed=seed,
        config_snapshot=config_snapshot, metadata=metadata,
    )
    payload["benchmark_id"] = f"{benchmark_run.benchmark_id}-iter-{iteration}"
    record.persisted_run_id = await persist_benchmark_payload(payload)
