"""Tests for the Jenny honing loop helpers."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from scripts.jenny_benchmark_eval import (
    JennyBenchmarkAttempt,
    JennyBenchmarkRun,
    summarize_attempts,
)
from scripts.run_jenny_honing_loop import (
    _run_improvement_pass,
    build_honing_prompt,
    run_honing_loop,
)


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


def test_build_honing_prompt_includes_persistent_cluster_section() -> None:
    run = _make_run(
        [
            JennyBenchmarkAttempt(
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

    prompt = build_honing_prompt(
        run,
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


def _passing_attempt(case_id: str) -> JennyBenchmarkAttempt:
    return JennyBenchmarkAttempt(
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


def _failing_attempt(case_id: str) -> JennyBenchmarkAttempt:
    return JennyBenchmarkAttempt(
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


def _benchmark_run(benchmark_id: str, attempts: list[JennyBenchmarkAttempt]) -> JennyBenchmarkRun:
    return JennyBenchmarkRun(
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


@pytest.mark.asyncio
async def test_run_improvement_pass_disables_memory_in_controlled_honing_loop() -> None:
    client = _FakeImprovementClient()
    run = _benchmark_run("bench-1", [_failing_attempt("session_patience_recent_progress")])

    with patch(
        "scripts.jenny_honing._experiment._fetch_used_tool_names",
        new=AsyncMock(return_value=["read_heartbeat_instructions"]),
    ):
        session_id, content, tools, parsed = await _run_improvement_pass(
            client=client,
            project_id="agent-hub",
            iteration=1,
            run=run,
            previous_clusters=None,
            timeout_seconds=5.0,
            working_root=Path("/tmp/jenny-honing-test"),
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


@pytest.mark.asyncio
async def test_run_honing_loop_rolls_back_non_promoted_candidate() -> None:
    baseline_run = _benchmark_run("baseline-1", [_failing_attempt("session_patience_quiet")])
    extra_baseline_run = _benchmark_run("baseline-2", [_failing_attempt("session_patience_quiet")])
    candidate_run_1 = _benchmark_run("candidate-1", [_failing_attempt("session_patience_quiet")])
    candidate_run_2 = _benchmark_run("candidate-2", [_failing_attempt("session_patience_quiet")])

    with (
        patch("scripts.run_jenny_honing_loop.AsyncAgentHubClient", return_value=_FakeClient()),
        patch(
            "scripts.run_jenny_honing_loop._resolve_client_id",
            new=AsyncMock(return_value="client-1"),
        ),
        patch(
            "scripts.jenny_honing._experiment._capture_jenny_mutable_state",
            new=AsyncMock(return_value=SimpleNamespace()),
        ),
        patch(
            "scripts.jenny_honing._experiment.run_benchmark",
            new=AsyncMock(side_effect=[baseline_run, extra_baseline_run, candidate_run_1, candidate_run_2]),
        ),
        patch(
            "scripts.jenny_honing._experiment._run_improvement_pass",
            new=AsyncMock(return_value=("sess-improve", '{"summary":"tuned"}', ["read_heartbeat_instructions"], {"summary": "tuned"})),
        ),
        patch(
            "scripts.jenny_honing._experiment.capture_benchmark_config_snapshot",
            new=AsyncMock(return_value={"primary_model_id": "codex/gpt-5.4"}),
        ),
        patch(
            "scripts.jenny_honing._experiment.persist_benchmark_payload",
            new=AsyncMock(side_effect=["run-1", "run-2", "run-3", "run-4"]),
        ),
        patch(
            "scripts.jenny_honing._experiment.get_benchmark_experiment_summary_by_key",
            new=AsyncMock(return_value={"decision": "rollback", "decision_reason": "candidate_underperforms_baseline"}),
        ),
        patch(
            "scripts.jenny_honing._experiment._restore_jenny_mutable_state",
            new=AsyncMock(),
        ) as mock_restore,
    ):
        result = await run_honing_loop(
            models=["codex/gpt-5.4"],
            case_ids=["session_patience_quiet"],
            runs_per_case=1,
            project_id="agent-hub",
            working_root=Path("/tmp/jenny-honing-test"),
            output_dir=Path("/tmp/jenny-honing-test/reports"),
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
        patch("scripts.run_jenny_honing_loop.AsyncAgentHubClient", return_value=_FakeClient()),
        patch(
            "scripts.run_jenny_honing_loop._resolve_client_id",
            new=AsyncMock(return_value="client-1"),
        ),
        patch(
            "scripts.jenny_honing._experiment._capture_jenny_mutable_state",
            new=AsyncMock(return_value=SimpleNamespace()),
        ),
        patch(
            "scripts.jenny_honing._experiment.run_benchmark",
            new=AsyncMock(side_effect=[baseline_run, extra_baseline_run, candidate_run_1, candidate_run_2]),
        ),
        patch(
            "scripts.jenny_honing._experiment._run_improvement_pass",
            new=AsyncMock(return_value=("sess-improve", '{"summary":"tuned"}', ["read_heartbeat_instructions"], {"summary": "tuned"})),
        ),
        patch(
            "scripts.jenny_honing._experiment.capture_benchmark_config_snapshot",
            new=AsyncMock(return_value={"primary_model_id": "codex/gpt-5.4"}),
        ),
        patch(
            "scripts.jenny_honing._experiment.persist_benchmark_payload",
            new=AsyncMock(side_effect=["run-1", "run-2", "run-3", "run-4"]),
        ),
        patch(
            "scripts.jenny_honing._experiment.get_benchmark_experiment_summary_by_key",
            new=AsyncMock(return_value={"decision": "promote", "decision_reason": "candidate_outperforms_baseline"}),
        ),
        patch(
            "scripts.jenny_honing._experiment._restore_jenny_mutable_state",
            new=AsyncMock(),
        ) as mock_restore,
    ):
        result = await run_honing_loop(
            models=["codex/gpt-5.4"],
            case_ids=["session_patience_quiet"],
            runs_per_case=1,
            project_id="agent-hub",
            working_root=Path("/tmp/jenny-honing-test"),
            output_dir=Path("/tmp/jenny-honing-test/reports"),
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
