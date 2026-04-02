"""Iteration record construction and stall detection for the persona honing loop."""
from __future__ import annotations

from scripts.completion_review_benchmark_eval import CompletionReviewBenchmarkRun
from scripts.persona_benchmark_eval import PersonaBenchmarkRun
from scripts.persona_honing._clusters import _diff_failure_clusters, _group_failures
from scripts.persona_honing._models import PersonaHoningIteration, _LoopState
from scripts.persona_honing._run_helpers import _count_failures, _merge_review_runs, _merge_runs


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
    if review_merged is None:
        return
    review_top = review_merged.summaries[0] if review_merged.summaries else None
    loop_state.previous_review_best_score = (
        review_top.avg_composite_score if review_top is not None else (record.review_top_score or 0.0)
    )
    loop_state.previous_review_failing_attempts = _count_failures(review_merged)
    loop_state.previous_review_clusters = _group_failures(review_merged.attempts)


def _populate_review_fields(
    record: PersonaHoningIteration,
    review_run: CompletionReviewBenchmarkRun,
    loop_state: _LoopState,
) -> None:
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
        _populate_review_fields(record, review_run, loop_state)
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


def _apply_decision_to_loop_state(
    loop_state: _LoopState,
    *,
    should_rollback: bool,
    record: PersonaHoningIteration,
    experiment_key: str,
    baseline_runs: list[PersonaBenchmarkRun],
    candidate_runs: list[PersonaBenchmarkRun],
    review_baseline_runs: list[CompletionReviewBenchmarkRun],
    review_candidate_runs: list[CompletionReviewBenchmarkRun],
) -> None:
    """Merge winning runs into loop state and set the honed flag."""
    if should_rollback:
        merged = _merge_runs(baseline_runs, benchmark_id=f"{experiment_key}-baseline-merged")
        review_merged = (
            _merge_review_runs(
                review_baseline_runs,
                benchmark_id=f"{record.review_experiment_key}-baseline-merged",
            ) if review_baseline_runs else None
        )
    else:
        merged = _merge_runs(candidate_runs, benchmark_id=f"{experiment_key}-candidate-merged")
        review_merged = (
            _merge_review_runs(
                review_candidate_runs,
                benchmark_id=f"{record.review_experiment_key}-candidate-merged",
            ) if review_candidate_runs else None
        )
    _update_loop_state_from_merged(loop_state, merged, record, review_merged=review_merged)
    review_clean = loop_state.previous_review_failing_attempts == 0 if review_merged is not None else True
    loop_state.honed = not should_rollback and loop_state.previous_failing_attempts == 0 and review_clean
