"""Tests for the Jenny honing loop helpers."""

from __future__ import annotations

from scripts.jenny_benchmark_eval import (
    JennyBenchmarkAttempt,
    JennyBenchmarkRun,
    summarize_attempts,
)
from scripts.run_jenny_honing_loop import build_honing_prompt


def _make_run(attempts: list[JennyBenchmarkAttempt]) -> JennyBenchmarkRun:
    return JennyBenchmarkRun(
        benchmark_id="bench-hone",
        project_id="agent-hub",
        models=["codex/gpt-5.4", "claude-sonnet-4-6"],
        case_ids=["feedback_triage_hotspot", "performance_review_honing"],
        runs_per_case=1,
        started_at="2026-03-11T00:00:00+00:00",
        completed_at="2026-03-11T00:01:00+00:00",
        attempts=attempts,
        summaries=summarize_attempts(attempts),
    )


def test_build_honing_prompt_includes_failure_clusters_and_reference_notes() -> None:
    run = _make_run(
        [
            JennyBenchmarkAttempt(
                model_id="codex/gpt-5.4",
                case_id="feedback_triage_hotspot",
                run_number=1,
                latency_ms=800,
                composite_score=42.0,
                correctness_score=0.5,
                passed=False,
                failure_kind="model",
                failure_detail="required_tools_missing: manage_feedback",
                total_tokens=120,
                turns=2,
                tool_calls_count=1,
                used_tool_names=["review_agent_performance"],
            ),
            JennyBenchmarkAttempt(
                model_id="claude-sonnet-4-6",
                case_id="performance_review_honing",
                run_number=1,
                latency_ms=760,
                composite_score=55.0,
                correctness_score=0.6,
                passed=False,
                failure_kind="model",
                failure_detail="summary_terms_missing: heartbeat, performance",
                total_tokens=110,
                turns=2,
                tool_calls_count=2,
                used_tool_names=["review_agent_performance", "read_heartbeat_instructions"],
            ),
        ]
    )

    prompt = build_honing_prompt(run, iteration=2)

    assert "feedback_triage_hotspot" in prompt
    assert "performance_review_honing" in prompt
    assert "Auto-Claude inspiration" in prompt
    assert "OpenClaw inspiration" in prompt
    assert "Do not create or dispatch project tasks." in prompt


def test_build_honing_prompt_handles_clean_run() -> None:
    run = _make_run(
        [
            JennyBenchmarkAttempt(
                model_id="codex/gpt-5.4",
                case_id="feedback_triage_hotspot",
                run_number=1,
                latency_ms=500,
                composite_score=100.0,
                correctness_score=1.0,
                passed=True,
                total_tokens=80,
                turns=1,
                tool_calls_count=1,
                used_tool_names=["manage_feedback"],
            )
        ]
    )

    prompt = build_honing_prompt(run, iteration=1)

    assert "Top failure clusters:\n- none" in prompt
