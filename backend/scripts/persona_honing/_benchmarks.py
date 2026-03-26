"""Benchmark execution helpers for persona honing cohorts."""
from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from app.services.agent_benchmark_service import capture_benchmark_config_snapshot
from scripts.completion_review_benchmark_eval import CompletionReviewBenchmarkRun
from scripts.persona_benchmark_eval import PersonaBenchmarkRun
from scripts.persona_honing._models import PersonaMutableState, _IterationConfig
from scripts.persona_honing._state import _capture_persona_mutable_state
from scripts.run_completion_review_model_benchmark import run_completion_review_benchmark
from scripts.run_persona_model_benchmark import run_benchmark


async def _get_config_snapshot(agent_slug: str, benchmark_task_type: str) -> dict[str, Any]:
    snapshot = await capture_benchmark_config_snapshot(agent_slug, task_type=benchmark_task_type)
    return {**snapshot, "benchmark_task_type": benchmark_task_type}


async def _run_cohort_benchmarks(
    *,
    models: list[str],
    case_ids: list[str],
    runs_per_case: int,
    project_id: str,
    working_root: Path,
    timeout_seconds: float | None,
    base_url: str,
    client_id: str,
    use_memory: bool,
    benchmark_task_type: str,
    seed_base: int,
    count: int,
    first_run: PersonaBenchmarkRun | None = None,
) -> list[PersonaBenchmarkRun]:
    """Run `count` benchmark repetitions; optionally prepend an already-executed first_run."""
    runs: list[PersonaBenchmarkRun] = [first_run] if first_run else []
    for offset in range(1 if first_run else 0, count):
        runs.append(await run_benchmark(
            models=models, case_ids=case_ids, runs_per_case=runs_per_case,
            project_id=project_id, working_root=working_root, seed=seed_base + offset,
            timeout_seconds=timeout_seconds, keep_workdirs=False,
            base_url=base_url, client_id=client_id, use_memory=use_memory,
            memory_group_id=f"benchmark:honing:{uuid.uuid4().hex[:8]}",
            task_type=benchmark_task_type,
        ))
    return runs


async def _run_review_cohort_benchmarks(
    *,
    models: list[str],
    case_ids: list[str],
    runs_per_case: int,
    project_id: str,
    timeout_seconds: float | None,
    base_url: str,
    client_id: str,
    use_memory: bool,
    seed_base: int,
    count: int,
    first_run: CompletionReviewBenchmarkRun | None = None,
) -> list[CompletionReviewBenchmarkRun]:
    runs: list[CompletionReviewBenchmarkRun] = [first_run] if first_run else []
    for offset in range(1 if first_run else 0, count):
        runs.append(await run_completion_review_benchmark(
            models=models, case_ids=case_ids, runs_per_case=runs_per_case,
            project_id=project_id, seed=seed_base + offset, timeout_seconds=timeout_seconds,
            base_url=base_url, client_id=client_id, use_memory=use_memory,
        ))
    return runs


async def _run_initial_benchmarks(
    *,
    iteration: int,
    cfg: _IterationConfig,
) -> tuple[PersonaMutableState, PersonaBenchmarkRun, CompletionReviewBenchmarkRun | None, dict[str, Any] | None]:
    """Capture baseline state, run main benchmark, and optionally run the review benchmark."""
    baseline_state = await _capture_persona_mutable_state(cfg["agent_slug"])
    benchmark_run = await run_benchmark(
        models=cfg["models"], case_ids=cfg["case_ids"], runs_per_case=cfg["runs_per_case"],
        project_id=cfg["project_id"], working_root=cfg["working_root"],
        seed=cfg["seed"] + iteration - 1, timeout_seconds=cfg["timeout_seconds"],
        keep_workdirs=False, base_url=cfg["base_url"], client_id=cfg["client_id"],
        use_memory=cfg["use_memory"],
        memory_group_id=f"benchmark:honing:{uuid.uuid4().hex[:8]}",
        task_type=cfg["benchmark_task_type"],
    )
    review_run: CompletionReviewBenchmarkRun | None = None
    review_baseline_config: dict[str, Any] | None = None
    if not cfg["disable_completion_review"] and cfg["reviewer_models"] and cfg["reviewer_case_ids"]:
        review_run = await run_completion_review_benchmark(
            models=cfg["reviewer_models"], case_ids=cfg["reviewer_case_ids"],
            runs_per_case=cfg["reviewer_runs_per_case"], project_id=cfg["project_id"],
            seed=cfg["seed"] + iteration + 4999, timeout_seconds=cfg["timeout_seconds"],
            base_url=cfg["base_url"], client_id=cfg["client_id"], use_memory=cfg["use_memory"],
        )
        review_baseline_config = await _get_config_snapshot(cfg["agent_slug"], "review")
    return baseline_state, benchmark_run, review_run, review_baseline_config
