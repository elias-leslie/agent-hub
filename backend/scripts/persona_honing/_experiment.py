"""Cohort experiment helpers and per-iteration logic for the persona honing loop."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from agent_hub import AsyncAgentHubClient
from sqlalchemy import select

from app.db import async_session
from app.services.agent_benchmark_service import (
    get_benchmark_experiment_summary_by_key,
    summarize_benchmark_experiment,
)
from app.services.persona_prompt_service import (
    render_persona_improvement_decision_review_prompt,
    render_persona_improvement_prompt,
)
from scripts.completion_review_benchmark_eval import (
    CompletionReviewBenchmarkRun,
    summarize_completion_review_attempts,
)
from scripts.persona_benchmark_eval import PersonaBenchmarkRun, summarize_attempts
from scripts.persona_benchmark_persistence import build_persistence_payload
from scripts.persona_benchmark_report import generate_markdown_report
from scripts.persona_benchmark_runner import _fetch_used_tool_names
from scripts.persona_honing._benchmarks import (
    _get_config_snapshot,
    _run_cohort_benchmarks,
    _run_initial_benchmarks,
    _run_review_cohort_benchmarks,
)
from scripts.persona_honing._clusters import (
    _diff_failure_clusters,
    _group_failures,
    _render_cluster_block,
)
from scripts.persona_honing._constants import (
    DECISION_PROMOTE,
    RUN_KIND_HONING_BASELINE,
    RUN_KIND_HONING_CANDIDATE,
)
from scripts.persona_honing._models import (
    PersonaHoningIteration,
    PersonaMutableState,
    _IterationConfig,
    _LoopState,
)
from scripts.persona_honing._persistence import (
    _persist_iteration_record,
    _persist_review_cohort_pair,
    _persist_runs,
)
from scripts.persona_honing._response import (
    _HONING_RESPONSE_SCHEMA,
    parse_decision_review_content,
    parse_improvement_content,
)
from scripts.persona_honing._state import _restore_persona_mutable_state
from scripts.run_completion_review_model_benchmark import derive_suite_id as derive_review_suite_id
from scripts.run_persona_model_benchmark import derive_suite_id

_REFERENCE_NOTES = [
    (
        "Auto-Claude inspiration: the learning loop should retrieve shared patterns/gotchas "
        "before acting, and durable lessons belong in shared memory rather than ad hoc notes."
    ),
    (
        "OpenClaw inspiration: keep fallback/model decisions observable and simple; prefer "
        "clear, inspectable adaptation over extra defensive machinery."
    ),
]


async def _load_recent_improvement_signals(project_id: str) -> str | None:
    """Return recent combined improvement evidence for the honing prompt."""
    from app.services.improvement_signals import build_improvement_signal_digest

    review = await build_improvement_signal_digest(
        project_id=project_id, primary_agent_slug="persona", days_back=7, include_team=True,
    )
    return review.strip() or None


async def _load_field_snapshot() -> dict[str, Any]:
    from app.services.persona_improvement import get_persona_heartbeat_field_snapshot

    async with async_session() as db:
        return await get_persona_heartbeat_field_snapshot(db)


def _format_delta_block(label: str, delta: dict[str, Any] | None) -> str:
    if not isinstance(delta, dict):
        return f"- {label}: unavailable"
    return f"- {label}: mean={delta.get('mean_delta')} ci=[{delta.get('ci_low')}, {delta.get('ci_high')}]"


def _format_experiment_summary_block(summary: dict[str, Any] | None) -> str:
    if not isinstance(summary, dict):
        return "- not available"
    baseline = dict(summary.get("baseline") or {})
    candidate = dict(summary.get("candidate") or {})
    return "\n".join([
        f"- decision={summary.get('decision')} reason={summary.get('decision_reason')}",
        (
            f"- baseline: runs={baseline.get('run_count')} score={baseline.get('avg_score')} "
            f"pass_rate={baseline.get('avg_pass_rate')} tools={baseline.get('avg_tool_calls')}"
        ),
        (
            f"- candidate: runs={candidate.get('run_count')} score={candidate.get('avg_score')} "
            f"pass_rate={candidate.get('avg_pass_rate')} tools={candidate.get('avg_tool_calls')}"
        ),
        _format_delta_block("score_delta", summary.get("score_delta")),
        _format_delta_block("pass_rate_delta", summary.get("pass_rate_delta")),
        _format_delta_block("tool_call_delta", summary.get("tool_call_delta")),
    ])


def _format_improvement_summary_block(record: PersonaHoningIteration) -> str:
    parsed = dict(record.improvement_parsed or {})
    changes = parsed.get("changes_applied")
    next_focus = parsed.get("next_focus")
    lines = [
        f"- summary={parsed.get('summary') or '(none)'}",
        f"- tools={', '.join(record.improvement_tools or []) or 'none'}",
    ]
    if isinstance(changes, list) and changes:
        lines.append("- changes_applied=" + "; ".join(str(item) for item in changes))
    if isinstance(next_focus, list) and next_focus:
        lines.append("- next_focus=" + "; ".join(str(item) for item in next_focus))
    return "\n".join(lines)


def _needs_supervisor_review(
    *,
    raw_decision: str,
    raw_reason: str,
    review_summary: dict[str, Any] | None,
    field_snapshot: dict[str, Any] | None,
) -> bool:
    if raw_decision == "hold":
        return True
    if raw_reason == "candidate_matches_quality_with_fewer_tool_calls":
        return True
    if review_summary is not None and str(review_summary.get("decision")) == "hold":
        return True
    return bool(dict((field_snapshot or {}).get("review_gate") or {}).get("needs_review"))


async def _persist_final_experiment_decision(
    *,
    experiment_key: str,
    decision: str,
    reason: str,
    source: str,
    field_snapshot: dict[str, Any] | None,
    decision_review: dict[str, Any] | None,
) -> None:
    from app.models import AgentBenchmarkExperiment

    async with async_session() as db:
        experiment = await db.scalar(
            select(AgentBenchmarkExperiment).where(
                AgentBenchmarkExperiment.experiment_key == experiment_key
            )
        )
        if experiment is None:
            return
        evidence = dict(experiment.evidence or {})
        evidence["final_decision_source"] = source
        if field_snapshot:
            evidence["field_gate"] = dict(field_snapshot.get("review_gate") or {})
            evidence["field_overview"] = dict(field_snapshot.get("overview") or {})
        if decision_review:
            evidence["supervisor_review"] = decision_review
        experiment.decision = decision
        experiment.decision_reason = reason
        experiment.status = "closed" if decision in {"promote", "rollback"} else "open"
        experiment.evidence = evidence
        await db.commit()


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
            enable_caching=False, skip_cache=True, use_memory=False, max_turns=1,
            working_dir=str(working_root), execute_tools=False, timeout_seconds=timeout_seconds,
        )
    except Exception as exc:
        return {"used": False, "session_id": None, "decision": None, "reason": f"review_unavailable:{type(exc).__name__}"}
    parsed = parse_decision_review_content(response.content)
    if parsed is None:
        return {"used": False, "session_id": response.session_id, "decision": None, "reason": "review_unparseable", "raw_content": response.content}
    return {
        "used": True, "session_id": response.session_id,
        "decision": parsed["decision"], "reason": parsed["reason"],
        "raw_content": response.content,
        "field_gate": dict((field_snapshot or {}).get("review_gate") or {}),
    }


async def _determine_final_experiment_decision(
    *,
    client: AsyncAgentHubClient,
    iteration: int,
    record: PersonaHoningIteration,
    experiment_key: str,
    experiment_summary: dict[str, Any],
    review_summary: dict[str, Any] | None,
    field_snapshot: dict[str, Any] | None,
    cfg: _IterationConfig,
) -> tuple[str, str, str, dict[str, Any] | None]:
    raw_decision = str(experiment_summary.get("decision") or "hold")
    raw_reason = str(experiment_summary.get("decision_reason") or "no_clear_winner")
    review_decision = str(review_summary.get("decision")) if review_summary is not None else None
    if review_decision == "rollback":
        review_reason = str(review_summary.get("decision_reason") or "completion_review_regression")
        return "rollback", review_reason, "completion_review", None
    if _needs_supervisor_review(
        raw_decision=raw_decision, raw_reason=raw_reason,
        review_summary=review_summary, field_snapshot=field_snapshot,
    ):
        decision_review = await _run_decision_review(
            client=client, iteration=iteration, experiment_key=experiment_key,
            project_id=cfg["project_id"], timeout_seconds=cfg["timeout_seconds"],
            working_root=cfg["working_root"], proposed_decision=raw_decision,
            proposed_reason=raw_reason, experiment_summary=experiment_summary,
            review_summary=review_summary, field_snapshot=field_snapshot, record=record,
        )
        if decision_review.get("used"):
            return str(decision_review["decision"]), str(decision_review["reason"]), "supervisor_review", decision_review
        return raw_decision, raw_reason, "benchmark", decision_review
    return raw_decision, raw_reason, "benchmark", None


def _build_review_prompt_blocks(
    review_run: CompletionReviewBenchmarkRun | None,
    previous_review_clusters: list[dict[str, Any]] | None,
    max_failures: int,
) -> tuple[str, str, str]:
    """Return (review_ranking_block, review_failure_block, review_persistent_block)."""
    if review_run is None:
        return (
            "- not run",
            "Completion-review failure clusters:\n- not run",
            "Persistent completion-review clusters from the previous iteration:\n- not run",
        )
    review_ranking_lines = [
        f"- rank={i} model={s.model_id} avg_score={s.avg_composite_score:.1f} "
        f"pass_rate={s.pass_rate:.1f} avg_turns={s.avg_turns:.2f}"
        for i, s in enumerate(review_run.summaries[:3], start=1)
    ]
    review_clusters = _group_failures(review_run.attempts)
    review_persistent_clusters, _, _ = _diff_failure_clusters(previous_review_clusters, review_clusters)
    return (
        "\n".join(review_ranking_lines) if review_ranking_lines else "- none",
        _render_cluster_block(review_clusters[:max_failures], "Completion-review failure clusters"),
        _render_cluster_block(
            review_persistent_clusters[:max_failures],
            "Persistent completion-review clusters from the previous iteration",
        ),
    )


async def _build_improvement_prompt(
    *,
    run: PersonaBenchmarkRun,
    iteration: int,
    previous_clusters: list[dict[str, Any]] | None,
    review_run: CompletionReviewBenchmarkRun | None,
    previous_review_clusters: list[dict[str, Any]] | None,
    improvement_signals: str | None,
    field_signals: str | None,
    max_failures: int = 6,
) -> str:
    current_clusters = _group_failures(run.attempts)
    persistent_clusters, new_clusters, resolved_clusters = _diff_failure_clusters(
        previous_clusters, current_clusters,
    )
    ranking_block = "\n".join(
        f"- rank={i} model={s.model_id} avg_score={s.avg_composite_score:.1f} "
        f"pass_rate={s.pass_rate:.3f} avg_tools={s.avg_tool_calls:.1f}"
        for i, s in enumerate(run.summaries[:3], start=1)
    ) or "- none"
    review_ranking_block, review_failure_block, review_persistent_block = (
        _build_review_prompt_blocks(review_run, previous_review_clusters, max_failures)
    )
    return await render_persona_improvement_prompt(
        iteration=iteration,
        ranking_block=ranking_block,
        failure_block=_render_cluster_block(current_clusters[:max_failures], "Top failure clusters"),
        persistent_block=_render_cluster_block(persistent_clusters[:max_failures], "Persistent unresolved clusters from the previous iteration"),
        new_block=_render_cluster_block(new_clusters[:max_failures], "New clusters this iteration"),
        resolved_block=_render_cluster_block(resolved_clusters[:max_failures], "Resolved clusters since the previous iteration"),
        review_ranking_block=review_ranking_block,
        review_failure_block=review_failure_block,
        review_persistent_block=review_persistent_block,
        improvement_signals_block=improvement_signals or "- none",
        field_signals_block=field_signals or "- none",
        reference_block="\n".join(f"- {note}" for note in _REFERENCE_NOTES),
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
    return _merge_benchmark_runs(runs, benchmark_id=benchmark_id, summarize_fn=summarize_attempts)  # type: ignore[return-value]


def _merge_review_runs(
    runs: list[CompletionReviewBenchmarkRun], *, benchmark_id: str
) -> CompletionReviewBenchmarkRun:
    return _merge_benchmark_runs(runs, benchmark_id=benchmark_id, summarize_fn=summarize_completion_review_attempts)  # type: ignore[return-value]


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
        run=run, iteration=iteration, previous_clusters=previous_clusters,
        review_run=review_run, previous_review_clusters=previous_review_clusters,
        improvement_signals=improvement_signals, field_signals=field_signals,
    )
    response = await client.complete(
        messages=[{"role": "user", "content": prompt}],
        project_id=project_id, agent_slug="persona",
        external_id=f"persona-honing:{run.benchmark_id}:iteration-{iteration}",
        enable_caching=False, skip_cache=True, use_memory=False, max_turns=12,
        working_dir=str(working_root), execute_tools=True, timeout_seconds=timeout_seconds,
        response_format={"type": "json_object", "schema": _HONING_RESPONSE_SCHEMA},
    )
    used_tools = await _fetch_used_tool_names(response.session_id)
    return response.session_id, response.content, used_tools, parse_improvement_content(response.content)


def _write_iteration_report(output_dir: Path, run: PersonaBenchmarkRun, iteration: int) -> str:
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / f"iteration-{iteration:02d}-{run.benchmark_id}.md"
    report_path.write_text(generate_markdown_report(run))
    return str(report_path)


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
    if persist_results:
        async with async_session() as db:
            persisted = await get_benchmark_experiment_summary_by_key(db, experiment_key)
        if persisted:
            summary = persisted
    return summary


def _update_loop_state_from_merged(
    loop_state: _LoopState,
    merged: PersonaBenchmarkRun,
    record: PersonaHoningIteration,
    *,
    review_merged: CompletionReviewBenchmarkRun | None = None,
) -> None:
    loop_state.previous_best_score = (
        merged.summaries[0].avg_composite_score if merged.summaries else record.top_score
    )
    loop_state.previous_failing_attempts = _count_failures(merged)
    loop_state.previous_clusters = _group_failures(merged.attempts)
    if review_merged is not None:
        review_top = review_merged.summaries[0] if review_merged.summaries else None
        loop_state.previous_review_best_score = (
            review_top.avg_composite_score if review_top is not None else (record.review_top_score or 0.0)
        )
        loop_state.previous_review_failing_attempts = _count_failures(review_merged)
        loop_state.previous_review_clusters = _group_failures(review_merged.attempts)


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
    common = dict(
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
    review_experiment_key = f"persona-honing-review-{review_suite_name}-iter-{iteration}-{uuid.uuid4().hex[:8]}"
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
        merged = _merge_runs(baseline_runs, benchmark_id=f"{experiment_key}-baseline-merged")
        review_merged = (
            _merge_review_runs(review_baseline_runs, benchmark_id=f"{record.review_experiment_key}-baseline-merged")
            if review_baseline_runs else None
        )
    else:
        merged = _merge_runs(candidate_runs, benchmark_id=f"{experiment_key}-candidate-merged")
        review_merged = (
            _merge_review_runs(review_candidate_runs, benchmark_id=f"{record.review_experiment_key}-candidate-merged")
            if review_candidate_runs else None
        )
    _update_loop_state_from_merged(loop_state, merged, record, review_merged=review_merged)
    review_clean = loop_state.previous_review_failing_attempts == 0 if review_merged is not None else True
    loop_state.honed = not should_rollback and loop_state.previous_failing_attempts == 0 and review_clean


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
    baseline_runs = await _run_cohort_benchmarks(**cohort_kw, seed_base=cfg["seed"] + iteration * 100, first_run=benchmark_run)
    candidate_runs = await _run_cohort_benchmarks(**cohort_kw, seed_base=cfg["seed"] + iteration * 1000)
    experiment_key = f"persona-honing-{suite_name}-iter-{iteration}-{uuid.uuid4().hex[:8]}"
    record.experiment_key = experiment_key
    candidate_config = await _get_config_snapshot(cfg["agent_slug"], cfg["benchmark_task_type"])
    if cfg["persist_results"]:
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
    record.experiment_summary = await _evaluate_experiment(
        experiment_key=experiment_key, iteration=iteration, suite_name=suite_name,
        baseline_runs=baseline_runs, candidate_runs=candidate_runs,
        baseline_config=baseline_config, candidate_config=candidate_config,
        cohort_repetitions=cfg["cohort_repetitions"], persist_results=cfg["persist_results"],
    )
    return baseline_runs, candidate_runs, experiment_key


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


def _build_iteration_record(
    iteration: int,
    benchmark_run: PersonaBenchmarkRun,
    report_path: str,
    loop_state: _LoopState,
    review_run: CompletionReviewBenchmarkRun | None = None,
) -> PersonaHoningIteration:
    failure_clusters = _group_failures(benchmark_run.attempts)
    persistent_clusters, _, _ = _diff_failure_clusters(loop_state.previous_clusters, failure_clusters)
    top_summary = benchmark_run.summaries[0] if benchmark_run.summaries else None
    record = PersonaHoningIteration(
        iteration=iteration,
        benchmark_id=benchmark_run.benchmark_id,
        top_model=top_summary.model_id if top_summary else None,
        top_score=top_summary.avg_composite_score if top_summary else 0.0,
        failing_attempts=_count_failures(benchmark_run),
        benchmark_report_path=report_path,
        failure_clusters=failure_clusters,
        persistent_failure_clusters=persistent_clusters,
    )
    if review_run is not None:
        review_failure_clusters = _group_failures(review_run.attempts)
        review_persistent, _, _ = _diff_failure_clusters(
            loop_state.previous_review_clusters, review_failure_clusters,
        )
        review_top = review_run.summaries[0] if review_run.summaries else None
        record.review_benchmark_id = review_run.benchmark_id
        record.review_top_model = review_top.model_id if review_top else None
        record.review_top_score = review_top.avg_composite_score if review_top else 0.0
        record.review_failing_attempts = _count_failures(review_run)
        record.review_failure_clusters = review_failure_clusters
        record.review_persistent_failure_clusters = review_persistent
    return record


def _is_stalled(
    record: PersonaHoningIteration,
    loop_state: _LoopState,
    *,
    review_run: CompletionReviewBenchmarkRun | None,
) -> bool:
    """Return True when there is no measurable improvement since last iteration."""
    if loop_state.previous_best_score is None or loop_state.previous_failing_attempts is None:
        return False
    main_stalled = (
        record.top_score <= loop_state.previous_best_score
        and record.failing_attempts >= loop_state.previous_failing_attempts
    )
    if not main_stalled:
        return False
    if review_run is None:
        return True
    return (
        loop_state.previous_review_best_score is not None
        and loop_state.previous_review_failing_attempts is not None
        and (record.review_top_score or 0.0) <= loop_state.previous_review_best_score
        and (record.review_failing_attempts or 0) >= loop_state.previous_review_failing_attempts
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
