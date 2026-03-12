"""Cohort experiment helpers and per-iteration logic for the Jenny honing loop."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from agent_hub import AsyncAgentHubClient

from app.db import async_session
from app.services.agent_benchmark_service import (
    capture_benchmark_config_snapshot,
    get_benchmark_experiment_summary_by_key,
    persist_benchmark_payload,
    summarize_benchmark_experiment,
)
from scripts.jenny_benchmark_eval import (
    JennyBenchmarkAttempt,
    JennyBenchmarkRun,
    summarize_attempts,
)
from scripts.jenny_benchmark_report import generate_markdown_report
from scripts.jenny_honing._clusters import _diff_failure_clusters, _group_failures
from scripts.jenny_honing._constants import (
    DECISION_PROMOTE,
    RUN_KIND_HONING_BASELINE,
    RUN_KIND_HONING_CANDIDATE,
    RUN_KIND_HONING_ITERATION,
)
from scripts.jenny_honing._models import JennyHoningIteration, JennyMutableState, _LoopState
from scripts.jenny_honing._prompt import (
    _HONING_RESPONSE_SCHEMA,
    _parse_improvement_content,
    build_honing_prompt,
)
from scripts.jenny_honing._state import _capture_jenny_mutable_state, _restore_jenny_mutable_state
from scripts.run_jenny_model_benchmark import (
    _fetch_used_tool_names,
    build_persistence_payload,
    derive_suite_id,
    run_benchmark,
)


def _merge_runs(runs: list[JennyBenchmarkRun], *, benchmark_id: str) -> JennyBenchmarkRun:
    if not runs:
        raise ValueError("Cannot merge empty benchmark run list")
    attempts: list[JennyBenchmarkAttempt] = []
    models: list[str] = []
    case_ids: list[str] = []
    for run in runs:
        attempts.extend(run.attempts)
        for model_id in run.models:
            if model_id not in models:
                models.append(model_id)
        for case_id in run.case_ids:
            if case_id not in case_ids:
                case_ids.append(case_id)
    return JennyBenchmarkRun(
        benchmark_id=benchmark_id,
        project_id=runs[0].project_id,
        models=models,
        case_ids=case_ids,
        runs_per_case=sum(run.runs_per_case for run in runs),
        started_at=runs[0].started_at,
        completed_at=runs[-1].completed_at,
        attempts=attempts,
        summaries=summarize_attempts(attempts),
    )


def _cohort_run_summary(
    run: JennyBenchmarkRun,
    *,
    cohort: str,
    config_snapshot: dict[str, Any],
) -> SimpleNamespace:
    attempt_count = len(run.attempts)
    passed_count = sum(1 for a in run.attempts if a.passed)
    avg_score = (sum(float(a.composite_score) for a in run.attempts) / attempt_count) if attempt_count else 0.0
    pass_rate = ((passed_count / attempt_count) * 100) if attempt_count else 0.0
    return SimpleNamespace(
        experiment_cohort=cohort,
        avg_score=avg_score,
        pass_rate=pass_rate,
        config_snapshot=config_snapshot,
        completed_at=datetime.fromisoformat(run.completed_at.replace("Z", "+00:00")),
    )


async def _persist_cohort_runs(
    *,
    runs: list[JennyBenchmarkRun],
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
) -> list[str]:
    run_ids: list[str] = []
    for offset, run in enumerate(runs):
        payload = build_persistence_payload(
            run,
            agent_slug=agent_slug,
            suite_id=suite_id,
            run_kind=run_kind,
            use_memory=use_memory,
            seed=seed_start + offset,
            config_snapshot=dict(config_snapshot),
            metadata={"honing_cohort": cohort},
            experiment={
                "experiment_key": experiment_key,
                "name": experiment_name,
                "cohort": cohort,
                "hypothesis": hypothesis,
                "suite_id": suite_id,
                "project_id": project_id,
                "min_runs_per_cohort": min_runs_per_cohort,
            },
        )
        run_ids.append(await persist_benchmark_payload(payload))
    return run_ids


async def _run_improvement_pass(
    *,
    client: AsyncAgentHubClient,
    project_id: str,
    iteration: int,
    run: JennyBenchmarkRun,
    previous_clusters: list[dict[str, Any]] | None,
    timeout_seconds: float,
    working_root: Path,
) -> tuple[str | None, str, list[str], dict[str, Any] | None]:
    """Prompt Jenny to improve herself based on benchmark failures."""
    response = await client.complete(
        messages=[{"role": "user", "content": build_honing_prompt(run, iteration, previous_clusters)}],
        project_id=project_id,
        agent_slug="persona",
        external_id=f"jenny-honing:{run.benchmark_id}:iteration-{iteration}",
        enable_caching=False,
        skip_cache=True,
        use_memory=False,
        max_turns=12,
        working_dir=str(working_root),
        execute_tools=True,
        timeout_seconds=timeout_seconds,
        response_format={"type": "json_object", "schema": _HONING_RESPONSE_SCHEMA},
    )
    used_tools = await _fetch_used_tool_names(response.session_id)
    return response.session_id, response.content, used_tools, _parse_improvement_content(response.content)


def _write_iteration_report(output_dir: Path, run: JennyBenchmarkRun, iteration: int) -> str:
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / f"iteration-{iteration:02d}-{run.benchmark_id}.md"
    report_path.write_text(generate_markdown_report(run))
    return str(report_path)


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
    timeout_seconds: float,
    base_url: str,
    client_id: str,
    use_memory: bool,
    benchmark_task_type: str,
    seed_base: int,
    count: int,
    first_run: JennyBenchmarkRun | None = None,
) -> list[JennyBenchmarkRun]:
    """Run `count` benchmark repetitions; optionally prepend an already-executed first_run."""
    runs: list[JennyBenchmarkRun] = [first_run] if first_run else []
    start_offset = 1 if first_run else 0
    for offset in range(start_offset, count):
        runs.append(await run_benchmark(
            models=models,
            case_ids=case_ids,
            runs_per_case=runs_per_case,
            project_id=project_id,
            working_root=working_root,
            seed=seed_base + offset,
            timeout_seconds=timeout_seconds,
            keep_workdirs=False,
            base_url=base_url,
            client_id=client_id,
            use_memory=use_memory,
            memory_group_id=f"benchmark:honing:{uuid.uuid4().hex[:8]}",
            task_type=benchmark_task_type,
        ))
    return runs


async def _evaluate_experiment(
    *,
    experiment_key: str,
    iteration: int,
    suite_name: str,
    baseline_runs: list[JennyBenchmarkRun],
    candidate_runs: list[JennyBenchmarkRun],
    baseline_config: dict[str, Any],
    candidate_config: dict[str, Any],
    cohort_repetitions: int,
    persist_results: bool,
) -> dict[str, Any]:
    name = f"Jenny honing iteration {iteration}"
    hypothesis = f"Candidate self-edit for iteration {iteration} should improve {suite_name}."
    experiment = SimpleNamespace(
        experiment_key=experiment_key,
        name=name,
        suite_id=suite_name,
        status="open",
        hypothesis=hypothesis,
        baseline_label="baseline",
        candidate_label="candidate",
        min_runs_per_cohort=cohort_repetitions,
        updated_at=datetime.now(UTC),
        created_at=datetime.now(UTC),
    )
    local_runs = [
        *[_cohort_run_summary(r, cohort="baseline", config_snapshot=dict(baseline_config)) for r in baseline_runs],
        *[_cohort_run_summary(r, cohort="candidate", config_snapshot=dict(candidate_config)) for r in candidate_runs],
    ]
    summary = summarize_benchmark_experiment(experiment, local_runs)
    if persist_results:
        async with async_session() as db:
            persisted = await get_benchmark_experiment_summary_by_key(db, experiment_key)
        if persisted:
            summary = persisted
    return summary


def _update_loop_state_from_merged(
    loop_state: _LoopState,
    merged: JennyBenchmarkRun,
    record: JennyHoningIteration,
) -> None:
    loop_state.previous_best_score = (
        merged.summaries[0].avg_composite_score if merged.summaries else record.top_score
    )
    loop_state.previous_failing_attempts = sum(1 for a in merged.attempts if not a.passed)
    loop_state.previous_clusters = _group_failures(merged.attempts)


async def _run_experiment_and_decide(
    *,
    iteration: int,
    record: JennyHoningIteration,
    benchmark_run: JennyBenchmarkRun,
    baseline_state: JennyMutableState,
    loop_state: _LoopState,
    suite_name: str,
    baseline_config: dict[str, Any],
    client: AsyncAgentHubClient,
    project_id: str,
    agent_slug: str,
    models: list[str],
    case_ids: list[str],
    runs_per_case: int,
    working_root: Path,
    timeout_seconds: float,
    base_url: str,
    client_id: str,
    use_memory: bool,
    benchmark_task_type: str,
    seed: int,
    cohort_repetitions: int,
    persist_results: bool,
) -> None:
    """Run improvement pass + cohort experiments + decide promote/rollback; mutates record and loop_state."""
    session_id, content, tools, parsed = await _run_improvement_pass(
        client=client,
        project_id=project_id,
        iteration=iteration,
        run=benchmark_run,
        previous_clusters=loop_state.previous_clusters,
        timeout_seconds=timeout_seconds,
        working_root=working_root,
    )
    record.improvement_session_id = session_id
    record.improvement_content = content
    record.improvement_tools = tools
    record.improvement_parsed = parsed

    baseline_runs = await _run_cohort_benchmarks(
        models=models, case_ids=case_ids, runs_per_case=runs_per_case,
        project_id=project_id, working_root=working_root, timeout_seconds=timeout_seconds,
        base_url=base_url, client_id=client_id, use_memory=use_memory,
        benchmark_task_type=benchmark_task_type,
        seed_base=seed + iteration * 100, count=cohort_repetitions, first_run=benchmark_run,
    )
    candidate_runs = await _run_cohort_benchmarks(
        models=models, case_ids=case_ids, runs_per_case=runs_per_case,
        project_id=project_id, working_root=working_root, timeout_seconds=timeout_seconds,
        base_url=base_url, client_id=client_id, use_memory=use_memory,
        benchmark_task_type=benchmark_task_type,
        seed_base=seed + iteration * 1000, count=cohort_repetitions,
    )

    experiment_key = f"jenny-honing-{suite_name}-iter-{iteration}-{uuid.uuid4().hex[:8]}"
    record.experiment_key = experiment_key
    candidate_config = await _get_config_snapshot(agent_slug, benchmark_task_type)

    if persist_results:
        shared = dict(
            experiment_key=experiment_key,
            experiment_name=f"Jenny honing iteration {iteration}",
            hypothesis=f"Candidate self-edit for iteration {iteration} should improve {suite_name}.",
            suite_id=suite_name, project_id=project_id, agent_slug=agent_slug,
            use_memory=use_memory, min_runs_per_cohort=cohort_repetitions,
        )
        record.baseline_run_ids = await _persist_cohort_runs(
            runs=baseline_runs, cohort="baseline", run_kind=RUN_KIND_HONING_BASELINE,
            seed_start=seed + iteration * 100, config_snapshot=baseline_config, **shared,
        )
        record.candidate_run_ids = await _persist_cohort_runs(
            runs=candidate_runs, cohort="candidate", run_kind=RUN_KIND_HONING_CANDIDATE,
            seed_start=seed + iteration * 1000, config_snapshot=candidate_config, **shared,
        )

    experiment_summary = await _evaluate_experiment(
        experiment_key=experiment_key, iteration=iteration, suite_name=suite_name,
        baseline_runs=baseline_runs, candidate_runs=candidate_runs,
        baseline_config=baseline_config, candidate_config=candidate_config,
        cohort_repetitions=cohort_repetitions, persist_results=persist_results,
    )
    record.experiment_summary = experiment_summary

    decision = experiment_summary["decision"]
    if decision != DECISION_PROMOTE:
        await _restore_jenny_mutable_state(
            agent_slug, baseline_state,
            reason=f"Reverted non-promoted honing candidate iteration {iteration}",
        )
        record.rollback_applied = True
        merged = _merge_runs(baseline_runs, benchmark_id=f"{experiment_key}-baseline-merged")
    else:
        merged = _merge_runs(candidate_runs, benchmark_id=f"{experiment_key}-candidate-merged")

    _update_loop_state_from_merged(loop_state, merged, record)
    loop_state.honed = (decision == DECISION_PROMOTE and loop_state.previous_failing_attempts == 0)


async def _persist_iteration_record(
    *,
    record: JennyHoningIteration,
    benchmark_run: JennyBenchmarkRun,
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
        "failure_clusters": failure_clusters,
        "persistent_failure_clusters": persistent_clusters,
        "improvement": None,
    }
    if stop_reason:
        metadata["stop_reason"] = stop_reason
    payload = build_persistence_payload(
        benchmark_run,
        agent_slug=agent_slug,
        suite_id=suite_name,
        run_kind=RUN_KIND_HONING_ITERATION,
        use_memory=use_memory,
        seed=seed,
        config_snapshot=config_snapshot,
        metadata=metadata,
    )
    record.persisted_run_id = await persist_benchmark_payload(payload)


def _build_iteration_record(
    iteration: int,
    benchmark_run: JennyBenchmarkRun,
    report_path: str,
    loop_state: _LoopState,
) -> JennyHoningIteration:
    failure_clusters = _group_failures(benchmark_run.attempts)
    persistent_clusters, _, _ = _diff_failure_clusters(loop_state.previous_clusters, failure_clusters)
    top_summary = benchmark_run.summaries[0] if benchmark_run.summaries else None
    return JennyHoningIteration(
        iteration=iteration,
        benchmark_id=benchmark_run.benchmark_id,
        top_model=top_summary.model_id if top_summary else None,
        top_score=top_summary.avg_composite_score if top_summary else 0.0,
        failing_attempts=sum(1 for a in benchmark_run.attempts if not a.passed),
        benchmark_report_path=report_path,
        failure_clusters=failure_clusters,
        persistent_failure_clusters=persistent_clusters,
    )


async def _run_iteration(
    *,
    iteration: int,
    loop_state: _LoopState,
    client: AsyncAgentHubClient,
    suite_id: str | None,
    models: list[str],
    case_ids: list[str],
    runs_per_case: int,
    project_id: str,
    working_root: Path,
    output_dir: Path,
    seed: int,
    timeout_seconds: float,
    client_id: str,
    use_memory: bool,
    benchmark_task_type: str,
    cohort_repetitions: int,
    base_url: str,
    agent_slug: str,
    persist_results: bool,
) -> bool:
    """Execute one benchmark + improvement cycle. Returns True if the loop should stop."""
    import uuid as _uuid

    baseline_state = await _capture_jenny_mutable_state(agent_slug)
    benchmark_run = await run_benchmark(
        models=models, case_ids=case_ids, runs_per_case=runs_per_case, project_id=project_id,
        working_root=working_root, seed=seed + iteration - 1, timeout_seconds=timeout_seconds,
        keep_workdirs=False, base_url=base_url, client_id=client_id, use_memory=use_memory,
        memory_group_id=f"benchmark:honing:{_uuid.uuid4().hex[:8]}", task_type=benchmark_task_type,
    )
    report_path = _write_iteration_report(output_dir, benchmark_run, iteration)
    baseline_config = await _get_config_snapshot(agent_slug, benchmark_task_type)
    suite_name = suite_id or derive_suite_id(case_ids)
    record = _build_iteration_record(iteration, benchmark_run, report_path, loop_state)

    persist_kw: dict[str, Any] = dict(
        record=record, benchmark_run=benchmark_run, config_snapshot=baseline_config,
        suite_name=suite_name, agent_slug=agent_slug, use_memory=use_memory,
        seed=seed + iteration - 1, iteration=iteration, report_path=report_path,
        failure_clusters=record.failure_clusters or [],
        persistent_clusters=record.persistent_failure_clusters or [],
        persist_results=persist_results,
    )
    if record.failing_attempts == 0:
        await _persist_iteration_record(stop_reason=None, **persist_kw)
        loop_state.iterations.append(record)
        loop_state.honed = True
        return True

    no_improvement = (
        loop_state.previous_best_score is not None
        and loop_state.previous_failing_attempts is not None
        and record.top_score <= loop_state.previous_best_score
        and record.failing_attempts >= loop_state.previous_failing_attempts
    )
    if no_improvement:
        await _persist_iteration_record(stop_reason="no_improvement", **persist_kw)
        loop_state.iterations.append(record)
        return True

    await _run_experiment_and_decide(
        iteration=iteration, record=record, benchmark_run=benchmark_run,
        baseline_state=baseline_state, loop_state=loop_state,
        suite_name=suite_name, baseline_config=baseline_config, client=client,
        project_id=project_id, agent_slug=agent_slug, models=models, case_ids=case_ids,
        runs_per_case=runs_per_case, working_root=working_root, timeout_seconds=timeout_seconds,
        base_url=base_url, client_id=client_id, use_memory=use_memory,
        benchmark_task_type=benchmark_task_type, seed=seed,
        cohort_repetitions=cohort_repetitions, persist_results=persist_results,
    )
    loop_state.iterations.append(record)
    return loop_state.honed
