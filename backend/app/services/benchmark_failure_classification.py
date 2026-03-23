"""Shared failure classification for benchmark and experiment surfaces."""

from __future__ import annotations

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
    "all connection attempts failed",
    "503",
    "502",
    "rate limit",
    "claude sdk stalled after tool_result",
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
    """Classify a failure as infra or model-quality related."""
    if not detail:
        return False, None
    lower = detail.lower()
    if any(marker in lower for marker in _INFRA_FAILURE_MARKERS):
        return True, "infra"
    return False, "model"


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
