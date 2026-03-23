"""Parsing, scoring, and aggregation for persona model benchmark runs."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any

from app.adapters.registry import get_provider_for_model
from app.services.benchmark_aggregation import aggregate_attempts
from app.services.benchmark_failure_classification import classify_benchmark_failure_detail
from scripts.persona_benchmark_cases import PersonaBenchmarkCase

_VALID_ACTIONS = {"dispatch", "monitor", "block", "wait", "reconcile"}
_VALID_CONFIDENCE = {"low", "medium", "high"}


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


def _extract_fenced_json_block(content: str) -> str | None:
    """Extract the first fenced JSON block from a provider response."""
    match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", content, flags=re.DOTALL)
    if not match:
        return None
    return match.group(1).strip()


_LEADING_APPLIED_CITATIONS_RE = re.compile(
    r"^(?:Applied:\s*(?:\[[MGR]:[^\]]+\]\s*)+)+"
)


def _strip_leading_narration_tags(content: str) -> str:
    """Remove leading [[P:...]] narration tags emitted during task execution."""
    remaining = content.lstrip()
    while remaining:
        if remaining.startswith("[[P:"):
            end = remaining.find("]]")
            if end == -1:
                break
            remaining = remaining[end + 2 :].lstrip()
            continue

        citation_match = _LEADING_APPLIED_CITATIONS_RE.match(remaining)
        if citation_match:
            remaining = remaining[citation_match.end() :].lstrip()
            continue

        break
    return remaining


def _load_first_json_object(content: str) -> dict[str, Any]:
    """Decode the first JSON object in a response, tolerating light preamble."""
    decoder = json.JSONDecoder()
    stripped = content.strip()
    try:
        parsed, _ = decoder.raw_decode(stripped)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    brace_index = stripped.find("{")
    if brace_index <= 0:
        raise json.JSONDecodeError("Expected JSON object", stripped, 0)
    reparsed, _ = decoder.raw_decode(stripped[brace_index:])
    if not isinstance(reparsed, dict):
        raise json.JSONDecodeError("Top-level value must be an object", stripped, brace_index)
    return reparsed


def parse_benchmark_json(content: str) -> tuple[dict[str, Any] | None, str | None]:
    """Parse the model output as JSON."""
    cleaned = strip_markdown_fences(_strip_leading_narration_tags(content))
    try:
        parsed = _load_first_json_object(cleaned)
    except json.JSONDecodeError as exc:
        fenced_json = _extract_fenced_json_block(content)
        if fenced_json is None:
            return None, f"invalid_json: {exc}"
        try:
            parsed = _load_first_json_object(_strip_leading_narration_tags(fenced_json))
        except json.JSONDecodeError as fenced_exc:
            return None, f"invalid_json: {fenced_exc}"
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
    return classify_benchmark_failure_detail(detail)


def _normalize_tool_name(tool_name: str) -> str:
    """Normalize stored tool names so prefixed runtime variants still match."""
    normalized = tool_name.strip().lower()
    if normalized.startswith("mcp__") and "__" in normalized:
        normalized = normalized.rsplit("__", 1)[-1]
    return normalized


def normalize_attempt_identity(
    *,
    model_id: str,
    provider: str | None,
    effective_model: str | None,
    requested_model: str | None = None,
) -> tuple[str, str, str]:
    """Return provider/effective/requested model identity with safe fallbacks."""
    resolved_requested_model = requested_model or model_id
    resolved_effective_model = effective_model or resolved_requested_model
    resolved_provider = provider or get_provider_for_model(resolved_effective_model)
    return resolved_provider, resolved_effective_model, resolved_requested_model


def _summary_term_present(case: PersonaBenchmarkCase, term: str, summary: str) -> bool:
    if term in summary:
        return True
    for alternative in case.summary_term_alternatives.get(term, ()):
        if alternative.lower() in summary:
            return True
    return False


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

    field_mismatches = [
        field_name
        for field_name, expected_value in case.expected.items()
        if parsed.get(field_name) != expected_value
    ]
    matches = [1.0 if field_name not in field_mismatches else 0.0 for field_name in case.expected]
    missing_summary_terms: list[str] = []
    if case.required_summary_terms:
        summary = str(parsed.get("summary", "")).lower()
        missing_summary_terms = [
            term for term in case.required_summary_terms if not _summary_term_present(case, term, summary)
        ]
        keyword_match_ratio = (
            len(case.required_summary_terms) - len(missing_summary_terms)
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
        elif field_mismatches:
            attempt.failure_detail = f"wrong_fields: {', '.join(field_mismatches)}"
        elif missing_summary_terms:
            attempt.failure_detail = f"summary_terms_missing: {', '.join(missing_summary_terms)}"
        else:
            attempt.failure_detail = "wrong_decision"
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
            1 for attempt in model_attempts if not attempt.infra_failure and attempt.failure_kind == "model"
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
        key=lambda summary: (
            -summary.avg_composite_score,
            -summary.pass_rate,
            summary.avg_tool_calls,
            summary.avg_total_tokens,
            summary.avg_turns,
            summary.infra_failures,
            summary.avg_latency_ms,
        )
    )
    return summaries
