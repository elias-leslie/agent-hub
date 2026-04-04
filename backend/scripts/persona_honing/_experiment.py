"""Cohort experiment helpers and per-iteration logic for the persona honing loop."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_hub import AsyncAgentHubClient

from app.services.agent_benchmark_service import get_benchmark_experiment_summary_by_key
from app.services.persona_prompt_service import render_persona_improvement_decision_review_prompt
from scripts.completion_review_benchmark_eval import CompletionReviewBenchmarkRun
from scripts.persona_benchmark_eval import PersonaBenchmarkRun
from scripts.persona_benchmark_report import generate_markdown_report
from scripts.persona_benchmark_runner import _fetch_used_tool_names
from scripts.persona_honing import _cohort_experiment as _cohort_experiment_module
from scripts.persona_honing._benchmarks import _get_config_snapshot, _run_initial_benchmarks
from scripts.persona_honing._constants import DECISION_PROMOTE
from scripts.persona_honing._decision import (
    _determine_final_experiment_decision,
    _persist_final_experiment_decision,
)
from scripts.persona_honing._formatting import (
    _format_experiment_summary_block,
    _format_improvement_summary_block,
)
from scripts.persona_honing._improvement import _build_improvement_prompt
from scripts.persona_honing._iteration_record import (
    _apply_decision_to_loop_state,
    _build_iteration_record,
    _is_stalled,
)
from scripts.persona_honing._models import (
    PersonaHoningIteration,
    PersonaMutableState,
    _IterationConfig,
    _LoopState,
)
from scripts.persona_honing._persistence import _persist_iteration_record
from scripts.persona_honing._response import (
    _HONING_RESPONSE_SCHEMA,
    parse_decision_review_content,
    parse_improvement_content,
)
from scripts.persona_honing._signals import _load_field_snapshot, _load_recent_improvement_signals
from scripts.persona_honing._state import _restore_persona_mutable_state
from scripts.run_persona_model_benchmark import derive_suite_id

# Re-export public API consumed by external callers
__all__ = [
    "_build_improvement_prompt",
    "_fetch_used_tool_names",
    "_load_recent_improvement_signals",
    "_maybe_run_review_cohorts",
    "_run_and_evaluate_main_cohorts",
    "_run_decision_review",
    "_run_improvement_pass",
    "_run_iteration",
    "get_benchmark_experiment_summary_by_key",
    "render_persona_improvement_decision_review_prompt",
]


def _write_iteration_report(output_dir: Path, run: PersonaBenchmarkRun, iteration: int) -> str:
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / f"iteration-{iteration:02d}-{run.benchmark_id}.md"
    report_path.write_text(generate_markdown_report(run))
    return str(report_path)


async def _run_improvement_pass(
    *,
    client: AsyncAgentHubClient,
    project_id: str,
    iteration: int,
    run: PersonaBenchmarkRun,
    previous_clusters: list[dict[str, Any]] | None,
    review_run: CompletionReviewBenchmarkRun | None,
    previous_review_clusters: list[dict[str, Any]] | None,
    timeout_seconds: float | None,
    working_root: Path,
) -> tuple[str | None, str, list[str], dict[str, Any] | None]:
    """Prompt the persona to improve itself based on benchmark failures."""
    from app.services.persona_improvement import build_persona_heartbeat_field_digest

    improvement_signals = await _load_recent_improvement_signals(project_id)
    field_signals = await build_persona_heartbeat_field_digest()
    prompt = await _build_improvement_prompt(
        run=run,
        iteration=iteration,
        previous_clusters=previous_clusters,
        review_run=review_run,
        previous_review_clusters=previous_review_clusters,
        improvement_signals=improvement_signals,
        field_signals=field_signals,
    )
    response = await client.complete(
        messages=[{"role": "user", "content": prompt}],
        project_id=project_id,
        agent_slug="persona",
        external_id=f"persona-honing:{run.benchmark_id}:iteration-{iteration}",
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
    return (
        response.session_id,
        response.content,
        used_tools,
        parse_improvement_content(response.content),
    )


async def _run_decision_review(
    *,
    client: AsyncAgentHubClient,
    iteration: int,
    experiment_key: str,
    project_id: str,
    timeout_seconds: float | None,
    working_root: Path,
    proposed_decision: str,
    proposed_reason: str,
    experiment_summary: dict[str, Any],
    review_summary: dict[str, Any] | None,
    field_snapshot: dict[str, Any] | None,
    record: PersonaHoningIteration,
) -> dict[str, Any]:
    """Run the supervisor review prompt for a honing experiment decision."""
    from app.services.persona_improvement import build_persona_heartbeat_field_digest

    prompt = await render_persona_improvement_decision_review_prompt(
        proposed_decision=proposed_decision,
        proposed_reason=proposed_reason,
        experiment_summary_block=_format_experiment_summary_block(experiment_summary),
        completion_review_block=_format_experiment_summary_block(review_summary),
        field_signals_block=await build_persona_heartbeat_field_digest(),
        improvement_summary_block=_format_improvement_summary_block(record),
    )
    try:
        response = await client.complete(
            messages=[{"role": "user", "content": prompt}],
            project_id=project_id,
            agent_slug="supervisor",
            external_id=f"persona-honing-review:{experiment_key}:iteration-{iteration}",
            enable_caching=False,
            skip_cache=True,
            use_memory=False,
            max_turns=1,
            working_dir=str(working_root),
            execute_tools=False,
            timeout_seconds=timeout_seconds,
        )
    except Exception as exc:
        return {
            "used": False,
            "session_id": None,
            "decision": None,
            "reason": f"review_unavailable:{type(exc).__name__}",
        }

    parsed = parse_decision_review_content(response.content)
    if parsed is None:
        return {
            "used": False,
            "session_id": response.session_id,
            "decision": None,
            "reason": "review_unparseable",
            "raw_content": response.content,
        }
    return {
        "used": True,
        "session_id": response.session_id,
        "decision": parsed["decision"],
        "reason": parsed["reason"],
        "raw_content": response.content,
        "field_gate": dict((field_snapshot or {}).get("review_gate") or {}),
    }


async def _run_and_evaluate_main_cohorts(
    **kwargs: Any,
) -> tuple[list[PersonaBenchmarkRun], list[PersonaBenchmarkRun], str]:
    """Delegate to the cohort module with legacy patch points preserved."""
    original = _cohort_experiment_module.get_benchmark_experiment_summary_by_key
    _cohort_experiment_module.get_benchmark_experiment_summary_by_key = (
        get_benchmark_experiment_summary_by_key
    )
    try:
        return await _cohort_experiment_module._run_and_evaluate_main_cohorts(**kwargs)
    finally:
        _cohort_experiment_module.get_benchmark_experiment_summary_by_key = original


async def _maybe_run_review_cohorts(
    **kwargs: Any,
) -> tuple[list[CompletionReviewBenchmarkRun], list[CompletionReviewBenchmarkRun], dict[str, Any] | None]:
    """Delegate to the cohort module with legacy patch points preserved."""
    original = _cohort_experiment_module.get_benchmark_experiment_summary_by_key
    _cohort_experiment_module.get_benchmark_experiment_summary_by_key = (
        get_benchmark_experiment_summary_by_key
    )
    try:
        return await _cohort_experiment_module._maybe_run_review_cohorts(**kwargs)
    finally:
        _cohort_experiment_module.get_benchmark_experiment_summary_by_key = original


async def _apply_improvement_pass(
    record: PersonaHoningIteration,
    *,
    benchmark_run: PersonaBenchmarkRun,
    review_run: CompletionReviewBenchmarkRun | None,
    iteration: int,
    loop_state: _LoopState,
    client: AsyncAgentHubClient,
    cfg: _IterationConfig,
) -> None:
    session_id, content, tools, parsed = await _run_improvement_pass(
        client=client, project_id=cfg["project_id"], iteration=iteration, run=benchmark_run,
        previous_clusters=loop_state.previous_clusters, review_run=review_run,
        previous_review_clusters=loop_state.previous_review_clusters,
        timeout_seconds=cfg["timeout_seconds"], working_root=cfg["working_root"],
    )
    record.improvement_session_id = session_id
    record.improvement_content = content
    record.improvement_tools = tools
    record.improvement_parsed = parsed


async def _resolve_experiment_decision(
    *,
    final_decision: str,
    final_decision_reason: str,
    final_decision_source: str,
    baseline_state: PersonaMutableState,
    agent_slug: str,
    iteration: int,
    experiment_key: str,
    baseline_runs: list[PersonaBenchmarkRun],
    candidate_runs: list[PersonaBenchmarkRun],
    review_baseline_runs: list[CompletionReviewBenchmarkRun],
    review_candidate_runs: list[CompletionReviewBenchmarkRun],
    record: PersonaHoningIteration,
    loop_state: _LoopState,
) -> None:
    """Apply promote/rollback decision, merge winning runs, update loop state."""
    should_rollback = final_decision != DECISION_PROMOTE
    record.final_decision = final_decision
    record.final_decision_reason = final_decision_reason
    record.final_decision_source = final_decision_source
    if should_rollback:
        await _restore_persona_mutable_state(
            agent_slug, baseline_state,
            reason=f"Reverted non-promoted honing candidate iteration {iteration}",
        )
        record.rollback_applied = True
    _apply_decision_to_loop_state(
        loop_state, should_rollback=should_rollback, record=record,
        experiment_key=experiment_key, baseline_runs=baseline_runs, candidate_runs=candidate_runs,
        review_baseline_runs=review_baseline_runs, review_candidate_runs=review_candidate_runs,
    )


async def _run_experiment_and_decide(
    *,
    iteration: int,
    record: PersonaHoningIteration,
    benchmark_run: PersonaBenchmarkRun,
    review_run: CompletionReviewBenchmarkRun | None,
    baseline_state: PersonaMutableState,
    loop_state: _LoopState,
    suite_name: str,
    baseline_config: dict[str, Any],
    review_baseline_config: dict[str, Any] | None,
    client: AsyncAgentHubClient,
    cfg: _IterationConfig,
) -> None:
    """Run improvement pass + cohort experiments + decide promote/rollback; mutates record and loop_state."""
    await _apply_improvement_pass(
        record, benchmark_run=benchmark_run, review_run=review_run,
        iteration=iteration, loop_state=loop_state, client=client, cfg=cfg,
    )
    baseline_runs, candidate_runs, experiment_key = await _run_and_evaluate_main_cohorts(
        record=record, benchmark_run=benchmark_run, baseline_config=baseline_config,
        suite_name=suite_name, iteration=iteration, cfg=cfg,
    )
    review_baseline_runs, review_candidate_runs, review_summary = await _maybe_run_review_cohorts(
        record=record, review_run=review_run, review_baseline_config=review_baseline_config,
        experiment_key=experiment_key, iteration=iteration, cfg=cfg,
    )
    final_decision, final_reason, final_source, decision_review = (
        await _determine_final_experiment_decision(
            client=client, iteration=iteration, record=record, experiment_key=experiment_key,
            experiment_summary=record.experiment_summary, review_summary=review_summary,
            field_snapshot=record.field_snapshot, cfg=cfg,
        )
    )
    record.decision_review = decision_review
    await _persist_final_experiment_decision(
        experiment_key=experiment_key, decision=final_decision, reason=final_reason,
        source=final_source, field_snapshot=record.field_snapshot, decision_review=decision_review,
    )
    await _resolve_experiment_decision(
        final_decision=final_decision, final_decision_reason=final_reason,
        final_decision_source=final_source, baseline_state=baseline_state,
        agent_slug=cfg["agent_slug"], iteration=iteration, experiment_key=experiment_key,
        baseline_runs=baseline_runs, candidate_runs=candidate_runs,
        review_baseline_runs=review_baseline_runs, review_candidate_runs=review_candidate_runs,
        record=record, loop_state=loop_state,
    )


async def _run_iteration(
    *,
    iteration: int,
    loop_state: _LoopState,
    client: AsyncAgentHubClient,
    suite_id: str | None,
    cfg: _IterationConfig,
) -> bool:
    """Execute one benchmark + improvement cycle. Returns True if the loop should stop."""
    baseline_state, benchmark_run, review_run, review_baseline_config = (
        await _run_initial_benchmarks(iteration=iteration, cfg=cfg)
    )
    report_path = _write_iteration_report(cfg["output_dir"], benchmark_run, iteration)
    baseline_config = await _get_config_snapshot(cfg["agent_slug"], cfg["benchmark_task_type"])
    suite_name = suite_id or derive_suite_id(cfg["case_ids"])
    record = _build_iteration_record(iteration, benchmark_run, report_path, loop_state, review_run=review_run)
    field_snapshot = await _load_field_snapshot()
    record.field_snapshot = {
        "overview": dict(field_snapshot.get("overview") or {}),
        "review_gate": dict(field_snapshot.get("review_gate") or {}),
        "risks": list(field_snapshot.get("risks") or [])[:3],
    }
    persist_kw: dict[str, Any] = dict(
        record=record, benchmark_run=benchmark_run, config_snapshot=baseline_config,
        suite_name=suite_name, agent_slug=cfg["agent_slug"], use_memory=cfg["use_memory"],
        seed=cfg["seed"] + iteration - 1, iteration=iteration, report_path=report_path,
        failure_clusters=record.failure_clusters or [],
        persistent_clusters=record.persistent_failure_clusters or [],
        persist_results=cfg["persist_results"],
    )
    review_clean_now = review_run is None or (record.review_failing_attempts or 0) == 0
    if record.failing_attempts == 0 and review_clean_now:
        await _persist_iteration_record(stop_reason=None, **persist_kw)
        loop_state.iterations.append(record)
        loop_state.honed = True
        return True
    if _is_stalled(record, loop_state, review_run=review_run):
        await _persist_iteration_record(stop_reason="no_improvement", **persist_kw)
        loop_state.iterations.append(record)
        return True
    await _run_experiment_and_decide(
        iteration=iteration, record=record, benchmark_run=benchmark_run, review_run=review_run,
        baseline_state=baseline_state, loop_state=loop_state, suite_name=suite_name,
        baseline_config=baseline_config, review_baseline_config=review_baseline_config,
        client=client, cfg=cfg,
    )
    await _persist_iteration_record(stop_reason=None, **persist_kw)
    loop_state.iterations.append(record)
    return loop_state.honed
