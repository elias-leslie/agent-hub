"""Tests for Jenny model benchmark helpers."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from scripts.jenny_benchmark_cases import (
    DEFAULT_JENNY_BENCHMARK_MODELS,
    get_case_by_id,
    get_jenny_benchmark_cases,
    prepare_case_workspace,
)
from scripts.jenny_benchmark_eval import (
    JennyBenchmarkAttempt,
    classify_failure,
    parse_benchmark_json,
    score_attempt,
    summarize_attempts,
)
from scripts.jenny_benchmark_report import generate_markdown_report


def test_default_model_roster_includes_seven_configured_candidates() -> None:
    assert DEFAULT_JENNY_BENCHMARK_MODELS == [
        "codex/gpt-5.4",
        "codex/gpt-5.3-codex",
        "codex/gpt-5.3-codex-spark",
        "codex/gpt-5.2",
        "claude-opus-4-6",
        "claude-sonnet-4-6",
        "claude-haiku-4-5",
    ]


def test_workspace_case_materializes_fixture_files(tmp_path: Path) -> None:
    case = get_case_by_id("workspace_inspection_gate")

    workdir = prepare_case_workspace(case, tmp_path / "workspace")

    assert (workdir / "task.txt").read_text().startswith("TASK: task-6666")
    assert "needs_cleanup=1" in (workdir / "cleanup.txt").read_text()


def test_workspace_case_prompt_limits_search_scope() -> None:
    case = get_case_by_id("workspace_inspection_gate")

    prompt = case.build_prompt()

    assert "Only inspect task.txt, cleanup.txt, and sessions.txt" in prompt
    assert "Do not search outside the current working directory" in prompt


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
        used_tool_names=[],
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
        used_tool_names=[],
        input_tokens=60,
        output_tokens=18,
        total_tokens=78,
    )

    assert attempt.passed is False
    assert attempt.tool_requirement_met is False
    assert attempt.failure_detail == "required_tool_call_missing"


def test_score_attempt_checks_required_summary_terms() -> None:
    case = get_case_by_id("precision_search_architecture")

    attempt = score_attempt(
        case=case,
        model_id="claude-sonnet-4-6",
        run_number=1,
        latency_ms=900,
        content=(
            '{"case_id":"precision_search_architecture","primary_action":"dispatch",'
            '"should_dispatch":true,"should_close":false,'
            '"confidence":"high","summary":"Dispatch the shared Precision Code Search tool with a soft reminder and telemetry next."}'
        ),
        session_id="sess-3",
        provider="claude",
        effective_model="claude-sonnet-4-6",
        fallback_used=False,
        turns=1,
        tool_calls_count=0,
        used_tool_names=[],
        input_tokens=60,
        output_tokens=24,
        total_tokens=84,
    )

    assert attempt.passed is True
    assert attempt.correctness_score == 1.0


def test_score_attempt_requires_specific_tool_name() -> None:
    case = get_case_by_id("precision_search_live_lookup")

    attempt = score_attempt(
        case=case,
        model_id="claude-sonnet-4-6",
        run_number=1,
        latency_ms=700,
        content=(
            '{"case_id":"precision_search_live_lookup","primary_action":"dispatch",'
            '"should_dispatch":true,"should_close":false,'
            '"confidence":"high","summary":"The tool is already wired into the shared path, so dispatch follow-on work."}'
        ),
        session_id="sess-4",
        provider="claude",
        effective_model="claude-sonnet-4-6",
        fallback_used=False,
        turns=2,
        tool_calls_count=1,
        used_tool_names=["read_file"],
        input_tokens=70,
        output_tokens=22,
        total_tokens=92,
    )

    assert attempt.passed is False
    assert attempt.tool_requirement_met is False
    assert attempt.failure_detail == "required_tools_missing: precision_code_search"


def test_score_attempt_accepts_normalized_specific_tool_name() -> None:
    case = get_case_by_id("precision_search_live_lookup")

    attempt = score_attempt(
        case=case,
        model_id="claude-sonnet-4-6",
        run_number=1,
        latency_ms=700,
        content=(
            '{"case_id":"precision_search_live_lookup","primary_action":"dispatch",'
            '"should_dispatch":true,"should_close":false,'
            '"confidence":"high","summary":"The tool is already wired into the shared path, so dispatch follow-on work."}'
        ),
        session_id="sess-5",
        provider="claude",
        effective_model="claude-sonnet-4-6",
        fallback_used=False,
        turns=2,
        tool_calls_count=1,
        used_tool_names=["mcp__agent-hub__precision_code_search"],
        input_tokens=70,
        output_tokens=22,
        total_tokens=92,
    )

    assert attempt.passed is True
    assert attempt.tool_requirement_met is True


def test_classify_failure_marks_internal_server_errors_as_infra() -> None:
    infra, kind = classify_failure(
        'Server error: {"error":"internal_server_error","message":"An unexpected error occurred","details":[]}'
    )

    assert infra is True
    assert kind == "infra"


def test_classify_failure_marks_authentication_failures_as_infra() -> None:
    infra, kind = classify_failure(
        'Authentication failed: {"error":"http_error","message":"Authentication failed for openai. Check credentials in Settings or environment.","details":[]}'
    )

    assert infra is True
    assert kind == "infra"


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
            used_tool_names=[],
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
            used_tool_names=[],
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
            used_tool_names=["precision_code_search"],
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
    assert "precision_code_search" in report


def test_benchmark_case_battery_is_stable() -> None:
    case_ids = [case.case_id for case in get_jenny_benchmark_cases()]
    assert case_ids == [
        "ready_task_dispatch",
        "same_task_overlap",
        "cleanup_blocks_closeout",
        "session_patience_quiet",
        "stalled_session_reconcile",
        "workspace_inspection_gate",
        "precision_search_architecture",
        "precision_search_live_lookup",
    ]


async def test_run_one_attempt_disables_response_cache(tmp_path: Path) -> None:
    from scripts.run_jenny_model_benchmark import _run_one_attempt

    captured_kwargs: dict[str, object] = {}

    class FakeClient:
        async def complete(self, **kwargs):
            captured_kwargs.update(kwargs)
            return SimpleNamespace(
                content=(
                    '{"case_id":"ready_task_dispatch","primary_action":"dispatch",'
                    '"should_dispatch":true,"should_close":false,'
                    '"confidence":"high","summary":"Task is ready to dispatch."}'
                ),
                session_id="sess-1",
                provider="claude",
                model="claude-sonnet-4-6",
                turns=1,
                tool_calls_count=0,
                usage=SimpleNamespace(
                    input_tokens=100,
                    output_tokens=20,
                    total_tokens=120,
                ),
            )

    with patch(
        "scripts.run_jenny_model_benchmark._fetch_used_tool_names",
        new=AsyncMock(return_value=[]),
    ):
        attempt = await _run_one_attempt(
            client=FakeClient(),
            benchmark_id="bench-1",
            project_id="persona-sandbox",
            model_id="claude-sonnet-4-6",
            case_id="ready_task_dispatch",
            run_number=1,
            working_root=tmp_path,
            timeout_seconds=30.0,
            keep_workdirs=False,
            use_memory=False,
            memory_group_id="benchmark:bench-1",
        )

    assert attempt.passed is True
    assert captured_kwargs["enable_caching"] is False
    assert captured_kwargs["skip_cache"] is True
    assert captured_kwargs["disable_agent_fallbacks"] is True
    assert captured_kwargs["response_format"]["type"] == "json_object"


def test_precision_search_case_prompt_requires_specific_tool() -> None:
    case = get_case_by_id("precision_search_live_lookup")

    prompt = case.build_prompt()

    assert "precision_code_search" in prompt
    assert "first code-navigation step" in prompt
    assert "Do not rely on read_file, bash, or assumptions" in prompt


def test_validate_case_project_requirements_rejects_wrong_project() -> None:
    from scripts.run_jenny_model_benchmark import _validate_case_project_requirements

    with pytest.raises(ValueError, match="precision_search_live_lookup"):
        _validate_case_project_requirements(["precision_search_live_lookup"], "persona-sandbox")
