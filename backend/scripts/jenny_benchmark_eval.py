"""Parsing, scoring, and aggregation for Jenny model benchmark runs."""

from __future__ import annotations

import json
import statistics
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any

from scripts.jenny_benchmark_cases import JennyBenchmarkCase

_INFRA_FAILURE_MARKERS = (
    "authentication failed",
    "check credentials",
    "api key not configured",
    "internal_server_error",
    "unexpected error occurred",
    "no response returned",
    "upstream connect error",
    "remote connection failure",
    "transport failure",
    "connection reset",
    "timed out",
    "timeout",
    "connection refused",
    "503",
    "502",
    "rate limit",
    "claude sdk stalled after tool_result",
)

_VALID_ACTIONS = {"dispatch", "monitor", "block", "wait", "reconcile"}
_VALID_CONFIDENCE = {"low", "medium", "high"}


@dataclass
class JennyBenchmarkAttempt:
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
class JennyBenchmarkSummary:
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
class JennyBenchmarkRun:
    """Complete benchmark output across all models and cases."""

    benchmark_id: str
    project_id: str
    models: list[str]
    case_ids: list[str]
    runs_per_case: int
    started_at: str
    completed_at: str
    attempts: list[JennyBenchmarkAttempt]
    summaries: list[JennyBenchmarkSummary]

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


def strip_markdown_fences(content: str) -> str:
    """Remove simple ```json fences before parsing."""
    stripped = content.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        return "\n".join(lines).strip()
    return stripped


def parse_benchmark_json(content: str) -> tuple[dict[str, Any] | None, str | None]:
    """Parse the model output as JSON."""
    cleaned = strip_markdown_fences(content)
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        return None, f"invalid_json: {exc}"
    if not isinstance(parsed, dict):
        return None, "invalid_json: top-level value must be an object"
    return parsed, None


def validate_benchmark_shape(parsed: dict[str, Any]) -> tuple[bool, str | None]:
    """Validate the benchmark response shape."""
    required = {
        "case_id": str,
        "primary_action": str,
        "should_dispatch": bool,
        "should_close": bool,
        "confidence": str,
        "summary": str,
    }
    for field_name, expected_type in required.items():
        if field_name not in parsed:
            return False, f"missing_field: {field_name}"
        if not isinstance(parsed[field_name], expected_type):
            return False, f"type_error: {field_name}"

    if parsed["primary_action"] not in _VALID_ACTIONS:
        return False, "invalid_action"
    if parsed["confidence"] not in _VALID_CONFIDENCE:
        return False, "invalid_confidence"
    return True, None


def classify_failure(detail: str | None) -> tuple[bool, str | None]:
    """Classify a failure as infra or model-quality related."""
    if not detail:
        return False, None
    lower = detail.lower()
    if any(marker in lower for marker in _INFRA_FAILURE_MARKERS):
        return True, "infra"
    return False, "model"


def _normalize_tool_name(tool_name: str) -> str:
    """Normalize stored tool names so prefixed runtime variants still match."""
    normalized = tool_name.strip().lower()
    if normalized.startswith("mcp__") and "__" in normalized:
        normalized = normalized.rsplit("__", 1)[-1]
    return normalized


def score_attempt(
    *,
    case: JennyBenchmarkCase,
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
) -> JennyBenchmarkAttempt:
    """Turn one live completion into a scored benchmark attempt."""
    attempt = JennyBenchmarkAttempt(
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

    parsed, parse_error = parse_benchmark_json(content)
    if parse_error:
        attempt.failure_detail = parse_error
        attempt.failure_kind = "model"
        return attempt

    attempt.parsed = parsed
    attempt.schema_valid, shape_error = validate_benchmark_shape(parsed)
    if not attempt.schema_valid:
        attempt.failure_detail = shape_error
        attempt.failure_kind = "model"
        return attempt

    matches = [
        1.0 if parsed.get(field_name) == expected_value else 0.0
        for field_name, expected_value in case.expected.items()
    ]
    if case.required_summary_terms:
        summary = str(parsed.get("summary", "")).lower()
        keyword_match_ratio = sum(
            1.0 for term in case.required_summary_terms if term in summary
        ) / len(case.required_summary_terms)
        matches.append(keyword_match_ratio)
    attempt.correctness_score = sum(matches) / len(matches)
    generic_tool_requirement_met = (not case.require_tool_call) or tool_calls_count > 0
    used_tool_name_set = {
        _normalize_tool_name(tool_name) for tool_name in attempt.used_tool_names if tool_name
    }
    required_tool_name_set = {
        _normalize_tool_name(tool_name) for tool_name in case.required_tool_names if tool_name
    }
    specific_tool_requirement_met = required_tool_name_set.issubset(used_tool_name_set)
    attempt.tool_requirement_met = generic_tool_requirement_met and specific_tool_requirement_met
    tool_score = 1.0 if attempt.tool_requirement_met else 0.0
    attempt.composite_score = round((attempt.correctness_score * 0.85 + tool_score * 0.15) * 100, 1)
    attempt.passed = attempt.correctness_score == 1.0 and attempt.tool_requirement_met
    if not attempt.passed:
        attempt.failure_kind = "model"
        if not generic_tool_requirement_met:
            attempt.failure_detail = "required_tool_call_missing"
        elif not specific_tool_requirement_met:
            missing_tools = sorted(required_tool_name_set - used_tool_name_set)
            attempt.failure_detail = f"required_tools_missing: {', '.join(missing_tools)}"
        else:
            attempt.failure_detail = "wrong_decision"
    return attempt


def summarize_attempts(attempts: list[JennyBenchmarkAttempt]) -> list[JennyBenchmarkSummary]:
    """Aggregate attempts into per-model summaries."""
    grouped: dict[str, list[JennyBenchmarkAttempt]] = {}
    for attempt in attempts:
        grouped.setdefault(attempt.model_id, []).append(attempt)

    summaries: list[JennyBenchmarkSummary] = []
    for model_id, model_attempts in grouped.items():
        infra_failures = sum(1 for attempt in model_attempts if attempt.failure_kind == "infra")
        model_failures = sum(1 for attempt in model_attempts if attempt.failure_kind == "model")
        summaries.append(
            JennyBenchmarkSummary(
                model_id=model_id,
                attempts=len(model_attempts),
                pass_rate=sum(1 for attempt in model_attempts if attempt.passed) / len(model_attempts),
                avg_composite_score=statistics.fmean(
                    attempt.composite_score for attempt in model_attempts
                ),
                avg_correctness_score=statistics.fmean(
                    attempt.correctness_score for attempt in model_attempts
                ),
                infra_failures=infra_failures,
                model_failures=model_failures,
                avg_latency_ms=statistics.fmean(attempt.latency_ms for attempt in model_attempts),
                avg_total_tokens=statistics.fmean(attempt.total_tokens for attempt in model_attempts),
                avg_turns=statistics.fmean(attempt.turns for attempt in model_attempts),
                avg_tool_calls=statistics.fmean(attempt.tool_calls_count for attempt in model_attempts),
            )
        )

    summaries.sort(
        key=lambda summary: (
            -summary.avg_composite_score,
            -summary.pass_rate,
            summary.infra_failures,
            summary.avg_latency_ms,
        )
    )
    return summaries
