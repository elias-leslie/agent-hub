"""Parsing, scoring, and aggregation for helper-agent output contract benchmarks."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime

from app.services.benchmark_aggregation import aggregate_attempts
from scripts.agent_output_benchmark_cases import AgentOutputBenchmarkCase
from scripts.persona_benchmark_eval import classify_failure, normalize_attempt_identity


def _term_present(content: str, term: str) -> bool:
    alternatives = [candidate.strip().lower() for candidate in term.split("|") if candidate.strip()]
    lowered = content.lower()
    return any(candidate in lowered for candidate in alternatives)


def _line_count(content: str) -> int:
    return len([line for line in content.splitlines() if line.strip()])


def _summary_excerpt(content: str, max_chars: int = 160) -> str:
    stripped = content.strip().replace("\r\n", "\n").replace("\r", "\n")
    single_line = " ".join(part.strip() for part in stripped.splitlines() if part.strip())
    if len(single_line) <= max_chars:
        return single_line
    return single_line[: max_chars - 3].rstrip() + "..."


@dataclass
class AgentOutputBenchmarkAttempt:
    """One benchmark attempt for one helper-agent case on one model."""

    model_id: str
    case_id: str
    run_number: int
    latency_ms: int
    session_id: str | None = None
    provider: str | None = None
    effective_model: str | None = None
    requested_model: str | None = None
    content: str = ""
    schema_valid: bool = True
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
    summary_excerpt: str | None = None
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict[str, object]:
        """Serialize result to plain JSON-compatible data."""
        return asdict(self)


@dataclass
class AgentOutputBenchmarkSummary:
    """Aggregated benchmark result for one helper agent model target."""

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
class AgentOutputBenchmarkRun:
    """Complete helper-agent output benchmark output across all attempts."""

    benchmark_id: str
    project_id: str
    agent_slug: str
    models: list[str]
    case_ids: list[str]
    runs_per_case: int
    started_at: str
    completed_at: str
    attempts: list[AgentOutputBenchmarkAttempt]
    summaries: list[AgentOutputBenchmarkSummary]

    def to_dict(self) -> dict[str, object]:
        """Serialize complete run to dict."""
        return {
            "benchmark_id": self.benchmark_id,
            "project_id": self.project_id,
            "agent_slug": self.agent_slug,
            "models": self.models,
            "case_ids": self.case_ids,
            "runs_per_case": self.runs_per_case,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "attempts": [attempt.to_dict() for attempt in self.attempts],
            "summaries": [asdict(summary) for summary in self.summaries],
        }


def score_output_contract_attempt(
    *,
    case: AgentOutputBenchmarkCase,
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
) -> AgentOutputBenchmarkAttempt:
    provider, effective_model, requested_model = normalize_attempt_identity(
        model_id=model_id,
        provider=provider,
        effective_model=effective_model,
        requested_model=model_id,
    )
    attempt = AgentOutputBenchmarkAttempt(
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

    stripped = content.strip()
    attempt.summary_excerpt = _summary_excerpt(content) if stripped else None
    checks: list[bool] = []

    content_present = bool(stripped)
    checks.append(content_present)
    if not content_present:
        attempt.failure_kind = "model"
        attempt.failure_detail = "empty_output"
        return attempt

    if case.require_tool_call:
        tool_call_ok = bool(tool_calls_count or used_tool_names)
        checks.append(tool_call_ok)
        if not tool_call_ok and attempt.failure_detail is None:
            attempt.failure_kind = "model"
            attempt.failure_detail = "missing_required_tool_call"

    if case.required_prefix:
        prefix_ok = stripped.startswith(case.required_prefix)
        checks.append(prefix_ok)
        if not prefix_ok and attempt.failure_detail is None:
            attempt.failure_kind = "model"
            attempt.failure_detail = "missing_required_prefix"

    lines = _line_count(stripped)
    if case.min_lines is not None:
        min_lines_ok = lines >= case.min_lines
        checks.append(min_lines_ok)
        if not min_lines_ok and attempt.failure_detail is None:
            attempt.failure_kind = "model"
            attempt.failure_detail = "too_few_lines"
    if case.max_lines is not None:
        max_lines_ok = lines <= case.max_lines
        checks.append(max_lines_ok)
        if not max_lines_ok and attempt.failure_detail is None:
            attempt.failure_kind = "model"
            attempt.failure_detail = "too_many_lines"

    for term in case.required_terms:
        hit = _term_present(stripped, term)
        checks.append(hit)
        if not hit and attempt.failure_detail is None:
            attempt.failure_kind = "model"
            attempt.failure_detail = f"missing_required_term:{term}"

    for term in case.forbidden_terms:
        clean = not _term_present(stripped, term)
        checks.append(clean)
        if not clean and attempt.failure_detail is None:
            attempt.failure_kind = "model"
            attempt.failure_detail = f"forbidden_term_present:{term}"

    attempt.correctness_score = sum(1.0 for check in checks if check) / len(checks)
    attempt.composite_score = round(attempt.correctness_score * 100, 1)
    attempt.passed = all(checks)
    if not attempt.passed and attempt.failure_kind is None:
        attempt.failure_kind = "model"
        attempt.failure_detail = "output_contract_failed"
    return attempt


def summarize_output_contract_attempts(
    attempts: list[AgentOutputBenchmarkAttempt],
) -> list[AgentOutputBenchmarkSummary]:
    grouped: dict[str, list[AgentOutputBenchmarkAttempt]] = {}
    for attempt in attempts:
        grouped.setdefault(attempt.model_id, []).append(attempt)

    summaries: list[AgentOutputBenchmarkSummary] = []
    for model_id, model_attempts in grouped.items():
        aggregate = aggregate_attempts(model_attempts)
        summaries.append(
            AgentOutputBenchmarkSummary(
                model_id=model_id,
                attempts=len(model_attempts),
                pass_rate=aggregate.pass_rate or 0.0,
                avg_composite_score=aggregate.avg_score or 0.0,
                avg_correctness_score=aggregate.avg_correctness_score or 0.0,
                infra_failures=aggregate.infra_failure_count,
                model_failures=aggregate.scored_attempts - aggregate.passed_attempt_count,
                avg_latency_ms=aggregate.avg_latency_ms or 0.0,
                avg_total_tokens=aggregate.avg_total_tokens or 0.0,
                avg_turns=aggregate.avg_turns or 0.0,
                avg_tool_calls=aggregate.avg_tool_calls or 0.0,
            )
        )
    summaries.sort(key=lambda summary: (-summary.avg_composite_score, -summary.pass_rate, summary.model_id))
    return summaries
