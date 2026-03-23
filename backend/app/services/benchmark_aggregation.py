"""Shared benchmark aggregation helpers."""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from typing import Any

EFFICIENCY_METADATA_KEY = "efficiency"


@dataclass(frozen=True)
class BenchmarkAggregate:
    """Aggregate benchmark metrics with infra failures separated from model quality."""

    total_attempts: int
    scored_attempts: int
    passed_attempt_count: int
    infra_failure_count: int
    avg_score: float | None
    pass_rate: float | None
    avg_correctness_score: float | None
    avg_latency_ms: float | None
    avg_total_tokens: float | None
    avg_turns: float | None
    avg_tool_calls: float | None


def _read_value(item: Any, field_name: str, default: Any = None) -> Any:
    if isinstance(item, dict):
        return item.get(field_name, default)
    return getattr(item, field_name, default)


def attempt_is_infra(item: Any) -> bool:
    """Return True when an attempt represents infra noise, not model signal."""
    if bool(_read_value(item, "infra_failure", False)):
        return True
    return str(_read_value(item, "failure_kind", "") or "").lower() == "infra"


def run_scored_attempt_count(run: Any) -> int:
    """Return the number of non-infra attempts inside a persisted run."""
    total_attempts = int(_read_value(run, "attempt_count", 0) or 0)
    infra_failure_count = int(_read_value(run, "infra_failure_count", 0) or 0)
    return max(0, total_attempts - infra_failure_count)


def run_has_scored_attempts(run: Any) -> bool:
    """Return True when a run contains at least one scored attempt."""
    return run_scored_attempt_count(run) > 0


def _mean_or_none(values: list[float]) -> float | None:
    if not values:
        return None
    return float(statistics.fmean(values))


def _round_or_none(value: float | None, digits: int) -> float | None:
    if value is None:
        return None
    return round(value, digits)


def build_efficiency_metadata(aggregate: BenchmarkAggregate) -> dict[str, float | None]:
    """Build the canonical persisted efficiency summary for one aggregate."""
    return {
        "avg_total_tokens": aggregate.avg_total_tokens,
        "avg_turns": aggregate.avg_turns,
        "avg_tool_calls": aggregate.avg_tool_calls,
    }


def merge_efficiency_metadata(
    metadata: dict[str, Any] | None,
    aggregate: BenchmarkAggregate,
) -> dict[str, Any]:
    """Attach the canonical efficiency snapshot to benchmark run metadata."""
    merged = dict(metadata or {})
    merged[EFFICIENCY_METADATA_KEY] = build_efficiency_metadata(aggregate)
    return merged


def aggregate_attempts(attempts: list[Any]) -> BenchmarkAggregate:
    """Aggregate attempts while excluding infra failures from quality metrics."""
    total_attempts = len(attempts)
    infra_failure_count = sum(1 for attempt in attempts if attempt_is_infra(attempt))
    scored_attempts = [attempt for attempt in attempts if not attempt_is_infra(attempt)]
    passed_attempt_count = sum(
        1 for attempt in scored_attempts if bool(_read_value(attempt, "passed", False))
    )

    score_values = [
        float(_read_value(attempt, "composite_score", 0.0) or 0.0)
        for attempt in scored_attempts
    ]
    correctness_values = [
        float(_read_value(attempt, "correctness_score", 0.0) or 0.0)
        for attempt in scored_attempts
    ]
    latency_values = [float(int(_read_value(attempt, "latency_ms", 0) or 0)) for attempt in scored_attempts]
    total_token_values = [float(int(_read_value(attempt, "total_tokens", 0) or 0)) for attempt in scored_attempts]
    turn_values = [float(int(_read_value(attempt, "turns", 0) or 0)) for attempt in scored_attempts]
    tool_call_values = [
        float(int(_read_value(attempt, "tool_calls_count", 0) or 0)) for attempt in scored_attempts
    ]

    scored_count = len(scored_attempts)
    pass_rate = None if scored_count == 0 else (passed_attempt_count / scored_count) * 100
    return BenchmarkAggregate(
        total_attempts=total_attempts,
        scored_attempts=scored_count,
        passed_attempt_count=passed_attempt_count,
        infra_failure_count=infra_failure_count,
        avg_score=_round_or_none(_mean_or_none(score_values), 1),
        pass_rate=_round_or_none(pass_rate, 1),
        avg_correctness_score=_round_or_none(_mean_or_none(correctness_values), 3),
        avg_latency_ms=_round_or_none(_mean_or_none(latency_values), 1),
        avg_total_tokens=_round_or_none(_mean_or_none(total_token_values), 1),
        avg_turns=_round_or_none(_mean_or_none(turn_values), 2),
        avg_tool_calls=_round_or_none(_mean_or_none(tool_call_values), 2),
    )
