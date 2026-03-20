"""Parsing, scoring, and aggregation for completion-review model benchmarks."""

from __future__ import annotations

import json
import re
import statistics
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any

from scripts.completion_review_benchmark_cases import CompletionReviewBenchmarkCase
from scripts.persona_benchmark_eval import classify_failure

_VALID_DECISIONS = {"complete", "continue", "escalate"}
_VALID_CONFIDENCE = {"low", "medium", "high"}


def _expected_term_hit(combined_text: str, expected_term: str) -> bool:
    alternatives = [term.strip().lower() for term in expected_term.split("|") if term.strip()]
    return any(term in combined_text for term in alternatives)


@dataclass
class CompletionReviewBenchmarkAttempt:
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
    composite_score: float = 0.0
    passed: bool = False
    infra_failure: bool = False
    failure_detail: str | None = None
    failure_kind: str | None = None
    fallback_used: bool = False
    turns: int = 0
    tool_calls_count: int = 0
    used_tool_names: list[str] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CompletionReviewBenchmarkSummary:
    model_id: str
    attempts: int
    pass_rate: float
    avg_composite_score: float
    avg_correctness_score: float
    avg_latency_ms: float
    avg_total_tokens: float
    avg_turns: float


@dataclass
class CompletionReviewBenchmarkRun:
    benchmark_id: str
    project_id: str
    models: list[str]
    case_ids: list[str]
    runs_per_case: int
    started_at: str
    completed_at: str
    attempts: list[CompletionReviewBenchmarkAttempt]
    summaries: list[CompletionReviewBenchmarkSummary]

    def to_dict(self) -> dict[str, Any]:
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


def _strip_markdown_fences(content: str) -> str:
    stripped = content.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        return "\n".join(lines).strip()
    return stripped


def _extract_fenced_json_block(content: str) -> str | None:
    match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", content, flags=re.DOTALL)
    if not match:
        return None
    return match.group(1).strip()


def _parse_json(content: str) -> tuple[dict[str, Any] | None, str | None]:
    cleaned = _strip_markdown_fences(content)
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        fenced = _extract_fenced_json_block(content)
        if fenced is None:
            return None, f"invalid_json: {exc}"
        try:
            parsed = json.loads(fenced)
        except json.JSONDecodeError as fenced_exc:
            return None, f"invalid_json: {fenced_exc}"
    if not isinstance(parsed, dict):
        return None, "invalid_json: top-level value must be an object"
    return parsed, None


def _validate_shape(parsed: dict[str, Any]) -> tuple[bool, str | None]:
    required = {
        "case_id": str,
        "decision": str,
        "confidence": str,
        "reason": str,
        "focus": str,
    }
    for field_name, expected_type in required.items():
        if field_name not in parsed:
            return False, f"missing_field: {field_name}"
        if not isinstance(parsed[field_name], expected_type):
            return False, f"type_error: {field_name}"
    if parsed["decision"] not in _VALID_DECISIONS:
        return False, "invalid_decision"
    if parsed["confidence"] not in _VALID_CONFIDENCE:
        return False, "invalid_confidence"
    return True, None


def score_completion_review_attempt(
    *,
    case: CompletionReviewBenchmarkCase,
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
) -> CompletionReviewBenchmarkAttempt:
    attempt = CompletionReviewBenchmarkAttempt(
        model_id=model_id,
        case_id=case.case_id,
        run_number=run_number,
        latency_ms=latency_ms,
        session_id=session_id,
        provider=provider,
        effective_model=effective_model,
        requested_model=model_id,
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

    parsed, parse_error = _parse_json(content)
    if parse_error:
        attempt.failure_detail = parse_error
        attempt.failure_kind = "model"
        return attempt

    attempt.parsed = parsed
    attempt.schema_valid, shape_error = _validate_shape(parsed)
    if not attempt.schema_valid:
        attempt.failure_detail = shape_error
        attempt.failure_kind = "model"
        return attempt

    score_parts = [1.0 if parsed["case_id"] == case.case_id else 0.0]
    score_parts.append(1.0 if parsed["decision"] == case.expected_decision else 0.0)

    combined_text = f"{parsed['reason']} {parsed['focus']}".lower()
    if case.expected_focus_terms:
        term_hits = sum(1 for term in case.expected_focus_terms if _expected_term_hit(combined_text, term))
        score_parts.append(term_hits / len(case.expected_focus_terms))

    attempt.correctness_score = sum(score_parts) / len(score_parts)
    attempt.composite_score = round(attempt.correctness_score * 100, 1)
    attempt.passed = (
        parsed["case_id"] == case.case_id
        and parsed["decision"] == case.expected_decision
        and all(_expected_term_hit(combined_text, term) for term in case.expected_focus_terms)
    )
    if not attempt.passed:
        attempt.failure_kind = "model"
        if parsed["decision"] != case.expected_decision:
            attempt.failure_detail = "wrong_review_decision"
        else:
            attempt.failure_detail = "focus_terms_missing"
    return attempt


def summarize_completion_review_attempts(
    attempts: list[CompletionReviewBenchmarkAttempt],
) -> list[CompletionReviewBenchmarkSummary]:
    grouped: dict[str, list[CompletionReviewBenchmarkAttempt]] = {}
    for attempt in attempts:
        grouped.setdefault(attempt.model_id, []).append(attempt)

    summaries: list[CompletionReviewBenchmarkSummary] = []
    for model_id, model_attempts in grouped.items():
        pass_rate = (sum(1 for attempt in model_attempts if attempt.passed) / len(model_attempts)) * 100
        summaries.append(
            CompletionReviewBenchmarkSummary(
                model_id=model_id,
                attempts=len(model_attempts),
                pass_rate=round(pass_rate, 1),
                avg_composite_score=round(
                    statistics.mean(attempt.composite_score for attempt in model_attempts), 1
                ),
                avg_correctness_score=round(
                    statistics.mean(attempt.correctness_score for attempt in model_attempts), 3
                ),
                avg_latency_ms=round(statistics.mean(attempt.latency_ms for attempt in model_attempts), 1),
                avg_total_tokens=round(
                    statistics.mean(attempt.total_tokens for attempt in model_attempts), 1
                ),
                avg_turns=round(statistics.mean(attempt.turns for attempt in model_attempts), 2),
            )
        )
    summaries.sort(key=lambda summary: (-summary.avg_composite_score, -summary.pass_rate, summary.model_id))
    return summaries
