"""Parsing, scoring, and aggregation for persona model benchmark runs."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any

from app.services.benchmark_aggregation import aggregate_attempts
from scripts.persona_benchmark_cases import PersonaBenchmarkCase
from scripts.persona_benchmark_scoring import (
    classify_failure,
    evaluate_attempt_content,
    normalize_attempt_identity,
    parse_benchmark_json,
    strip_markdown_fences,
    validate_benchmark_shape,
)

# Re-export public helpers that callers may import from this module.
__all__ = [
    "PersonaBenchmarkAttempt",
    "PersonaBenchmarkRun",
    "PersonaBenchmarkSummary",
    "classify_failure",
    "normalize_attempt_identity",
    "parse_benchmark_json",
    "score_attempt",
    "strip_markdown_fences",
    "summarize_attempts",
    "validate_benchmark_shape",
]


@dataclass
class PersonaBenchmarkAttempt:
    """One benchmark attempt for one case on one model."""

    model_id: str
    case_id: str
    run_number: int
    latency_ms: int
    session_id: str | None = None
    provider: str | None = None
    effective_model: str | None = None
    requested_model: str | None = None
    content: str = ""
    parsed: dict[str, Any] | None = None
    schema_valid: bool = False
    correctness_score: float = 0.0
    tool_requirement_met: bool = True
    composite_score: float = 0.0
    passed: bool = False
    infra_failure: bool = False
    failure_kind: str | None = None
    failure_detail: str | None = None
    fallback_used: bool = False
    turns: int = 0
    tool_calls_count: int = 0
    used_tool_names: list[str] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict[str, Any]:
        """Serialize result to plain JSON-compatible data."""
        return asdict(self)


@dataclass
class PersonaBenchmarkSummary:
    """Aggregated benchmark result for a single model."""

    model_id: str
    attempts: int
    pass_rate: float
    avg_composite_score: float
    avg_correctness_score: float
    infra_failures: int
    model_failures: int
    avg_latency_ms: float
    avg_total_tokens: float
    avg_turns: float
    avg_tool_calls: float


@dataclass
class PersonaBenchmarkRun:
    """Complete benchmark output across all models and cases."""

    benchmark_id: str
    project_id: str
    models: list[str]
    case_ids: list[str]
    runs_per_case: int
    started_at: str
    completed_at: str
    attempts: list[PersonaBenchmarkAttempt]
    summaries: list[PersonaBenchmarkSummary]

    def to_dict(self) -> dict[str, Any]:
        """Serialize complete run to dict."""
        return {
            "benchmark_id": self.benchmark_id,
            "project_id": self.project_id,
            "models": self.models,
            "case_ids": self.case_ids,
            "runs_per_case": self.runs_per_case,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "attempts": [attempt.to_dict() for attempt in self.attempts],
            "summaries": [asdict(summary) for summary in self.summaries],
        }


def score_attempt(
    *,
    case: PersonaBenchmarkCase,
    model_id: str,
    run_number: int,
    latency_ms: int,
    content: str,
    session_id: str | None,
    provider: str | None,
    effective_model: str | None,
    fallback_used: bool,
    turns: int,
    tool_calls_count: int,
    used_tool_names: list[str] | None,
    input_tokens: int,
    output_tokens: int,
    total_tokens: int,
    failure_detail: str | None = None,
) -> PersonaBenchmarkAttempt:
    """Turn one live completion into a scored benchmark attempt."""
    provider, effective_model, requested_model = normalize_attempt_identity(
        model_id=model_id,
        provider=provider,
        effective_model=effective_model,
        requested_model=model_id,
    )
    attempt = PersonaBenchmarkAttempt(
        model_id=model_id,
        case_id=case.case_id,
        run_number=run_number,
        latency_ms=latency_ms,
        session_id=session_id,
        provider=provider,
        effective_model=effective_model,
        requested_model=requested_model,
        content=content,
        fallback_used=fallback_used,
        turns=turns,
        tool_calls_count=tool_calls_count,
        used_tool_names=list(used_tool_names or []),
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
        failure_detail=failure_detail,
    )

    if failure_detail:
        attempt.infra_failure, attempt.failure_kind = classify_failure(failure_detail)
        if not attempt.failure_kind:
            attempt.failure_kind = "model"
        return attempt

    evaluate_attempt_content(attempt, case)
    return attempt


def summarize_attempts(attempts: list[PersonaBenchmarkAttempt]) -> list[PersonaBenchmarkSummary]:
    """Aggregate attempts into per-model summaries."""
    grouped: dict[str, list[PersonaBenchmarkAttempt]] = {}
    for attempt in attempts:
        grouped.setdefault(attempt.model_id, []).append(attempt)

    summaries: list[PersonaBenchmarkSummary] = []
    for model_id, model_attempts in grouped.items():
        aggregate = aggregate_attempts(model_attempts)
        infra_failures = aggregate.infra_failure_count
        model_failures = sum(
            1 for a in model_attempts if not a.infra_failure and a.failure_kind == "model"
        )
        summaries.append(
            PersonaBenchmarkSummary(
                model_id=model_id,
                attempts=len(model_attempts),
                pass_rate=(aggregate.pass_rate or 0.0) / 100,
                avg_composite_score=aggregate.avg_score or 0.0,
                avg_correctness_score=aggregate.avg_correctness_score or 0.0,
                infra_failures=infra_failures,
                model_failures=model_failures,
                avg_latency_ms=aggregate.avg_latency_ms or 0.0,
                avg_total_tokens=aggregate.avg_total_tokens or 0.0,
                avg_turns=aggregate.avg_turns or 0.0,
                avg_tool_calls=aggregate.avg_tool_calls or 0.0,
            )
        )

    summaries.sort(
        key=lambda s: (
            -s.avg_composite_score,
            -s.pass_rate,
            s.avg_tool_calls,
            s.avg_total_tokens,
            s.avg_turns,
            s.infra_failures,
            s.avg_latency_ms,
        )
    )
    return summaries
