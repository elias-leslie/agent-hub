"""Tests for the persona honing loop helpers."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from scripts.completion_review_benchmark_eval import (
    CompletionReviewBenchmarkAttempt,
    CompletionReviewBenchmarkRun,
    summarize_completion_review_attempts,
)
from scripts.persona_benchmark_eval import (
    PersonaBenchmarkAttempt,
    PersonaBenchmarkRun,
    summarize_attempts,
)
from scripts.run_persona_honing_loop import (
    _build_improvement_prompt,
    _run_improvement_pass,
    run_honing_loop,
)


def _make_run(attempts: list[PersonaBenchmarkAttempt]) -> PersonaBenchmarkRun:
    return PersonaBenchmarkRun(
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


@pytest.fixture(autouse=True)
def _mock_persona_improvement_prompt():
    async def _require_prompt_content(slug: str) -> str:
        if slug == "persona-evolution-guidelines":
            return (
                "You are the persona reviewing your own benchmark results for honing iteration {iteration}.\n\n"
                "Your job is to improve your own operating model only where the evidence justifies it.\n"
                "Stay inside Jenny-improvement work: canonical prompts, memory, model/config, performance logging, and valid control-plane/runtime fixes.\n"
                "Do not create or dispatch project tasks.\n\n"
                "Benchmark ranking:\n"
                "{ranking_block}\n\n"
                "{failure_block}\n\n"
                "{persistent_block}\n\n"
                "{new_block}\n\n"
                "{resolved_block}\n\n"
                "Completion-review benchmark ranking:\n"
                "{review_ranking_block}\n\n"
                "{review_failure_block}\n\n"
                "{review_persistent_block}\n\n"
                "Recent improvement signals:\n"
                "{improvement_signals_block}\n\n"
                "Recent real-heartbeat field evidence:\n"
                "{field_signals_block}\n\n"
                "Reference heuristics to borrow when relevant:\n"
                "{reference_block}\n\n"
                "Required behavior:\n"
                "- Diagnose the canonical layer first: prompt, memory, config, truth pipeline, evaluator, or runtime.\n"
                "- Use `persona-evolution-guidelines` as the canonical Jenny improvement prompt and DB-backed prompts rather than Python prompt files.\n"
                "- When reviewing your own performance history, use agent_slug=\"persona\" rather than a display name string.\n"
                "- Use repeated issue clusters, benchmark decisions, and low-yield reference evidence to choose the smallest effective fix.\n"
                "- If model assignment looks implicated, inspect model/performance tools before changing config.\n"
                "- If memory routing looks implicated, inspect current agent memory config first and use manage_memory_tags for reference-tier retagging before editing heartbeat instructions.\n"
                "- If a specialist keeps missing universal workflow rules like rebuild.sh or dt, inspect mandate/guardrail exposure before retagging references.\n"
                "- Treat audience tags and reference inclusion as the memory-routing levers; do not paper over routing misses by inventing new mandates or guardrails.\n"
                "- Treat completion-review regressions as first-class evidence; inspect completion-review-prompt, completion-review-rules, or supervisor model config when reviewer cases fail.\n"
                "- If improvement signals show a recurring self-correction failure that this battery does not directly cover, call that out in next_focus as a benchmark coverage gap rather than overfitting the current prompt to an untested pattern.\n"
                "- Return JSON only with fields summary, changes_applied, next_focus, durable_learning_saved."
            )
        if slug == "persona-improvement-review":
            return (
                "You are reviewing a proposed Jenny self-improvement decision.\n\n"
                "Protected lab summary:\n"
                "{experiment_summary_block}\n\n"
                "Completion-review summary:\n"
                "{completion_review_block}\n\n"
                "Recent field evidence:\n"
                "{field_signals_block}\n\n"
                "Candidate change summary:\n"
                "{improvement_summary_block}\n\n"
                "Proposed automatic decision:\n"
                "- decision={proposed_decision}\n"
                "- reason={proposed_reason}\n\n"
                "Return JSON only with fields decision and reason."
            )
        raise AssertionError(f"unexpected prompt slug: {slug}")

    with patch("app.services.persona_prompt_service.require_prompt_content", new=_require_prompt_content):
        yield


@pytest.mark.asyncio
async def test_build_honing_prompt_includes_failure_clusters_and_reference_notes() -> None:
    run = _make_run(
        [
            PersonaBenchmarkAttempt(
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
            PersonaBenchmarkAttempt(
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

    prompt = await _build_improvement_prompt(
        run=run,
        iteration=2,
        previous_clusters=None,
        review_run=None,
        previous_review_clusters=None,
        improvement_signals=None,
        field_signals=None,
    )

    assert "feedback_triage_hotspot" in prompt
    assert "performance_review_honing" in prompt
    assert "Auto-Claude inspiration" in prompt
    assert "OpenClaw inspiration" in prompt
    assert "Do not create or dispatch project tasks." in prompt
    assert "memory routing" in prompt
    assert "manage_memory_tags" in prompt
    assert "rebuild.sh" in prompt


@pytest.mark.asyncio
async def test_build_honing_prompt_handles_clean_run() -> None:
    run = _make_run(
        [
            PersonaBenchmarkAttempt(
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

    prompt = await _build_improvement_prompt(
        run=run,
        iteration=1,
        previous_clusters=None,
        review_run=None,
        previous_review_clusters=None,
        improvement_signals=None,
        field_signals=None,
    )

    assert "Top failure clusters:\n- none" in prompt


@pytest.mark.asyncio
async def test_build_honing_prompt_includes_persistent_cluster_section() -> None:
    run = _make_run(
        [
            PersonaBenchmarkAttempt(
                model_id="codex/gpt-5.4",
                case_id="session_patience_recent_progress",
                run_number=1,
                latency_ms=500,
                composite_score=57.5,
                correctness_score=0.5,
                passed=False,
                failure_kind="model",
                failure_detail="wrong_fields: primary_action, should_dispatch",
                total_tokens=80,
                turns=1,
                tool_calls_count=0,
                used_tool_names=[],
            )
        ]
    )

    prompt = await _build_improvement_prompt(
        run=run,
        iteration=2,
        previous_clusters=[
            {
                "case_id": "session_patience_recent_progress",
                "failure_detail": "wrong_fields: primary_action, should_dispatch",
                "count": 1,
                "models": ["codex/gpt-5.4"],
                "avg_score": 57.5,
            }
        ],
        review_run=None,
        previous_review_clusters=None,
        improvement_signals=None,
        field_signals=None,
    )

    assert "Persistent unresolved clusters from the previous iteration" in prompt
    assert "session_patience_recent_progress" in prompt
    assert 'agent_slug="persona"' in prompt


class _FakeClient:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None


class _FakeImprovementClient:
    def __init__(self) -> None:
        self.kwargs: dict[str, object] | None = None

    async def complete(self, **kwargs):
        self.kwargs = kwargs
        return SimpleNamespace(
            session_id="sess-improve",
            content=(
                '{"summary":"tightened prompt","changes_applied":["edited heartbeat"],'
                '"next_focus":["rerun benchmark"],"durable_learning_saved":false}'
            ),
        )


class _FakeDecisionReviewClient:
    def __init__(self) -> None:
        self.kwargs: dict[str, object] | None = None

    async def complete(self, **kwargs):
        self.kwargs = kwargs
        return SimpleNamespace(
            session_id="sess-review",
            content='```json\n{"decision":"hold","reason":"review confirms hold"}\n```',
        )


def _passing_attempt(case_id: str) -> PersonaBenchmarkAttempt:
    return PersonaBenchmarkAttempt(
        model_id="codex/gpt-5.4",
        case_id=case_id,
        run_number=1,
        latency_ms=500,
        composite_score=100.0,
        correctness_score=1.0,
        passed=True,
        total_tokens=50,
        turns=1,
        tool_calls_count=0,
        used_tool_names=[],
    )


def _failing_attempt(case_id: str) -> PersonaBenchmarkAttempt:
    return PersonaBenchmarkAttempt(
        model_id="codex/gpt-5.4",
        case_id=case_id,
        run_number=1,
        latency_ms=500,
        composite_score=50.0,
        correctness_score=0.5,
        passed=False,
        failure_kind="model",
        failure_detail="wrong_fields: primary_action",
        total_tokens=50,
        turns=1,
        tool_calls_count=0,
        used_tool_names=[],
    )


def _benchmark_run(benchmark_id: str, attempts: list[PersonaBenchmarkAttempt]) -> PersonaBenchmarkRun:
    return PersonaBenchmarkRun(
        benchmark_id=benchmark_id,
        project_id="agent-hub",
        models=["codex/gpt-5.4"],
        case_ids=sorted({attempt.case_id for attempt in attempts}),
        runs_per_case=1,
        started_at="2026-03-11T00:00:00+00:00",
        completed_at="2026-03-11T00:01:00+00:00",
        attempts=attempts,
        summaries=summarize_attempts(attempts),
    )


def _review_passing_attempt(case_id: str) -> CompletionReviewBenchmarkAttempt:
    return CompletionReviewBenchmarkAttempt(
        model_id="claude-opus-4-6",
        case_id=case_id,
        run_number=1,
        latency_ms=450,
        composite_score=100.0,
        correctness_score=1.0,
        passed=True,
        turns=1,
        tool_calls_count=0,
        total_tokens=40,
    )


def _review_failing_attempt(case_id: str) -> CompletionReviewBenchmarkAttempt:
    return CompletionReviewBenchmarkAttempt(
        model_id="claude-opus-4-6",
        case_id=case_id,
        run_number=1,
        latency_ms=450,
        composite_score=40.0,
        correctness_score=0.4,
        passed=False,
        failure_kind="model",
        failure_detail="wrong_review_decision",
        turns=1,
        tool_calls_count=0,
        total_tokens=40,
    )


def _review_benchmark_run(
    benchmark_id: str,
    attempts: list[CompletionReviewBenchmarkAttempt],
) -> CompletionReviewBenchmarkRun:
    return CompletionReviewBenchmarkRun(
        benchmark_id=benchmark_id,
        project_id="agent-hub",
        models=["claude-opus-4-6"],
        case_ids=sorted({attempt.case_id for attempt in attempts}),
        runs_per_case=1,
        started_at="2026-03-11T00:00:00+00:00",
        completed_at="2026-03-11T00:01:00+00:00",
        attempts=attempts,
        summaries=summarize_completion_review_attempts(attempts),
    )


@pytest.mark.asyncio
async def test_run_improvement_pass_disables_memory_in_controlled_honing_loop() -> None:
    client = _FakeImprovementClient()
    run = _benchmark_run("bench-1", [_failing_attempt("session_patience_recent_progress")])

    with (
        patch(
            "scripts.persona_honing._experiment._fetch_used_tool_names",
            new=AsyncMock(return_value=["read_heartbeat_instructions"]),
        ),
        patch(
            "scripts.persona_honing._experiment._load_recent_improvement_signals",
            new=AsyncMock(return_value="## Repeated issues\n- persona [2x]: missed rebuild.sh"),
        ),
        patch(
            "app.services.persona_improvement.build_persona_heartbeat_field_digest",
            new=AsyncMock(return_value="- 3 recent real heartbeats; avg reliability 90.0%; critical issues 0."),
        ),
    ):
        session_id, content, tools, parsed = await _run_improvement_pass(
            client=client,
            project_id="agent-hub",
            iteration=1,
            run=run,
            previous_clusters=None,
            review_run=None,
            previous_review_clusters=None,
            timeout_seconds=5.0,
            working_root=Path("/tmp/persona-honing-test"),
        )

    assert session_id == "sess-improve"
    assert '"durable_learning_saved":false' in content
    assert tools == ["read_heartbeat_instructions"]
    assert parsed == {
        "summary": "tightened prompt",
        "changes_applied": ["edited heartbeat"],
        "next_focus": ["rerun benchmark"],
        "durable_learning_saved": False,
    }
    assert client.kwargs is not None
    assert client.kwargs["use_memory"] is False
    assert client.kwargs["agent_slug"] == "persona"
    assert "Recent improvement signals" in client.kwargs["messages"][0]["content"]
    assert "Recent real-heartbeat field evidence" in client.kwargs["messages"][0]["content"]
    assert "missed rebuild.sh" in client.kwargs["messages"][0]["content"]


@pytest.mark.asyncio
async def test_build_honing_prompt_includes_completion_review_surface() -> None:
    run = _benchmark_run("bench-1", [_failing_attempt("session_patience_recent_progress")])
    review_run = _review_benchmark_run(
        "review-1",
        [_review_failing_attempt("review_recent_progress_patience")],
    )

    prompt = await _build_improvement_prompt(
        run=run,
        iteration=2,
        review_run=review_run,
        previous_clusters=None,
        previous_review_clusters=[
            {
                "case_id": "review_recent_progress_patience",
                "failure_detail": "wrong_review_decision",
                "count": 1,
                "models": ["claude-opus-4-6"],
                "avg_score": 40.0,
            }
        ],
        improvement_signals=None,
        field_signals=None,
    )

    assert "Completion-review benchmark ranking" in prompt
    assert "Completion-review failure clusters" in prompt
    assert "Persistent completion-review clusters from the previous iteration" in prompt
    assert "completion-review-prompt" in prompt


@pytest.mark.asyncio
async def test_build_honing_prompt_includes_recent_improvement_signals() -> None:
    run = _benchmark_run("bench-1", [_failing_attempt("session_patience_recent_progress")])

    prompt = await _build_improvement_prompt(
        run=run,
        iteration=2,
        previous_clusters=None,
        review_run=None,
        previous_review_clusters=None,
        improvement_signals=(
            "# Improvement Signals\n\n"
            "## Repeated issues\n"
            "- persona [2x]: Heartbeat self-reflection signals: missing HEARTBEAT_OK/HEARTBEAT_ACTION prefix\n"
        ),
        field_signals="- 4 recent real heartbeats; avg reliability 89.0%; avg effectiveness 83.5%; critical issues 0.",
    )

    assert "Recent improvement signals" in prompt
    assert "Recent real-heartbeat field evidence" in prompt
    assert "Heartbeat self-reflection signals" in prompt
    assert "benchmark coverage gap" in prompt


def test_parse_improvement_content_tolerates_narration_and_citations() -> None:
    from scripts.persona_honing._response import parse_improvement_content

    parsed = parse_improvement_content(
        """[[P:started:reviewing improvement output]] Applied: [M:b901dcc9]
{"summary":"tightened benchmark phrasing","changes_applied":["logged performance note"],"next_focus":["rerun benchmark"],"durable_learning_saved":false}"""
    )

    assert parsed == {
        "summary": "tightened benchmark phrasing",
        "changes_applied": ["logged performance note"],
        "next_focus": ["rerun benchmark"],
        "durable_learning_saved": False,
    }


def test_parse_decision_review_content_tolerates_narration() -> None:
    from scripts.persona_honing._response import parse_decision_review_content

    parsed = parse_decision_review_content(
        """[[P:started:reviewing decision]] {"decision":"hold","reason":"field evidence suggests evaluator gap"}"""
    )

    assert parsed == {
        "decision": "hold",
        "reason": "field evidence suggests evaluator gap",
    }


@pytest.mark.asyncio
async def test_run_decision_review_uses_freeform_completion_and_parses_json() -> None:
    from scripts.persona_honing._experiment import _run_decision_review

    client = _FakeDecisionReviewClient()
    record = SimpleNamespace(
        summary="candidate improved same_task_overlap JSON hygiene",
        changes_applied=["tightened JSON-only precedence"],
        next_focus=["address primary_action contract drift"],
        improvement_parsed={
            "summary": "candidate improved same_task_overlap JSON hygiene",
            "changes_applied": ["tightened JSON-only precedence"],
            "next_focus": ["address primary_action contract drift"],
        },
        improvement_tools=[],
    )

    with (
        patch(
            "scripts.persona_honing._experiment.render_persona_improvement_decision_review_prompt",
            new=AsyncMock(return_value="review prompt"),
        ),
        patch(
            "app.services.persona_improvement.build_persona_heartbeat_field_digest",
            new=AsyncMock(return_value="- 4 recent real heartbeats; avg reliability 100.0%."),
        ),
    ):
        result = await _run_decision_review(
            client=client,
            iteration=1,
            experiment_key="exp-1234",
            project_id="agent-hub",
            timeout_seconds=60.0,
            working_root=Path("/tmp/persona-honing-test"),
            proposed_decision="hold",
            proposed_reason="no_clear_winner",
            experiment_summary={"decision": "hold", "decision_reason": "no_clear_winner"},
            review_summary=None,
            field_snapshot={"review_gate": {"needs_review": False, "summary": "field_ok"}},
            record=record,
        )

    assert result["used"] is True
    assert result["decision"] == "hold"
    assert result["reason"] == "review confirms hold"
    assert client.kwargs is not None
    assert "response_format" not in client.kwargs


@pytest.mark.asyncio
async def test_persist_iteration_record_uses_unique_iteration_benchmark_id() -> None:
    from scripts.persona_honing._persistence import _persist_iteration_record

    benchmark_run = _benchmark_run("persona-benchmark-abc12345", [_failing_attempt("memory_routing_reconsideration")])
    record = SimpleNamespace(
        review_benchmark_id=None,
        review_top_model=None,
        review_top_score=None,
        review_failing_attempts=None,
        review_failure_clusters=None,
        review_persistent_failure_clusters=None,
        review_experiment_key=None,
        review_experiment_summary=None,
        persisted_run_id=None,
        improvement_session_id=None,
        improvement_tools=None,
        improvement_parsed=None,
        final_decision=None,
        final_decision_reason=None,
        final_decision_source=None,
        decision_review=None,
        field_snapshot=None,
    )
    captured_payload: dict[str, object] = {}

    async def _capture(payload: dict[str, object]) -> str:
        captured_payload.update(payload)
        return "run-iteration-1"

    with patch(
        "scripts.persona_honing._persistence.persist_benchmark_payload",
        new=AsyncMock(side_effect=_capture),
    ):
        await _persist_iteration_record(
            record=record,
            benchmark_run=benchmark_run,
            config_snapshot={"primary_model_id": "codex/gpt-5.4"},
            suite_name="persona-suite-self-correction",
            agent_slug="persona",
            use_memory=True,
            seed=42,
            iteration=2,
            report_path="/tmp/report.md",
            failure_clusters=[],
            persistent_clusters=[],
            stop_reason=None,
            persist_results=True,
        )

    assert captured_payload["benchmark_id"] == "persona-benchmark-abc12345-iter-2"
    assert captured_payload["metadata"]["source_benchmark_id"] == "persona-benchmark-abc12345"
    assert record.persisted_run_id == "run-iteration-1"


@pytest.mark.asyncio
async def test_run_honing_loop_rolls_back_non_promoted_candidate() -> None:
    baseline_run = _benchmark_run("baseline-1", [_failing_attempt("session_patience_quiet")])
    extra_baseline_run = _benchmark_run("baseline-2", [_failing_attempt("session_patience_quiet")])
    candidate_run_1 = _benchmark_run("candidate-1", [_failing_attempt("session_patience_quiet")])
    candidate_run_2 = _benchmark_run("candidate-2", [_failing_attempt("session_patience_quiet")])

    with (
        patch("scripts.run_persona_honing_loop.AsyncAgentHubClient", return_value=_FakeClient()),
        patch(
            "scripts.run_persona_honing_loop._resolve_client_id",
            new=AsyncMock(return_value="client-1"),
        ),
        patch(
            "scripts.persona_honing._benchmarks._capture_persona_mutable_state",
            new=AsyncMock(return_value=SimpleNamespace()),
        ),
        patch(
            "scripts.persona_honing._benchmarks.run_benchmark",
            new=AsyncMock(side_effect=[baseline_run, extra_baseline_run, candidate_run_1, candidate_run_2]),
        ),
        patch(
            "scripts.persona_honing._experiment._run_improvement_pass",
            new=AsyncMock(return_value=("sess-improve", '{"summary":"tuned"}', ["read_heartbeat_instructions"], {"summary": "tuned"})),
        ),
        patch(
            "scripts.persona_honing._benchmarks.capture_benchmark_config_snapshot",
            new=AsyncMock(return_value={"primary_model_id": "codex/gpt-5.4"}),
        ),
        patch(
            "scripts.persona_honing._persistence.persist_benchmark_payload",
            new=AsyncMock(side_effect=["run-1", "run-2", "run-3", "run-4", "run-5"]),
        ),
        patch(
            "scripts.persona_honing._experiment.get_benchmark_experiment_summary_by_key",
            new=AsyncMock(return_value={"decision": "rollback", "decision_reason": "candidate_underperforms_baseline"}),
        ),
        patch(
            "scripts.persona_honing._experiment._load_field_snapshot",
            new=AsyncMock(return_value={"overview": {}, "review_gate": {"needs_review": False}, "risks": []}),
        ),
        patch(
            "scripts.persona_honing._experiment._persist_final_experiment_decision",
            new=AsyncMock(),
        ),
        patch(
            "scripts.persona_honing._experiment._restore_persona_mutable_state",
            new=AsyncMock(),
        ) as mock_restore,
    ):
        result = await run_honing_loop(
            models=["codex/gpt-5.4"],
            case_ids=["session_patience_quiet"],
            runs_per_case=1,
            project_id="agent-hub",
            working_root=Path("/tmp/persona-honing-test"),
            output_dir=Path("/tmp/persona-honing-test/reports"),
            seed=42,
            timeout_seconds=5.0,
            client_id="client-1",
            use_memory=False,
            benchmark_task_type="heartbeat",
            max_iterations=1,
            cohort_repetitions=2,
            base_url="http://localhost:8003",
            persist_results=True,
        )

    assert result["iterations"][0]["rollback_applied"] is True
    mock_restore.assert_awaited_once()


@pytest.mark.asyncio
async def test_run_honing_loop_keeps_promoted_candidate_and_marks_honed() -> None:
    baseline_run = _benchmark_run("baseline-1", [_failing_attempt("session_patience_quiet")])
    extra_baseline_run = _benchmark_run("baseline-2", [_failing_attempt("session_patience_quiet")])
    candidate_run_1 = _benchmark_run("candidate-1", [_passing_attempt("session_patience_quiet")])
    candidate_run_2 = _benchmark_run("candidate-2", [_passing_attempt("session_patience_quiet")])

    with (
        patch("scripts.run_persona_honing_loop.AsyncAgentHubClient", return_value=_FakeClient()),
        patch(
            "scripts.run_persona_honing_loop._resolve_client_id",
            new=AsyncMock(return_value="client-1"),
        ),
        patch(
            "scripts.persona_honing._benchmarks._capture_persona_mutable_state",
            new=AsyncMock(return_value=SimpleNamespace()),
        ),
        patch(
            "scripts.persona_honing._benchmarks.run_benchmark",
            new=AsyncMock(side_effect=[baseline_run, extra_baseline_run, candidate_run_1, candidate_run_2]),
        ),
        patch(
            "scripts.persona_honing._experiment._run_improvement_pass",
            new=AsyncMock(return_value=("sess-improve", '{"summary":"tuned"}', ["read_heartbeat_instructions"], {"summary": "tuned"})),
        ),
        patch(
            "scripts.persona_honing._benchmarks.capture_benchmark_config_snapshot",
            new=AsyncMock(return_value={"primary_model_id": "codex/gpt-5.4"}),
        ),
        patch(
            "scripts.persona_honing._persistence.persist_benchmark_payload",
            new=AsyncMock(side_effect=["run-1", "run-2", "run-3", "run-4", "run-5"]),
        ),
        patch(
            "scripts.persona_honing._experiment.get_benchmark_experiment_summary_by_key",
            new=AsyncMock(return_value={"decision": "promote", "decision_reason": "candidate_outperforms_baseline"}),
        ),
        patch(
            "scripts.persona_honing._experiment._load_field_snapshot",
            new=AsyncMock(return_value={"overview": {}, "review_gate": {"needs_review": False}, "risks": []}),
        ),
        patch(
            "scripts.persona_honing._experiment._persist_final_experiment_decision",
            new=AsyncMock(),
        ),
        patch(
            "scripts.persona_honing._experiment._restore_persona_mutable_state",
            new=AsyncMock(),
        ) as mock_restore,
    ):
        result = await run_honing_loop(
            models=["codex/gpt-5.4"],
            case_ids=["session_patience_quiet"],
            runs_per_case=1,
            project_id="agent-hub",
            working_root=Path("/tmp/persona-honing-test"),
            output_dir=Path("/tmp/persona-honing-test/reports"),
            seed=42,
            timeout_seconds=5.0,
            client_id="client-1",
            use_memory=False,
            benchmark_task_type="heartbeat",
            max_iterations=1,
            cohort_repetitions=2,
            base_url="http://localhost:8003",
            persist_results=True,
        )

    assert result["honed"] is True
    assert result["iterations"][0]["rollback_applied"] is False
    mock_restore.assert_not_awaited()


@pytest.mark.asyncio
async def test_run_honing_loop_rolls_back_when_completion_review_surface_regresses() -> None:
    baseline_run = _benchmark_run("baseline-1", [_failing_attempt("session_patience_quiet")])
    extra_baseline_run = _benchmark_run("baseline-2", [_failing_attempt("session_patience_quiet")])
    candidate_run_1 = _benchmark_run("candidate-1", [_passing_attempt("session_patience_quiet")])
    candidate_run_2 = _benchmark_run("candidate-2", [_passing_attempt("session_patience_quiet")])
    review_baseline_run = _review_benchmark_run(
        "review-baseline-1",
        [_review_passing_attempt("review_recent_progress_patience")],
    )
    review_extra_baseline_run = _review_benchmark_run(
        "review-baseline-2",
        [_review_passing_attempt("review_recent_progress_patience")],
    )
    review_candidate_run_1 = _review_benchmark_run(
        "review-candidate-1",
        [_review_failing_attempt("review_recent_progress_patience")],
    )
    review_candidate_run_2 = _review_benchmark_run(
        "review-candidate-2",
        [_review_failing_attempt("review_recent_progress_patience")],
    )

    with (
        patch("scripts.run_persona_honing_loop.AsyncAgentHubClient", return_value=_FakeClient()),
        patch(
            "scripts.run_persona_honing_loop._resolve_client_id",
            new=AsyncMock(return_value="client-1"),
        ),
        patch(
            "scripts.persona_honing._benchmarks._capture_persona_mutable_state",
            new=AsyncMock(return_value=SimpleNamespace()),
        ),
        patch(
            "scripts.persona_honing._benchmarks.run_benchmark",
            new=AsyncMock(side_effect=[baseline_run, extra_baseline_run, candidate_run_1, candidate_run_2]),
        ),
        patch(
            "scripts.persona_honing._benchmarks.run_completion_review_benchmark",
            new=AsyncMock(
                side_effect=[
                    review_baseline_run,
                    review_extra_baseline_run,
                    review_candidate_run_1,
                    review_candidate_run_2,
                ]
            ),
        ),
        patch(
            "scripts.persona_honing._experiment._run_improvement_pass",
            new=AsyncMock(return_value=("sess-improve", '{"summary":"tuned"}', ["read_heartbeat_instructions"], {"summary": "tuned"})),
        ),
        patch(
            "scripts.persona_honing._benchmarks.capture_benchmark_config_snapshot",
            new=AsyncMock(return_value={"primary_model_id": "codex/gpt-5.4"}),
        ),
        patch(
            "scripts.persona_honing._persistence.persist_benchmark_payload",
            new=AsyncMock(return_value="run-id"),
        ),
        patch(
            "scripts.persona_honing._experiment.get_benchmark_experiment_summary_by_key",
            new=AsyncMock(
                side_effect=[
                    {"decision": "promote", "decision_reason": "candidate_outperforms_baseline"},
                    {"decision": "rollback", "decision_reason": "completion_review_regression"},
                ]
            ),
        ),
        patch(
            "scripts.persona_honing._experiment._load_field_snapshot",
            new=AsyncMock(return_value={"overview": {}, "review_gate": {"needs_review": False}, "risks": []}),
        ),
        patch(
            "scripts.persona_honing._experiment._persist_final_experiment_decision",
            new=AsyncMock(),
        ),
        patch(
            "scripts.persona_honing._experiment._restore_persona_mutable_state",
            new=AsyncMock(),
        ) as mock_restore,
    ):
        result = await run_honing_loop(
            models=["codex/gpt-5.4"],
            case_ids=["session_patience_quiet"],
            runs_per_case=1,
            reviewer_models=["claude-opus-4-6"],
            reviewer_case_ids=["review_recent_progress_patience"],
            reviewer_runs_per_case=1,
            project_id="agent-hub",
            working_root=Path("/tmp/persona-honing-test"),
            output_dir=Path("/tmp/persona-honing-test/reports"),
            seed=42,
            timeout_seconds=5.0,
            client_id="client-1",
            use_memory=False,
            benchmark_task_type="heartbeat",
            max_iterations=1,
            cohort_repetitions=2,
            base_url="http://localhost:8003",
            persist_results=True,
        )

    assert result["iterations"][0]["rollback_applied"] is True
    assert result["iterations"][0]["review_experiment_summary"]["decision"] == "rollback"
    mock_restore.assert_awaited_once()
