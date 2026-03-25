"""Tests for helper-agent output contract benchmark helpers."""

from __future__ import annotations

from scripts.agent_output_benchmark_cases import get_case_by_id, get_default_case_ids
from scripts.agent_output_benchmark_eval import (
    AgentOutputBenchmarkRun,
    score_output_contract_attempt,
    summarize_output_contract_attempts,
)
from scripts.run_agent_output_benchmark import build_persistence_payload, derive_suite_id


def test_score_output_contract_attempt_passes_note_titler_case() -> None:
    case = get_case_by_id("note-titler", "note_titler_plain_title")

    attempt = score_output_contract_attempt(
        case=case,
        model_id="codex/gpt-5.4",
        run_number=1,
        latency_ms=850,
        content="TITLE: Q2 Deadline for JWT Auth Migration",
        session_id="sess-1",
        provider="codex",
        effective_model="codex/gpt-5.4",
        fallback_used=False,
        turns=1,
        tool_calls_count=0,
        used_tool_names=[],
        input_tokens=90,
        output_tokens=15,
        total_tokens=105,
    )

    assert attempt.passed is True
    assert attempt.failure_detail is None
    assert attempt.composite_score == 100.0


def test_score_output_contract_attempt_rejects_observability_tags() -> None:
    case = get_case_by_id("prompt-builder", "prompt_builder_raw_prompt")

    attempt = score_output_contract_attempt(
        case=case,
        model_id="codex/gpt-5.4",
        run_number=1,
        latency_ms=900,
        content="[[P:started:building prompt]]\nYou summarize billing incidents in factual language.",
        session_id="sess-2",
        provider="codex",
        effective_model="codex/gpt-5.4",
        fallback_used=False,
        turns=1,
        tool_calls_count=0,
        used_tool_names=[],
        input_tokens=90,
        output_tokens=25,
        total_tokens=115,
    )

    assert attempt.passed is False
    assert attempt.failure_detail == "missing_required_prefix"


def test_derive_suite_id_uses_agent_default_suite() -> None:
    suite_id = derive_suite_id("note-formatter", get_default_case_ids("note-formatter"))

    assert suite_id == "output-contract-note-formatter"


def test_build_persistence_payload_maps_output_summary() -> None:
    case = get_case_by_id("note-formatter", "note_formatter_bare_json")
    attempt = score_output_contract_attempt(
        case=case,
        model_id="claude-sonnet-4-6",
        run_number=1,
        latency_ms=900,
        content=(
            '{\n'
            '"title": "Agent Hub Project Status Overview",\n'
            '"content": "rotate keys\\nrerun benchmark\\nverify heartbeat"\n'
            '}'
        ),
        session_id="sess-3",
        provider="claude",
        effective_model="claude-sonnet-4-6",
        fallback_used=False,
        turns=1,
        tool_calls_count=0,
        used_tool_names=[],
        input_tokens=120,
        output_tokens=60,
        total_tokens=180,
    )
    run = AgentOutputBenchmarkRun(
        benchmark_id="output-bench-1",
        project_id="agent-hub",
        agent_slug="note-formatter",
        models=["claude-sonnet-4-6"],
        case_ids=[case.case_id],
        runs_per_case=1,
        started_at="2026-03-25T00:00:00+00:00",
        completed_at="2026-03-25T00:01:00+00:00",
        attempts=[attempt],
        summaries=summarize_output_contract_attempts([attempt]),
    )

    payload = build_persistence_payload(
        run,
        suite_id="output-contract-note-formatter",
        run_kind="output_contract_benchmark",
        use_memory=False,
        seed=42,
        config_snapshot={"primary_model_id": "claude-sonnet-4-6"},
        metadata={"benchmark_type": "output_contract"},
    )

    assert payload["avg_score"] == 100.0
    assert payload["pass_rate"] == 100.0
    assert payload["attempts"][0]["primary_action"] == "output_contract"
    assert "Agent Hub Project Status Overview" in str(payload["attempts"][0]["summary"])
