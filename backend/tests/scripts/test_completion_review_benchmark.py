"""Tests for completion-review benchmark scoring and payload shaping."""

from __future__ import annotations

from scripts.completion_review_benchmark_cases import (
    get_completion_review_case_by_id,
    get_default_completion_review_case_ids,
)
from scripts.completion_review_benchmark_eval import (
    CompletionReviewBenchmarkRun,
    score_completion_review_attempt,
    summarize_completion_review_attempts,
)
from scripts.run_completion_review_model_benchmark import build_persistence_payload, derive_suite_id


def test_score_completion_review_attempt_passes_matching_decision() -> None:
    case = get_completion_review_case_by_id("review_cleanup_false_complete")

    attempt = score_completion_review_attempt(
        case=case,
        model_id="codex/gpt-5.4",
        run_number=1,
        latency_ms=1200,
        content=(
            '{"case_id":"review_cleanup_false_complete","decision":"continue","confidence":"high",'
            '"reason":"Cleanup residue remains and needs finalize handling.","focus":"cleanup finalize"}'
        ),
        session_id="sess-1",
        provider="codex",
        effective_model="codex/gpt-5.4",
        fallback_used=False,
        turns=1,
        tool_calls_count=0,
        used_tool_names=[],
        input_tokens=100,
        output_tokens=50,
        total_tokens=150,
    )

    assert attempt.passed is True
    assert attempt.correctness_score == 1.0
    assert attempt.composite_score == 100.0


def test_build_persistence_payload_maps_decision_into_attempt_record() -> None:
    case = get_completion_review_case_by_id("review_true_complete_clean")
    attempt = score_completion_review_attempt(
        case=case,
        model_id="claude-opus-4-6",
        run_number=1,
        latency_ms=900,
        content=(
            '{"case_id":"review_true_complete_clean","decision":"complete","confidence":"medium",'
            '"reason":"No cleanup or workstream residue remains.","focus":"complete"}'
        ),
        session_id="sess-2",
        provider="claude",
        effective_model="claude-opus-4-6",
        fallback_used=False,
        turns=1,
        tool_calls_count=0,
        used_tool_names=[],
        input_tokens=120,
        output_tokens=60,
        total_tokens=180,
    )
    run = CompletionReviewBenchmarkRun(
        benchmark_id="review-bench-1",
        project_id="persona-sandbox",
        models=["claude-opus-4-6"],
        case_ids=[case.case_id],
        runs_per_case=1,
        started_at="2026-03-11T00:00:00+00:00",
        completed_at="2026-03-11T00:01:00+00:00",
        attempts=[attempt],
        summaries=summarize_completion_review_attempts([attempt]),
    )

    payload = build_persistence_payload(
        run,
        agent_slug="supervisor",
        suite_id="completion-review-suite",
        run_kind="completion_review_benchmark",
        use_memory=False,
        seed=42,
        config_snapshot={"primary_model_id": "claude-opus-4-6"},
        metadata={"reviewer_role": True},
    )

    assert payload["avg_score"] == 100.0
    assert payload["pass_rate"] == 100.0
    assert payload["attempts"][0]["primary_action"] == "complete"
    assert payload["attempts"][0]["summary"] == "No cleanup or workstream residue remains."


def test_score_completion_review_attempt_classifies_infra_failures() -> None:
    case = get_completion_review_case_by_id("review_recent_progress_patience")

    attempt = score_completion_review_attempt(
        case=case,
        model_id="codex/gpt-5.4",
        run_number=1,
        latency_ms=2500,
        content="",
        session_id=None,
        provider=None,
        effective_model=None,
        fallback_used=False,
        turns=0,
        tool_calls_count=0,
        used_tool_names=[],
        input_tokens=0,
        output_tokens=0,
        total_tokens=0,
        failure_detail="upstream connect error: timeout",
    )

    assert attempt.infra_failure is True
    assert attempt.failure_kind == "infra"


def test_score_completion_review_attempt_accepts_monitor_as_recent_progress_follow_through() -> None:
    case = get_completion_review_case_by_id("review_recent_progress_patience")

    attempt = score_completion_review_attempt(
        case=case,
        model_id="claude-sonnet-4-6",
        run_number=1,
        latency_ms=900,
        content=(
            '{"case_id":"review_recent_progress_patience","decision":"continue","confidence":"high",'
            '"reason":"Active lane still shows recent progress and remains healthy.","focus":"monitor task-abc lane"}'
        ),
        session_id="sess-3",
        provider="claude",
        effective_model="claude-sonnet-4-6",
        fallback_used=False,
        turns=1,
        tool_calls_count=0,
        used_tool_names=[],
        input_tokens=120,
        output_tokens=40,
        total_tokens=160,
    )

    assert attempt.passed is True
    assert attempt.failure_detail is None


def test_default_completion_review_suite_matches_live_reviewer_path() -> None:
    assert get_default_completion_review_case_ids() == [
        "review_recent_progress_patience",
        "review_quiet_healthy_true_complete",
        "review_true_complete_clean",
    ]
    assert derive_suite_id(get_default_completion_review_case_ids()) == "completion-review-reviewer"
