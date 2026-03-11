"""Tests for Jenny model benchmark helpers."""

from __future__ import annotations

from pathlib import Path

from scripts.jenny_benchmark_cases import (
    DEFAULT_JENNY_BENCHMARK_MODELS,
    get_case_by_id,
    get_jenny_benchmark_cases,
    prepare_case_workspace,
)
from scripts.jenny_benchmark_eval import (
    JennyBenchmarkAttempt,
    parse_benchmark_json,
    score_attempt,
    summarize_attempts,
)
from scripts.jenny_benchmark_report import generate_markdown_report


def test_default_model_roster_includes_seven_candidates() -> None:
    assert DEFAULT_JENNY_BENCHMARK_MODELS == [
        "codex/gpt-5.4",
        "openai/gpt-5.2",
        "codex/gpt-5.3-codex",
        "codex/gpt-5.3-codex-spark",
        "claude-opus-4-6",
        "claude-sonnet-4-6",
        "claude-haiku-4-5",
    ]


def test_workspace_case_materializes_fixture_files(tmp_path: Path) -> None:
    case = get_case_by_id("workspace_inspection_gate")

    workdir = prepare_case_workspace(case, tmp_path / "workspace")

    assert (workdir / "task.txt").read_text().startswith("TASK: task-6666")
    assert "needs_cleanup=1" in (workdir / "cleanup.txt").read_text()


def test_parse_benchmark_json_strips_code_fences() -> None:
    parsed, error = parse_benchmark_json(
        """```json
        {"case_id":"ready_task_dispatch","primary_action":"dispatch","should_dispatch":true,"should_close":false,"confidence":"high","summary":"ready"}
        ```"""
    )

    assert error is None
    assert parsed is not None
    assert parsed["primary_action"] == "dispatch"


def test_score_attempt_marks_perfect_pass_for_correct_response() -> None:
    case = get_case_by_id("ready_task_dispatch")

    attempt = score_attempt(
        case=case,
        model_id="claude-sonnet-4-6",
        run_number=1,
        latency_ms=1234,
        content=(
            '{"case_id":"ready_task_dispatch","primary_action":"dispatch",'
            '"should_dispatch":true,"should_close":false,'
            '"confidence":"high","summary":"Task is ready to dispatch."}'
        ),
        session_id="sess-1",
        provider="claude",
        effective_model="claude-sonnet-4-6",
        fallback_used=False,
        turns=1,
        tool_calls_count=0,
        input_tokens=100,
        output_tokens=20,
        total_tokens=120,
    )

    assert attempt.passed is True
    assert attempt.correctness_score == 1.0
    assert attempt.composite_score == 100.0
    assert attempt.failure_detail is None


def test_score_attempt_fails_when_tool_requirement_missing() -> None:
    case = get_case_by_id("workspace_inspection_gate")

    attempt = score_attempt(
        case=case,
        model_id="claude-haiku-4-5",
        run_number=1,
        latency_ms=800,
        content=(
            '{"case_id":"workspace_inspection_gate","primary_action":"block",'
            '"should_dispatch":false,"should_close":false,'
            '"confidence":"medium","summary":"Cleanup blocks action."}'
        ),
        session_id="sess-2",
        provider="claude",
        effective_model="claude-haiku-4-5",
        fallback_used=False,
        turns=1,
        tool_calls_count=0,
        input_tokens=60,
        output_tokens=18,
        total_tokens=78,
    )

    assert attempt.passed is False
    assert attempt.tool_requirement_met is False
    assert attempt.failure_detail == "required_tool_call_missing"


def test_summarize_attempts_ranks_by_score_then_reliability() -> None:
    attempts = [
        JennyBenchmarkAttempt(
            model_id="model-a",
            case_id="c1",
            run_number=1,
            latency_ms=1000,
            composite_score=100.0,
            correctness_score=1.0,
            passed=True,
            total_tokens=100,
            turns=1,
            tool_calls_count=0,
        ),
        JennyBenchmarkAttempt(
            model_id="model-b",
            case_id="c1",
            run_number=1,
            latency_ms=900,
            composite_score=90.0,
            correctness_score=0.8,
            passed=False,
            failure_kind="model",
            total_tokens=90,
            turns=1,
            tool_calls_count=0,
        ),
    ]

    summaries = summarize_attempts(attempts)

    assert [summary.model_id for summary in summaries] == ["model-a", "model-b"]
    assert summaries[0].pass_rate == 1.0
    assert summaries[1].model_failures == 1


def test_generate_markdown_report_includes_ranking_table() -> None:
    attempts = [
        JennyBenchmarkAttempt(
            model_id="model-a",
            case_id="c1",
            run_number=1,
            latency_ms=1000,
            composite_score=100.0,
            correctness_score=1.0,
            passed=True,
            total_tokens=100,
            turns=1,
            tool_calls_count=0,
        )
    ]
    summaries = summarize_attempts(attempts)
    from scripts.jenny_benchmark_eval import JennyBenchmarkRun

    run = JennyBenchmarkRun(
        benchmark_id="bench-1",
        project_id="persona-sandbox",
        models=["model-a"],
        case_ids=["c1"],
        runs_per_case=1,
        started_at="2026-03-11T00:00:00+00:00",
        completed_at="2026-03-11T00:01:00+00:00",
        attempts=attempts,
        summaries=summaries,
    )

    report = generate_markdown_report(run)

    assert "# Jenny Model Benchmark" in report
    assert "| Rank | Model | Avg Score |" in report
    assert "`model-a`" in report


def test_benchmark_case_battery_is_stable() -> None:
    case_ids = [case.case_id for case in get_jenny_benchmark_cases()]
    assert case_ids == [
        "ready_task_dispatch",
        "same_task_overlap",
        "cleanup_blocks_closeout",
        "session_patience_quiet",
        "stalled_session_reconcile",
        "workspace_inspection_gate",
    ]
