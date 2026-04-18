"""Tests for persona model benchmark helpers."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from scripts.persona_benchmark_cases import (
    DEFAULT_PERSONA_BENCHMARK_MODELS,
    get_case_by_id,
    get_persona_benchmark_cases,
    get_persona_improvement_case_ids,
    prepare_case_workspace,
    suggest_suite_id,
)
from scripts.persona_benchmark_eval import (
    PersonaBenchmarkAttempt,
    classify_failure,
    parse_benchmark_json,
    score_attempt,
    summarize_attempts,
)
from scripts.persona_benchmark_report import generate_markdown_report


def test_default_model_roster_includes_seven_configured_candidates() -> None:
    assert DEFAULT_PERSONA_BENCHMARK_MODELS == [
        "codex/gpt-5.4",
        "codex/gpt-5.3-codex",
        "codex/gpt-5.3-codex-spark",
        "codex/gpt-5.2-codex",
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
    assert "Set `should_dispatch=true` only when `primary_action` is `dispatch`" in prompt
    assert "Use `monitor` for an existing same-task work lane" in prompt


def test_suggest_suite_id_uses_shared_case_family() -> None:
    suite_id = suggest_suite_id(
        ["session_patience_quiet", "session_patience_recent_progress", "stalled_session_reconcile"]
    )

    assert suite_id == "persona-suite-session-patience"


def test_suggest_suite_id_returns_none_for_mixed_case_families() -> None:
    suite_id = suggest_suite_id(["ready_task_dispatch", "feedback_triage_hotspot"])

    assert suite_id is None


def test_suggest_suite_id_uses_persona_improvement_suite_for_stable_battery() -> None:
    suite_id = suggest_suite_id(get_persona_improvement_case_ids())

    assert suite_id == "persona-suite-self-improvement"


def test_parse_benchmark_json_strips_code_fences() -> None:
    parsed, error = parse_benchmark_json(
        """```json
        {"case_id":"ready_task_dispatch","primary_action":"dispatch","should_dispatch":true,"should_close":false,"confidence":"high","summary":"ready"}
        ```"""
    )

    assert error is None
    assert parsed is not None
    assert parsed["primary_action"] == "dispatch"


def test_parse_benchmark_json_extracts_fenced_json_after_preamble() -> None:
    parsed, error = parse_benchmark_json(
        """The evidence is unambiguous.

```json
{"case_id":"ready_task_dispatch","primary_action":"dispatch","should_dispatch":true,"should_close":false,"confidence":"high","summary":"ready"}
```"""
    )

    assert error is None
    assert parsed is not None
    assert parsed["case_id"] == "ready_task_dispatch"


def test_parse_benchmark_json_strips_leading_narration_tags() -> None:
    parsed, error = parse_benchmark_json(
        """[[P:started:reviewing benchmark scenario]][[P:decision:reconcile now]]
{"case_id":"feedback_triage_hotspot","primary_action":"reconcile","should_dispatch":false,"should_close":false,"confidence":"high","summary":"Reconcile the operating checklist before dispatching new work."}"""
    )

    assert error is None
    assert parsed is not None
    assert parsed["case_id"] == "feedback_triage_hotspot"
    assert parsed["primary_action"] == "reconcile"


def test_parse_benchmark_json_tolerates_interleaved_narration_and_citations() -> None:
    parsed, error = parse_benchmark_json(
        """[[P:started:checking the benchmark surface]] Applied: [M:b901dcc9]
[[P:decision:reconcile the routing layer first]] Applied: [M:17449124]
{"case_id":"memory_routing_reconsideration","primary_action":"reconcile","should_dispatch":false,"should_close":false,"confidence":"high","summary":"Reconcile memory routing before dispatching more work."}"""
    )

    assert error is None
    assert parsed is not None
    assert parsed["case_id"] == "memory_routing_reconsideration"
    assert parsed["primary_action"] == "reconcile"


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


def test_score_attempt_backfills_identity_for_infra_failures() -> None:
    case = get_case_by_id("ready_task_dispatch")

    attempt = score_attempt(
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
        failure_detail="All connection attempts failed",
    )

    assert attempt.provider == "codex"
    assert attempt.effective_model == "codex/gpt-5.4"
    assert attempt.requested_model == "codex/gpt-5.4"
    assert attempt.infra_failure is True
    assert attempt.failure_kind == "infra"


def test_score_attempt_classifies_empty_content_as_infra() -> None:
    case = get_case_by_id("ready_task_dispatch")

    attempt = score_attempt(
        case=case,
        model_id="codex/gpt-5.4",
        run_number=1,
        latency_ms=60000,
        content="",
        session_id=None,
        provider=None,
        effective_model=None,
        fallback_used=False,
        turns=1,
        tool_calls_count=0,
        used_tool_names=[],
        input_tokens=0,
        output_tokens=0,
        total_tokens=0,
    )

    assert attempt.infra_failure is True
    assert attempt.failure_kind == "infra"
    assert attempt.failure_detail == "empty_model_response"
    assert attempt.passed is False


def test_score_attempt_classifies_whitespace_only_content_as_infra() -> None:
    case = get_case_by_id("ready_task_dispatch")

    attempt = score_attempt(
        case=case,
        model_id="codex/gpt-5.3-codex-spark",
        run_number=2,
        latency_ms=60000,
        content="\n\n  \n",
        session_id=None,
        provider=None,
        effective_model=None,
        fallback_used=False,
        turns=1,
        tool_calls_count=0,
        used_tool_names=[],
        input_tokens=0,
        output_tokens=0,
        total_tokens=0,
    )

    assert attempt.infra_failure is True
    assert attempt.failure_kind == "infra"
    assert attempt.failure_detail == "empty_model_response"


def test_build_persistence_payload_captures_run_and_snapshot_metadata() -> None:
    from scripts.persona_benchmark_eval import PersonaBenchmarkRun
    from scripts.persona_benchmark_persistence import build_persistence_payload

    attempt = PersonaBenchmarkAttempt(
        model_id="codex/gpt-5.4",
        case_id="session_patience_quiet",
        run_number=1,
        latency_ms=1200,
        session_id="sess-1",
        provider="openai",
        effective_model="codex/gpt-5.4",
        requested_model="codex/gpt-5.4",
        content='{"case_id":"session_patience_quiet"}',
        parsed={
            "case_id": "session_patience_quiet",
            "primary_action": "wait",
            "should_dispatch": False,
            "should_close": False,
            "confidence": "high",
            "summary": "Active session is quiet but healthy.",
        },
        schema_valid=True,
        correctness_score=1.0,
        tool_requirement_met=True,
        composite_score=100.0,
        passed=True,
        fallback_used=False,
        turns=2,
        tool_calls_count=1,
        used_tool_names=["query_sessions"],
        input_tokens=100,
        output_tokens=20,
        total_tokens=120,
    )
    run = PersonaBenchmarkRun(
        benchmark_id="persona-benchmark-aaaa1111",
        project_id="agent-hub",
        models=["codex/gpt-5.4"],
        case_ids=["session_patience_quiet"],
        runs_per_case=1,
        started_at="2026-03-11T12:00:00Z",
        completed_at="2026-03-11T12:05:00Z",
        attempts=[attempt],
        summaries=summarize_attempts([attempt]),
    )

    payload = build_persistence_payload(
        run,
        agent_slug="persona",
        suite_id="persona-patience",
        run_kind="benchmark",
        use_memory=True,
        seed=42,
        config_snapshot={
            "primary_model_id": "codex/gpt-5.4",
            "benchmark_task_type": "heartbeat",
            "thinking_level": "medium",
            "heartbeat_prompt": {
                "slug": "persona-heartbeat-instructions",
                "updated_at": "2026-03-11T11:16:06Z",
                "content_hash": "abcd1234",
            },
        },
        experiment={
            "experiment_key": "persona-patience-ab",
            "name": "Persona patience A/B",
            "cohort": "candidate",
            "min_runs_per_cohort": 4,
        },
    )

    assert payload["benchmark_id"] == "persona-benchmark-aaaa1111"
    assert payload["suite_id"] == "persona-patience"
    assert payload["run_kind"] == "benchmark"
    assert payload["attempt_count"] == 1
    assert payload["passed_attempt_count"] == 1
    assert payload["avg_score"] == 100.0
    assert payload["pass_rate"] == 100.0
    config_snapshot = payload["config_snapshot"]
    experiment = payload["experiment"]
    metadata = payload["metadata"]
    attempts = payload["attempts"]
    assert isinstance(config_snapshot, dict)
    assert isinstance(experiment, dict)
    assert isinstance(metadata, dict)
    assert isinstance(attempts, list)
    efficiency = metadata["efficiency"]
    assert isinstance(efficiency, dict)
    first_attempt = attempts[0]
    assert isinstance(first_attempt, dict)
    assert config_snapshot["thinking_level"] == "medium"
    assert config_snapshot["benchmark_task_type"] == "heartbeat"
    assert experiment["experiment_key"] == "persona-patience-ab"
    assert experiment["cohort"] == "candidate"
    assert efficiency["avg_total_tokens"] == 120.0
    assert efficiency["avg_turns"] == 2.0
    assert efficiency["avg_tool_calls"] == 1.0
    assert first_attempt["case_id"] == "session_patience_quiet"
    assert first_attempt["primary_action"] == "wait"


def test_derive_suite_id_prefers_family_name_for_related_cases() -> None:
    from scripts.run_persona_model_benchmark import derive_suite_id

    suite_id = derive_suite_id(
        ["session_patience_recent_progress", "stalled_session_reconcile", "session_patience_quiet"]
    )

    assert suite_id == "persona-suite-session-patience"


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


def test_score_attempt_accepts_summary_term_alternatives() -> None:
    case = get_case_by_id("dead_code_cleanup_followthrough")

    attempt = score_attempt(
        case=case,
        model_id="codex/gpt-5.4",
        run_number=1,
        latency_ms=700,
        content=(
            '{"case_id":"dead_code_cleanup_followthrough","primary_action":"dispatch",'
            '"should_dispatch":true,"should_close":false,'
            '"confidence":"high","summary":"Dispatch follow-through cleanup now to remove the unused compatibility shim and orphaned fields."}'
        ),
        session_id="sess-dead",
        provider="codex",
        effective_model="codex/gpt-5.4",
        fallback_used=False,
        turns=1,
        tool_calls_count=0,
        used_tool_names=[],
        input_tokens=50,
        output_tokens=20,
        total_tokens=70,
    )

    assert attempt.passed is True


def test_score_attempt_accepts_benchmark_summary_alternative() -> None:
    case = get_case_by_id("model_config_reconsideration")

    attempt = score_attempt(
        case=case,
        model_id="codex/gpt-5.4",
        run_number=1,
        latency_ms=800,
        content=(
            '{"case_id":"model_config_reconsideration","primary_action":"reconcile",'
            '"should_dispatch":false,"should_close":false,'
            '"confidence":"high","summary":"Reconcile model selection now because fresh evidence shows the current primary is underperforming on governance-heavy work."}'
        ),
        session_id="sess-model",
        provider="codex",
        effective_model="codex/gpt-5.4",
        fallback_used=False,
        turns=1,
        tool_calls_count=2,
        used_tool_names=["manage_model_config", "review_agent_performance"],
        input_tokens=55,
        output_tokens=22,
        total_tokens=77,
    )

    assert attempt.passed is True


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


def test_precision_live_lookup_accepts_bound_shared_summary_language() -> None:
    case = get_case_by_id("precision_search_live_lookup")

    attempt = score_attempt(
        case=case,
        model_id="codex/gpt-5.4",
        run_number=1,
        latency_ms=700,
        content=(
            '{"case_id":"precision_search_live_lookup","primary_action":"dispatch",'
            '"should_dispatch":true,"should_close":false,'
            '"confidence":"high","summary":"precision_code_search already exists and is bound in Agent Hub\'s shared executor registry for project-scoped/persona use, so the persona should dispatch follow-on adoption work rather than block on core tool implementation."}'
        ),
        session_id="sess-6",
        provider="codex",
        effective_model="codex/gpt-5.4",
        fallback_used=False,
        turns=1,
        tool_calls_count=1,
        used_tool_names=["precision_code_search"],
        input_tokens=80,
        output_tokens=18,
        total_tokens=98,
    )

    assert attempt.passed is True
    assert attempt.failure_detail is None


def test_score_attempt_accepts_signal_summary_alternative() -> None:
    case = get_case_by_id("model_config_reconsideration")

    attempt = score_attempt(
        case=case,
        model_id="codex/gpt-5.4",
        run_number=1,
        latency_ms=900,
        content=(
            '{"case_id":"model_config_reconsideration","primary_action":"reconcile",'
            '"should_dispatch":false,"should_close":false,'
            '"confidence":"high","summary":"Reconcile model selection now because the current primary '
            'keeps missing tool-heavy governance work while another configured model shows stronger success signals."}'
        ),
        session_id="sess-11",
        provider="openai",
        effective_model="codex/gpt-5.4",
        fallback_used=False,
        turns=3,
        tool_calls_count=2,
        used_tool_names=["manage_model_config", "review_agent_performance"],
        input_tokens=100,
        output_tokens=35,
        total_tokens=135,
    )

    assert attempt.passed is True
    assert attempt.failure_detail is None


def test_score_attempt_accepts_wait_alternative_intervene() -> None:
    """Regression test: 'intervene' in summary should satisfy the 'wait' term."""
    case = get_case_by_id("session_patience_recent_progress")

    attempt = score_attempt(
        case=case,
        model_id="claude-opus-4-6",
        run_number=1,
        latency_ms=9000,
        content=(
            '{"case_id":"session_patience_recent_progress","primary_action":"wait",'
            '"should_dispatch":false,"should_close":false,'
            '"confidence":"high","summary":"Session is active with recent progress '
            'and only 2.5 minutes of quiet while composing its next step '
            '\\u2014 no reason to intervene."}'
        ),
        session_id="sess-wait",
        provider="claude",
        effective_model="claude-opus-4-6",
        fallback_used=False,
        turns=1,
        tool_calls_count=0,
        used_tool_names=[],
        input_tokens=80,
        output_tokens=30,
        total_tokens=110,
    )

    assert attempt.passed is True
    assert attempt.correctness_score == 1.0
    assert attempt.failure_detail is None


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


@pytest.mark.parametrize(
    "detail",
    [
        "500: Completion cancelled unexpectedly.",
        "sdk cancelled",
        "tool loop cancelled",
        "finalize cancelled",
        "partial store cancelled",
        "Claude SDK idle watchdog still armed during iterator unwind",
    ],
)
def test_classify_failure_marks_runtime_cancellation_signatures_as_infra(detail: str) -> None:
    infra, kind = classify_failure(detail)

    assert infra is True
    assert kind == "infra"


def test_summarize_attempts_ranks_by_score_then_reliability() -> None:
    attempts = [
        PersonaBenchmarkAttempt(
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
        PersonaBenchmarkAttempt(
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


def test_summarize_attempts_prefers_fewer_tool_calls_when_scores_tie() -> None:
    attempts = [
        PersonaBenchmarkAttempt(
            model_id="model-a",
            case_id="c1",
            run_number=1,
            latency_ms=1000,
            composite_score=100.0,
            correctness_score=1.0,
            passed=True,
            total_tokens=120,
            turns=2,
            tool_calls_count=3,
            used_tool_names=["read_file", "query_sessions", "manage_tasks"],
        ),
        PersonaBenchmarkAttempt(
            model_id="model-b",
            case_id="c1",
            run_number=1,
            latency_ms=1000,
            composite_score=100.0,
            correctness_score=1.0,
            passed=True,
            total_tokens=80,
            turns=1,
            tool_calls_count=1,
            used_tool_names=["manage_tasks"],
        ),
    ]

    summaries = summarize_attempts(attempts)

    assert [summary.model_id for summary in summaries] == ["model-b", "model-a"]


def test_summarize_attempts_ignores_infra_failures_in_scores() -> None:
    attempts = [
        PersonaBenchmarkAttempt(
            model_id="model-a",
            case_id="c1",
            run_number=1,
            latency_ms=1000,
            composite_score=0.0,
            correctness_score=0.0,
            passed=False,
            infra_failure=True,
            failure_kind="infra",
            failure_detail="All connection attempts failed",
            total_tokens=0,
            turns=0,
            tool_calls_count=0,
            used_tool_names=[],
        ),
        PersonaBenchmarkAttempt(
            model_id="model-a",
            case_id="c1",
            run_number=2,
            latency_ms=900,
            composite_score=100.0,
            correctness_score=1.0,
            passed=True,
            total_tokens=90,
            turns=1,
            tool_calls_count=0,
            used_tool_names=[],
        ),
    ]

    summary = summarize_attempts(attempts)[0]

    assert summary.avg_composite_score == 100.0
    assert summary.pass_rate == 1.0
    assert summary.infra_failures == 1


def test_generate_markdown_report_includes_ranking_table() -> None:
    attempts = [
        PersonaBenchmarkAttempt(
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
    from scripts.persona_benchmark_eval import PersonaBenchmarkRun

    run = PersonaBenchmarkRun(
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

    assert "# Persona Model Benchmark" in report
    assert "| Rank | Model | Avg Score |" in report
    assert "`model-a`" in report
    assert "precision_code_search" in report


def test_benchmark_run_to_dict_includes_failing_attempts() -> None:
    attempts = [
        PersonaBenchmarkAttempt(
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
        PersonaBenchmarkAttempt(
            model_id="model-a",
            case_id="c2",
            run_number=1,
            latency_ms=1200,
            composite_score=83.0,
            correctness_score=0.8,
            passed=False,
            failure_kind="model",
            failure_detail="wrong_fields: primary_action",
            total_tokens=110,
            turns=1,
            tool_calls_count=0,
            used_tool_names=[],
        ),
    ]
    summaries = summarize_attempts(attempts)
    from scripts.persona_benchmark_eval import PersonaBenchmarkRun

    run = PersonaBenchmarkRun(
        benchmark_id="bench-2",
        project_id="persona-sandbox",
        models=["model-a"],
        case_ids=["c1", "c2"],
        runs_per_case=1,
        started_at="2026-03-11T00:00:00+00:00",
        completed_at="2026-03-11T00:01:00+00:00",
        attempts=attempts,
        summaries=summaries,
    )

    payload = run.to_dict()

    assert len(payload["attempts"]) == 2
    assert len(payload["failing_attempts"]) == 1
    assert payload["failing_attempts"][0]["case_id"] == "c2"
    assert payload["failing_attempts"][0]["failure_detail"] == "wrong_fields: primary_action"


async def test_run_one_attempt_disables_response_cache(tmp_path: Path) -> None:
    from scripts.persona_benchmark_runner import _run_one_attempt

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
        "scripts.persona_benchmark_runner._fetch_used_tool_names",
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
            memory_variant_override="MINIMAL",
            task_type="heartbeat",
        )

    assert attempt.passed is True
    assert captured_kwargs["enable_caching"] is False
    assert captured_kwargs["skip_cache"] is True
    assert captured_kwargs["memory_variant_override"] == "MINIMAL"
    assert captured_kwargs["task_type"] == "heartbeat"
    assert captured_kwargs["disable_agent_fallbacks"] is True
    response_format = captured_kwargs["response_format"]
    assert isinstance(response_format, dict)
    assert response_format["type"] == "json_object"


@pytest.mark.asyncio
async def test_persist_run_promotes_memory_variant_on_candidate_win() -> None:
    from scripts.persona_benchmark_eval import PersonaBenchmarkRun
    from scripts.persona_benchmark_persistence import _persist_run
    from scripts.run_persona_model_benchmark import _build_parser, derive_suite_id

    attempt = PersonaBenchmarkAttempt(
        model_id="codex/gpt-5.4",
        case_id="ready_task_dispatch",
        run_number=1,
        latency_ms=100,
        composite_score=100.0,
        correctness_score=1.0,
        passed=True,
        total_tokens=50,
        turns=1,
        tool_calls_count=0,
        used_tool_names=[],
    )
    run = PersonaBenchmarkRun(
        benchmark_id="bench-1",
        project_id="agent-hub",
        models=["codex/gpt-5.4"],
        case_ids=["ready_task_dispatch"],
        runs_per_case=1,
        started_at="2026-03-11T00:00:00+00:00",
        completed_at="2026-03-11T00:01:00+00:00",
        attempts=[attempt],
        summaries=summarize_attempts([attempt]),
    )
    args = _build_parser().parse_args([
        "--experiment-key", "memory-exp-1",
        "--experiment-cohort", "candidate",
        "--memory-variant-override", "ENHANCED",
        "--promote-on-win",
    ])

    with (
        patch(
            "scripts.persona_benchmark_persistence.capture_benchmark_config_snapshot",
            new=AsyncMock(return_value={"primary_model_id": "codex/gpt-5.4"}),
        ),
        patch(
            "scripts.persona_benchmark_persistence.persist_benchmark_payload",
            new=AsyncMock(return_value="run-1"),
        ),
        patch(
            "scripts.persona_benchmark_persistence.get_benchmark_experiment_summary_by_key",
            new=AsyncMock(return_value={"decision": "promote", "name": "exp", "decision_reason": "candidate_outperforms_baseline", "baseline": {"run_count": 3, "avg_score": 80.0, "avg_pass_rate": 50.0}, "candidate": {"run_count": 3, "avg_score": 95.0, "avg_pass_rate": 80.0}, "score_delta": {"mean_delta": 15.0, "ci_low": 5.0, "ci_high": 20.0}, "pass_rate_delta": {"mean_delta": 30.0, "ci_low": 10.0, "ci_high": 40.0}}),
        ),
        patch(
            "scripts.persona_benchmark_persistence.set_active_memory_variant",
            new=AsyncMock(),
        ) as mock_promote,
    ):
        await _persist_run(run, args, derive_suite_id(["ready_task_dispatch"]))

    mock_promote.assert_awaited_once_with("ENHANCED")


def test_precision_search_case_prompt_requires_specific_tool() -> None:
    case = get_case_by_id("precision_search_live_lookup")

    prompt = case.build_prompt()

    assert "precision_code_search" in prompt
    assert "first code-navigation step" in prompt
    assert "Do not rely on read_file, bash, or assumptions" in prompt


def test_web_research_case_requires_shared_web_tools() -> None:
    case = get_case_by_id("web_research_stack_lookup")

    prompt = case.build_prompt()

    assert "research_web" in prompt
    assert "search_web" in prompt
    assert "fetch_web_page" in prompt
    assert "Cloudflare Markdown for Agents" in prompt
    assert case.required_tool_names == ("search_web", "fetch_web_page")


def test_web_research_case_accepts_normalized_shared_tool_names() -> None:
    case = get_case_by_id("web_research_stack_lookup")

    attempt = score_attempt(
        case=case,
        model_id="claude-sonnet-4-6",
        run_number=1,
        latency_ms=1200,
        content=(
            '{"case_id":"web_research_stack_lookup","primary_action":"dispatch",'
            '"should_dispatch":true,"should_close":false,'
            '"confidence":"high","summary":"Dispatch adoption of the shared markdown-first web research stack now instead of building another fetcher."}'
        ),
        session_id="sess-web",
        provider="claude",
        effective_model="claude-sonnet-4-6",
        fallback_used=False,
        turns=3,
        tool_calls_count=2,
        used_tool_names=[
            "mcp__agent-hub__search_web",
            "mcp__agent-hub__fetch_web_page",
        ],
        input_tokens=120,
        output_tokens=30,
        total_tokens=150,
    )

    assert attempt.passed is True
    assert attempt.tool_requirement_met is True


def test_web_research_case_accepts_research_web_as_equivalent_coverage() -> None:
    case = get_case_by_id("web_research_stack_lookup")

    attempt = score_attempt(
        case=case,
        model_id="claude-sonnet-4-6",
        run_number=1,
        latency_ms=900,
        content=(
            '{"case_id":"web_research_stack_lookup","primary_action":"dispatch",'
            '"should_dispatch":true,"should_close":false,'
            '"confidence":"high","summary":"Dispatch adoption of the shared markdown-first web research stack now instead of building another fetcher."}'
        ),
        session_id="sess-web-1call",
        provider="claude",
        effective_model="claude-sonnet-4-6",
        fallback_used=False,
        turns=2,
        tool_calls_count=1,
        used_tool_names=["mcp__agent-hub__research_web"],
        input_tokens=110,
        output_tokens=28,
        total_tokens=138,
    )

    assert attempt.passed is True
    assert attempt.tool_requirement_met is True


def test_validate_case_project_requirements_rejects_wrong_project() -> None:
    from scripts.run_persona_model_benchmark import _validate_case_project_requirements

    with pytest.raises(ValueError, match="precision_search_live_lookup"):
        _validate_case_project_requirements(["precision_search_live_lookup"], "persona-sandbox")


def test_feedback_triage_case_requires_manage_feedback_tool() -> None:
    case = get_case_by_id("feedback_triage_hotspot")

    prompt = case.build_prompt()

    assert "manage_feedback" in prompt
    assert case.required_tool_names == ("manage_feedback",)


def test_global_git_hygiene_case_requires_dirty_repo_classification() -> None:
    case = get_case_by_id("global_git_hygiene_classification")

    prompt = case.build_prompt()

    assert "declare clean idle" in prompt
    assert case.expected["primary_action"] == "reconcile"
    assert "dirty" in case.required_summary_terms


def test_repeated_blocker_case_requires_fix_work_language() -> None:
    case = get_case_by_id("repeated_blocker_fix_work")

    prompt = case.build_prompt()

    assert "4 consecutive heartbeats" in prompt
    assert case.expected["primary_action"] == "reconcile"
    assert "fix" in case.required_summary_terms


def test_partial_blocker_churn_case_requires_partial_fix_language() -> None:
    case = get_case_by_id("partial_blocker_churn_fix_work")

    prompt = case.build_prompt()

    assert "6 consecutive heartbeats ended partial" in prompt
    assert case.expected["primary_action"] == "reconcile"
    assert "partial" in case.required_summary_terms
    assert "fix" in case.required_summary_terms


def test_failed_active_lane_recovery_case_requires_recovery_before_dispatch() -> None:
    case = get_case_by_id("failed_active_lane_recovery_before_dispatch")

    prompt = case.build_prompt()

    assert "recover the failed active lanes first" in prompt
    assert case.expected["primary_action"] == "reconcile"
    assert "failed" in case.required_summary_terms
    assert "recover" in case.required_summary_terms


def test_blocker_fix_task_case_requires_readying_the_fix_task() -> None:
    case = get_case_by_id("blocker_fix_task_must_be_shaped_ready")

    prompt = case.build_prompt()

    assert "task-40efc3b9|pending COMPLETE_READY:no" in prompt
    assert case.expected["primary_action"] == "reconcile"
    assert "ready" in case.required_summary_terms
    assert "shape" in case.required_summary_terms


def test_failed_task_record_recovery_case_requires_recovery_before_dispatch() -> None:
    case = get_case_by_id("failed_task_record_recovery_before_dispatch")

    prompt = case.build_prompt()

    assert "recent failed task records first" in prompt
    assert case.expected["primary_action"] == "reconcile"
    assert "failed" in case.required_summary_terms
    assert "recover" in case.required_summary_terms


def test_failed_task_beats_unrelated_cleanup_case_prioritizes_failed_chain() -> None:
    case = get_case_by_id("failed_task_beats_unrelated_cleanup")

    prompt = case.build_prompt()

    assert "recent failed task in a writable project should outrank unrelated cleanup" in case.description.lower()
    assert "What should the persona follow first?" in prompt
    assert case.expected["primary_action"] == "reconcile"
    assert "agent-hub" in case.required_summary_terms
    assert "recover" in case.required_summary_terms


def test_failed_task_inspection_case_requires_same_heartbeat_recovery_action() -> None:
    case = get_case_by_id("failed_task_inspection_requires_recovery_action")

    prompt = case.build_prompt()

    assert "task-1025819f|failed COMPLETE_READY:no SYNC_SKIPS:1.1:no-steps" in prompt
    assert case.expected["primary_action"] == "reconcile"
    assert "failed" in case.required_summary_terms
    assert "recover" in case.required_summary_terms


def test_cli_usage_error_case_requires_help_recovery_language() -> None:
    case = get_case_by_id("cli_usage_error_requires_help_recovery")

    prompt = case.build_prompt()

    assert "st cleanup status --project agent-hub" in prompt
    assert "--help" in prompt
    assert case.expected["primary_action"] == "reconcile"
    assert "help" in case.required_summary_terms
    assert "recover" in case.required_summary_terms


def test_stale_reviewer_path_case_requires_verified_path_language() -> None:
    case = get_case_by_id("stale_reviewer_path_requires_verification")

    prompt = case.build_prompt()

    assert "File not found" in prompt
    assert "backend/app/workflows/_heartbeat_data.py" in prompt
    assert case.expected["primary_action"] == "reconcile"
    assert "verify" in case.required_summary_terms
    assert "path" in case.required_summary_terms


def test_performance_honing_case_requires_instruction_and_performance_tools() -> None:
    case = get_case_by_id("performance_review_honing")

    prompt = case.build_prompt()

    assert "review_agent_performance" in prompt
    assert "read_heartbeat_instructions" in prompt
    assert case.required_tool_names == (
        "review_agent_performance",
        "read_heartbeat_instructions",
    )


def test_model_config_reconsideration_case_requires_model_tools() -> None:
    case = get_case_by_id("model_config_reconsideration")

    prompt = case.build_prompt()

    assert "manage_model_config" in prompt
    assert "review_agent_performance" in prompt
    assert case.required_tool_names == (
        "manage_model_config",
        "review_agent_performance",
    )


def test_memory_routing_reconsideration_case_requires_memory_tooling() -> None:
    case = get_case_by_id("memory_routing_reconsideration")

    prompt = case.build_prompt()

    assert "manage_model_config" in prompt
    assert "memory routing" in prompt
    assert case.required_tool_names == ("manage_model_config",)


def test_rebuild_rule_reconsideration_case_requires_mandate_language() -> None:
    case = get_case_by_id("rebuild_rule_reconsideration")

    prompt = case.build_prompt()

    assert "manage_model_config" in prompt
    assert "rebuild.sh agent-hub" in prompt
    assert "universal workflow rule" in prompt
    assert case.required_tool_names == ("manage_model_config",)


def test_recent_progress_session_case_requires_wait_language() -> None:
    case = get_case_by_id("session_patience_recent_progress")

    attempt = score_attempt(
        case=case,
        model_id="codex/gpt-5.4",
        run_number=1,
        latency_ms=650,
        content=(
            '{"case_id":"session_patience_recent_progress","primary_action":"wait",'
            '"should_dispatch":false,"should_close":false,'
            '"confidence":"high","summary":"Recent progress is still visible, so wait rather than interrupt the session."}'
        ),
        session_id="sess-progress",
        provider="codex",
        effective_model="codex/gpt-5.4",
        fallback_used=False,
        turns=1,
        tool_calls_count=0,
        used_tool_names=[],
        input_tokens=42,
        output_tokens=20,
        total_tokens=62,
    )

    assert attempt.passed is True


def test_same_task_recent_progress_case_requires_monitor_language() -> None:
    case = get_case_by_id("same_task_recent_progress")

    attempt = score_attempt(
        case=case,
        model_id="claude-sonnet-4-6",
        run_number=1,
        latency_ms=700,
        content=(
            '{"case_id":"same_task_recent_progress","primary_action":"monitor",'
            '"should_dispatch":false,"should_close":false,'
            '"confidence":"high","summary":"Monitor the active lane because recent progress is still coming through."}'
        ),
        session_id="sess-progress-task",
        provider="claude",
        effective_model="claude-sonnet-4-6",
        fallback_used=False,
        turns=1,
        tool_calls_count=0,
        used_tool_names=[],
        input_tokens=44,
        output_tokens=18,
        total_tokens=62,
    )

    assert attempt.passed is True


def test_same_task_recent_progress_accepts_supervise_language() -> None:
    case = get_case_by_id("same_task_recent_progress")

    attempt = score_attempt(
        case=case,
        model_id="codex/gpt-5.4",
        run_number=1,
        latency_ms=700,
        content=(
            '{"case_id":"same_task_recent_progress","primary_action":"monitor",'
            '"should_dispatch":false,"should_close":false,'
            '"confidence":"high","summary":"The same-task session shows recent progress, so I would supervise the existing work rather than redispatch it."}'
        ),
        session_id="sess-progress-supervise",
        provider="openai",
        effective_model="codex/gpt-5.4",
        fallback_used=False,
        turns=1,
        tool_calls_count=0,
        used_tool_names=[],
        input_tokens=44,
        output_tokens=18,
        total_tokens=62,
    )

    assert attempt.passed is True
    assert attempt.failure_detail is None


def test_review_request_case_requires_review_language_in_summary() -> None:
    case = get_case_by_id("review_request_routes_to_reviewer")

    attempt = score_attempt(
        case=case,
        model_id="codex/gpt-5.4",
        run_number=1,
        latency_ms=600,
        content=(
            '{"case_id":"review_request_routes_to_reviewer","primary_action":"dispatch",'
            '"should_dispatch":true,"should_close":false,'
            '"confidence":"high","summary":"Dispatch a review specialist and return findings first."}'
        ),
        session_id="sess-review",
        provider="codex",
        effective_model="codex/gpt-5.4",
        fallback_used=False,
        turns=1,
        tool_calls_count=0,
        used_tool_names=[],
        input_tokens=40,
        output_tokens=16,
        total_tokens=56,
    )

    assert attempt.passed is True


def test_review_request_accepts_review_only_summary_language() -> None:
    case = get_case_by_id("review_request_routes_to_reviewer")

    attempt = score_attempt(
        case=case,
        model_id="codex/gpt-5.4",
        run_number=1,
        latency_ms=600,
        content=(
            '{"case_id":"review_request_routes_to_reviewer","primary_action":"dispatch",'
            '"should_dispatch":true,"should_close":false,'
            '"confidence":"high","summary":"Dispatch a review specialist now because the task is review-only and should not go to a coding lane."}'
        ),
        session_id="sess-review-only",
        provider="openai",
        effective_model="codex/gpt-5.4",
        fallback_used=False,
        turns=1,
        tool_calls_count=0,
        used_tool_names=[],
        input_tokens=40,
        output_tokens=16,
        total_tokens=56,
    )

    assert attempt.passed is True
    assert attempt.failure_detail is None


def test_benchmark_case_battery_includes_honing_and_review_cases() -> None:
    case_ids = [case.case_id for case in get_persona_benchmark_cases()]

    assert case_ids == [
        "ready_task_dispatch",
        "scope_conflict_shared_plumbing",
        "same_task_overlap",
        "same_task_recent_progress",
        "snapshot_recover_not_rollback",
        "cleanup_blocks_closeout",
        "dead_code_cleanup_followthrough",
        "session_patience_quiet",
        "session_patience_recent_progress",
        "stalled_session_reconcile",
        "workspace_inspection_gate",
        "precision_search_architecture",
        "precision_search_live_lookup",
        "web_research_stack_lookup",
        "review_request_routes_to_reviewer",
        "feedback_triage_hotspot",
        "performance_review_honing",
        "model_config_reconsideration",
        "memory_routing_reconsideration",
        "rebuild_rule_reconsideration",
        "manual_project_access_block",
        "ghost_owner_lane_reconcile",
        "publish_failure_non_fast_forward",
        "global_git_hygiene_classification",
        "repeated_blocker_fix_work",
        "partial_blocker_churn_fix_work",
        "blocker_fix_task_must_be_shaped_ready",
        "failed_active_lane_recovery_before_dispatch",
        "failed_task_record_recovery_before_dispatch",
        "failed_task_beats_unrelated_cleanup",
        "failed_task_inspection_requires_recovery_action",
        "cli_usage_error_requires_help_recovery",
        "stale_reviewer_path_requires_verification",
    ]
