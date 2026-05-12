"""Parsing, validation, and scoring helpers for persona benchmark evaluation."""

from __future__ import annotations

import json
import re
from typing import Any

from app.routing.registry import get_provider_for_model
from app.services.benchmark_failure_classification import classify_benchmark_failure_detail
from scripts.persona_benchmark_cases import PersonaBenchmarkCase

_VALID_ACTIONS = {"dispatch", "monitor", "block", "wait", "reconcile"}
_VALID_CONFIDENCE = {"low", "medium", "high"}
_IMPLIED_TOOL_COVERAGE: dict[str, frozenset[str]] = {
    "research_web": frozenset({"research_web", "search_web", "fetch_web_page"}),
}

_LEADING_APPLIED_CITATIONS_RE = re.compile(
    r"^(?:Applied:\s*(?:\[[MGR]:[^\]]+\]\s*)+)+"
)


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


def _normalize_tool_name(tool_name: str) -> str:
    """Normalize stored tool names so prefixed runtime variants still match."""
    normalized = tool_name.strip().lower()
    if normalized.startswith("mcp__") and "__" in normalized:
        normalized = normalized.rsplit("__", 1)[-1]
    return normalized


def _expand_tool_coverage(tool_names: set[str]) -> set[str]:
    expanded = set(tool_names)
    for tool_name in list(tool_names):
        expanded.update(_IMPLIED_TOOL_COVERAGE.get(tool_name, ()))
    return expanded


def _summary_term_present(case: PersonaBenchmarkCase, term: str, summary: str) -> bool:
    if term in summary:
        return True
    for alternative in case.summary_term_alternatives.get(term, ()):
        if alternative.lower() in summary:
            return True
    return False


def compute_correctness_score(
    case: PersonaBenchmarkCase,
    parsed: dict[str, Any],
) -> tuple[float, list[str], list[str]]:
    """Return (correctness_score, field_mismatches, missing_summary_terms)."""
    field_mismatches = [
        field_name
        for field_name, expected_value in case.expected.items()
        if parsed.get(field_name) != expected_value
    ]
    matches = [1.0 if f not in field_mismatches else 0.0 for f in case.expected]
    missing_summary_terms: list[str] = []
    if case.required_summary_terms:
        summary = str(parsed.get("summary", "")).lower()
        missing_summary_terms = [
            term for term in case.required_summary_terms
            if not _summary_term_present(case, term, summary)
        ]
        keyword_match_ratio = (
            len(case.required_summary_terms) - len(missing_summary_terms)
        ) / len(case.required_summary_terms)
        matches.append(keyword_match_ratio)
    return sum(matches) / len(matches), field_mismatches, missing_summary_terms


def check_tool_requirements(
    case: PersonaBenchmarkCase,
    tool_calls_count: int,
    used_tool_names: list[str],
) -> tuple[bool, bool, bool]:
    """Return (tool_requirement_met, generic_met, specific_met)."""
    generic_met = (not case.require_tool_call) or tool_calls_count > 0
    used_set = {_normalize_tool_name(t) for t in used_tool_names if t}
    covered_set = _expand_tool_coverage(used_set)
    required_set = {_normalize_tool_name(t) for t in case.required_tool_names if t}
    specific_met = required_set.issubset(covered_set)
    return generic_met and specific_met, generic_met, specific_met


def determine_failure_detail(
    case: PersonaBenchmarkCase,
    generic_met: bool,
    specific_met: bool,
    field_mismatches: list[str],
    missing_summary_terms: list[str],
    used_tool_names: list[str],
) -> str:
    """Return failure_detail string when an attempt does not pass."""
    if not generic_met:
        return "required_tool_call_missing"
    if not specific_met:
        required_set = {_normalize_tool_name(t) for t in case.required_tool_names if t}
        used_set = {_normalize_tool_name(t) for t in used_tool_names if t}
        missing_tools = sorted(required_set - _expand_tool_coverage(used_set))
        return f"required_tools_missing: {', '.join(missing_tools)}"
    if field_mismatches:
        return f"wrong_fields: {', '.join(field_mismatches)}"
    if missing_summary_terms:
        return f"summary_terms_missing: {', '.join(missing_summary_terms)}"
    return "wrong_decision"


def apply_scores(
    attempt: Any,
    case: PersonaBenchmarkCase,
    parsed: dict[str, Any],
) -> None:
    """Populate correctness, tool, composite, pass/fail fields on *attempt* in place."""
    attempt.correctness_score, field_mismatches, missing_summary_terms = compute_correctness_score(
        case, parsed
    )
    tool_req_met, generic_met, specific_met = check_tool_requirements(
        case, attempt.tool_calls_count, attempt.used_tool_names
    )
    attempt.tool_requirement_met = tool_req_met
    tool_score = 1.0 if tool_req_met else 0.0
    attempt.composite_score = round((attempt.correctness_score * 0.85 + tool_score * 0.15) * 100, 1)
    attempt.passed = attempt.correctness_score == 1.0 and attempt.tool_requirement_met
    if not attempt.passed:
        attempt.failure_kind = "model"
        attempt.failure_detail = determine_failure_detail(
            case, generic_met, specific_met, field_mismatches, missing_summary_terms,
            attempt.used_tool_names,
        )


def evaluate_attempt_content(attempt: Any, case: PersonaBenchmarkCase) -> bool:
    """Parse, validate, and score *attempt* content in place. Return True if done early (failure)."""
    if not attempt.content.strip():
        attempt.failure_detail = "empty_model_response"
        attempt.infra_failure = True
        attempt.failure_kind = "infra"
        return True

    parsed, parse_error = parse_benchmark_json(attempt.content)
    if parse_error:
        attempt.failure_detail = parse_error
        attempt.failure_kind = "model"
        return True

    attempt.parsed = parsed
    attempt.schema_valid, shape_error = validate_benchmark_shape(parsed)
    if not attempt.schema_valid:
        attempt.failure_detail = shape_error
        attempt.failure_kind = "model"
        return True

    apply_scores(attempt, case, parsed)
    return False
