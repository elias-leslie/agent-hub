"""Evaluation logic for parameter sweep."""

from dataclasses import dataclass
from typing import Any

from backend.scripts.sweep_config import ParameterConfig


@dataclass
class EvaluationResult:
    """Result of evaluating a parameter configuration."""

    config: ParameterConfig
    success_rate: float
    citation_rate: float
    avg_tokens: float
    avg_latency_ms: float
    score: float = 0.0
    pareto_optimal: bool = False


async def evaluate_config(config: ParameterConfig, records: list[Any]) -> EvaluationResult:
    """Evaluate a parameter configuration against historical records."""
    if not records:
        return EvaluationResult(
            config=config,
            success_rate=0.0,
            citation_rate=0.0,
            avg_tokens=0.0,
            avg_latency_ms=0.0,
        )

    total_success = total_known = total_loaded = total_cited = total_tokens = total_latency = 0

    for record in records:
        if record.task_succeeded is True:
            total_success += 1
            total_known += 1
        elif record.task_succeeded is False:
            total_known += 1

        loaded = record.memories_loaded or []
        cited = record.memories_cited or []
        total_loaded += len(loaded) if isinstance(loaded, list) else 0
        total_cited += len(cited) if isinstance(cited, list) else 0
        total_tokens += record.total_tokens or 0
        total_latency += record.injection_latency_ms or 0

    n = len(records)
    success_rate = total_success / total_known if total_known > 0 else 0.0
    citation_rate = total_cited / total_loaded if total_loaded > 0 else 0.0
    avg_tokens = total_tokens / n if n > 0 else 0.0
    avg_latency_ms = total_latency / n if n > 0 else 0.0

    # Composite score: 40% success, 30% citation, 20% token efficiency, 10% latency
    max_tokens, max_latency = 500, 200
    token_efficiency = max(0, 1 - (avg_tokens / max_tokens))
    latency_efficiency = max(0, 1 - (avg_latency_ms / max_latency))
    score = 0.4 * success_rate + 0.3 * citation_rate + 0.2 * token_efficiency + 0.1 * latency_efficiency

    return EvaluationResult(
        config=config,
        success_rate=success_rate,
        citation_rate=citation_rate,
        avg_tokens=avg_tokens,
        avg_latency_ms=avg_latency_ms,
        score=score,
    )


def find_pareto_front(results: list[EvaluationResult]) -> list[EvaluationResult]:
    """Find Pareto-optimal configurations."""
    pareto_front = []
    for candidate in results:
        is_dominated = False
        for other in results:
            if other is candidate:
                continue
            better_success = other.success_rate >= candidate.success_rate
            better_citation = other.citation_rate >= candidate.citation_rate
            better_tokens = other.avg_tokens <= candidate.avg_tokens
            strictly_better = (
                other.success_rate > candidate.success_rate
                or other.citation_rate > candidate.citation_rate
                or other.avg_tokens < candidate.avg_tokens
            )
            if better_success and better_citation and better_tokens and strictly_better:
                is_dominated = True
                break
        if not is_dominated:
            candidate.pareto_optimal = True
            pareto_front.append(candidate)
    return pareto_front
