"""Shared failure classification for benchmark and experiment surfaces."""

from __future__ import annotations

_INFRA_FAILURE_MARKERS = (
    "authentication failed",
    "check credentials",
    "api key not configured",
    "internal_server_error",
    "unexpected error occurred",
    "no response returned",
    "completion cancelled unexpectedly",
    "sdk cancelled",
    "tool loop cancelled",
    "finalize cancelled",
    "partial store cancelled",
    "idle watchdog still armed during iterator unwind",
    "async_generator_athrow",
    "upstream connect error",
    "remote connection failure",
    "transport failure",
    "connection reset",
    "timed out",
    "timeout",
    "connection refused",
    "all connection attempts failed",
    "503",
    "502",
    "rate limit",
    "empty_model_response",
)

_FORMAT_FAILURE_MARKERS = (
    "invalid_json",
    "missing_field:",
    "type_error:",
    "invalid_action",
    "invalid_confidence",
    "summary_terms_missing:",
)

_TOOLING_FAILURE_MARKERS = (
    "required_tool_call_missing",
    "required_tools_missing:",
)


def classify_benchmark_failure_detail(detail: str | None) -> tuple[bool, str | None]:
    """Classify a failure as infra or model-quality related.

    Delegates to categorize_benchmark_failure_detail for the single source of truth.
    """
    category = categorize_benchmark_failure_detail(detail)
    if category is None:
        return False, None
    return category == "infra", category if category == "infra" else "model"


def categorize_benchmark_failure_detail(detail: str | None) -> str | None:
    """Return a stable operator-facing failure category for one failure detail."""
    if not detail:
        return None
    lower = detail.lower()
    if any(marker in lower for marker in _INFRA_FAILURE_MARKERS):
        return "infra"
    if any(marker in lower for marker in _TOOLING_FAILURE_MARKERS):
        return "tooling"
    if any(marker in lower for marker in _FORMAT_FAILURE_MARKERS):
        return "format"
    return "behavior"
