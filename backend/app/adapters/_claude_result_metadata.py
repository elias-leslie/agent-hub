"""Normalize Claude SDK terminal result metadata for Agent Hub."""

from __future__ import annotations

from typing import Any


def finish_reason_from_result_subtype(subtype: str | None) -> str | None:
    """Map Claude SDK result subtype values to Agent Hub finish reasons."""
    if subtype == "error_max_turns":
        return "max_turns"
    return None


def resolve_result_finish_reason(
    message: Any,
    *,
    configured_max_turns: int | None = None,
) -> str:
    """Prefer native Claude stop metadata before local turn-budget inference."""
    explicit_finish_reason = getattr(message, "finish_reason", None)
    if isinstance(explicit_finish_reason, str) and explicit_finish_reason:
        return explicit_finish_reason

    stop_reason = getattr(message, "stop_reason", None)
    if isinstance(stop_reason, str) and stop_reason:
        return stop_reason

    subtype_finish_reason = finish_reason_from_result_subtype(
        getattr(message, "subtype", None),
    )
    if subtype_finish_reason is not None:
        return subtype_finish_reason

    if configured_max_turns is not None and configured_max_turns > 0:
        num_turns = getattr(message, "num_turns", None)
        if isinstance(num_turns, int) and num_turns >= configured_max_turns:
            return "max_turns"

    return "end_turn"


def normalized_stop_reason(
    message: Any,
    *,
    configured_max_turns: int | None = None,
) -> str | None:
    """Return a Claude-native stop_reason when one can be normalized safely."""
    stop_reason = getattr(message, "stop_reason", None)
    if isinstance(stop_reason, str) and stop_reason:
        return stop_reason

    finish_reason = resolve_result_finish_reason(
        message,
        configured_max_turns=configured_max_turns,
    )
    if finish_reason in {"end_turn", "max_turns"}:
        return finish_reason
    return None
