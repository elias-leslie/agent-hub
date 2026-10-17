"""Persistence and experiment helpers for the persona model benchmark."""
from __future__ import annotations

import argparse
import logging
from collections import defaultdict
from typing import Any

from app.db import async_session
from app.services.agent_benchmark_service import (
    capture_benchmark_config_snapshot,
    get_benchmark_experiment_summary_by_key,
    persist_benchmark_payload,
)
from app.services.benchmark_aggregation import (
    aggregate_attempts,
    attempt_is_infra,
    merge_efficiency_metadata,
)
from scripts.persona_benchmark_cases import get_case_by_id
from scripts.persona_benchmark_eval import PersonaBenchmarkRun

logger = logging.getLogger(__name__)

_STATUS_COMPLETED = "completed"
_RUN_KIND = "benchmark"
_METADATA_REPORT_KEY = "report_generated"
_CONFIG_TASK_TYPE_KEY = "benchmark_task_type"


PRODUCTIVE_ACTIONS = frozenset({"dispatch", "monitor", "reconcile"})


def _read_field(item: Any, field_name: str, default: Any = None) -> Any:
    if isinstance(item, dict):
        return item.get(field_name, default)
    return getattr(item, field_name, default)


def _round_metric(value: float | None, digits: int = 1) -> float | None:
    if value is None:
        return None
    return round(float(value), digits)


def _coerce_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _preview_summary_from_snapshot(config_snapshot: dict[str, Any]) -> dict[str, Any] | None:
    preview = config_snapshot.get("preview_summary")
    if isinstance(preview, dict):
        return preview
    return None


def _prompt_tokens_from_snapshot(config_snapshot: dict[str, Any]) -> tuple[int | None, dict[str, int]]:
    preview = _preview_summary_from_snapshot(config_snapshot)
    if not preview:
        return None, {}
    total = preview.get("total_estimated_tokens")
    by_source_kind = preview.get("by_source_kind")
    return (
        _coerce_int(total) if total is not None else None,
        dict(by_source_kind) if isinstance(by_source_kind, dict) else {},
    )


def build_persona_improvement_metadata(
    attempts: list[Any],
    *,
    config_snapshot: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Derive persona-focused quality and efficiency metrics for one benchmark run."""
    aggregate = aggregate_attempts(attempts)
    scored_attempts = [attempt for attempt in attempts if not attempt_is_infra(attempt)]
    passed_attempts = [
        attempt for attempt in scored_attempts if bool(_read_field(attempt, "passed", False))
    ]
    productive_attempts: list[Any] = []
    productive_passed = 0
    family_rollups: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"attempts": 0, "passed": 0, "productive_attempts": 0}
    )
    failure_counts: dict[str, int] = defaultdict(int)

    for attempt in scored_attempts:
        case_id = str(_read_field(attempt, "case_id", "") or "")
        case_family = "unknown"
        expected_action = None
        try:
            case = get_case_by_id(case_id)
        except KeyError:
            case = None
        if case is not None:
            case_family = case.family
            expected_action = case.expected.get("primary_action")

        family_rollups[case_family]["attempts"] += 1
        if bool(_read_field(attempt, "passed", False)):
            family_rollups[case_family]["passed"] += 1
        if expected_action in PRODUCTIVE_ACTIONS:
            productive_attempts.append(attempt)
            family_rollups[case_family]["productive_attempts"] += 1
            if bool(_read_field(attempt, "passed", False)):
                productive_passed += 1
        if not bool(_read_field(attempt, "passed", False)):
            failure_detail = str(_read_field(attempt, "failure_detail", "") or "failed")
            failure_counts[failure_detail] += 1

    total_tokens = sum(_coerce_int(_read_field(attempt, "total_tokens", 0)) for attempt in scored_attempts)
    prompt_tokens, prompt_sources = _prompt_tokens_from_snapshot(dict(config_snapshot or {}))
    reliability = aggregate.pass_rate
    effectiveness = (
        round((productive_passed / len(productive_attempts)) * 100, 1)
        if productive_attempts
        else aggregate.pass_rate
    )
    tokens_per_passed_attempt = (
        round(total_tokens / len(passed_attempts), 1) if passed_attempts else None
    )
    top_failure_detail = None
    if failure_counts:
        top_failure_detail = sorted(
            failure_counts.items(),
            key=lambda item: (-item[1], item[0]),
        )[0][0]

    family_breakdown = [
        {
            "family": family,
            "attempts": int(bucket["attempts"]),
            "pass_rate": round((bucket["passed"] / bucket["attempts"]) * 100, 1)
            if bucket["attempts"]
            else 0.0,
            "productive_attempts": int(bucket["productive_attempts"]),
        }
        for family, bucket in sorted(family_rollups.items())
    ]

    return {
        "reliability": _round_metric(reliability),
        "effectiveness": _round_metric(effectiveness),
        "avg_total_tokens": _round_metric(aggregate.avg_total_tokens),
        "tokens_per_passed_attempt": _round_metric(tokens_per_passed_attempt),
        "avg_tool_calls": _round_metric(aggregate.avg_tool_calls, 2),
        "avg_turns": _round_metric(aggregate.avg_turns, 2),
        "prompt_tokens": prompt_tokens,
        "prompt_sources": prompt_sources,
        "scored_attempts": len(scored_attempts),
        "passed_attempts": len(passed_attempts),
        "productive_attempts": len(productive_attempts),
        "failure_count": len(scored_attempts) - len(passed_attempts),
        "top_failure_detail": top_failure_detail,
        "family_breakdown": family_breakdown,
    }


def _normalize_attempt(attempt: dict) -> dict:
    """Flatten parsed JSON fields onto the attempt dict."""
    raw_parsed = attempt.get("parsed")
    parsed: dict = raw_parsed if isinstance(raw_parsed, dict) else {}
    return {
        **attempt,
        "primary_action": parsed.get("primary_action"),
        "should_dispatch": parsed.get("should_dispatch"),
        "should_close": parsed.get("should_close"),
        "confidence": parsed.get("confidence"),
        "summary": parsed.get("summary"),
    }


def build_persistence_payload(
    run: PersonaBenchmarkRun,
    *,
    agent_slug: str,
    suite_id: str,
    run_kind: str,
    use_memory: bool,
    seed: int | None,
    config_snapshot: dict[str, object] | None = None,
    metadata: dict[str, object] | None = None,
    experiment: dict[str, object] | None = None,
) -> dict[str, object]:
    """Normalize a benchmark run into the persisted DB payload shape."""
    attempts = [a.to_dict() for a in run.attempts]
    aggregate = aggregate_attempts(run.attempts)
    merged_metadata = merge_efficiency_metadata(metadata, aggregate)
    if agent_slug == "persona":
        merged_metadata["persona_improvement"] = build_persona_improvement_metadata(
            run.attempts,
            config_snapshot=dict(config_snapshot or {}),
        )
    return {
        "benchmark_id": run.benchmark_id,
        "agent_slug": agent_slug,
        "project_id": run.project_id,
        "suite_id": suite_id,
        "run_kind": run_kind,
        "status": _STATUS_COMPLETED,
        "models": list(run.models),
        "case_ids": list(run.case_ids),
        "runs_per_case": run.runs_per_case,
        "use_memory": use_memory,
        "seed": seed,
        "avg_score": aggregate.avg_score,
        "pass_rate": aggregate.pass_rate,
        "attempt_count": aggregate.total_attempts,
        "passed_attempt_count": aggregate.passed_attempt_count,
        "infra_failure_count": aggregate.infra_failure_count,
        "config_snapshot": dict(config_snapshot or {}),
        "metadata": merged_metadata,
        "experiment": dict(experiment) if experiment else None,
        "started_at": run.started_at,
        "completed_at": run.completed_at,
        "attempts": [_normalize_attempt(a) for a in attempts],
    }


def _build_experiment_payload(args: argparse.Namespace, suite_id: str) -> dict[str, object] | None:
    if not args.experiment_key:
        return None
    if not args.experiment_cohort:
        raise ValueError("--experiment-cohort is required when --experiment-key is set")
    return {
        "experiment_key": args.experiment_key,
        "name": args.experiment_name or args.experiment_key,
        "cohort": args.experiment_cohort,
        "hypothesis": args.experiment_hypothesis,
        "suite_id": suite_id,
        "project_id": args.project_id,
        "min_runs_per_cohort": args.min_runs_per_cohort,
    }


def _print_experiment_summary(summary: dict) -> None:
    print("")
    print(f"Experiment status: {summary['name']} -> {summary['decision']} ({summary['decision_reason']})")
    print(
        f"  baseline: {summary['baseline']['run_count']} runs,"
        f" avg score {summary['baseline']['avg_score']},"
        f" pass {summary['baseline']['avg_pass_rate']}%"
    )
    print(
        f"  candidate: {summary['candidate']['run_count']} runs,"
        f" avg score {summary['candidate']['avg_score']},"
        f" pass {summary['candidate']['avg_pass_rate']}%"
    )
    print(
        f"  score delta: {summary['score_delta']['mean_delta']}"
        f" [{summary['score_delta']['ci_low']}, {summary['score_delta']['ci_high']}]"
    )
    print(
        f"  pass delta: {summary['pass_rate_delta']['mean_delta']}"
        f" [{summary['pass_rate_delta']['ci_low']}, {summary['pass_rate_delta']['ci_high']}]"
    )


async def _persist_run(
    run: PersonaBenchmarkRun,
    args: argparse.Namespace,
    suite_id: str,
) -> str | None:
    config_snapshot = await capture_benchmark_config_snapshot(
        args.agent_slug,
        task_type=args.task_type,
    )
    if config_snapshot is not None:
        config_snapshot = {**config_snapshot, _CONFIG_TASK_TYPE_KEY: args.task_type}
    payload = build_persistence_payload(
        run,
        agent_slug=args.agent_slug,
        suite_id=suite_id,
        run_kind=_RUN_KIND,
        use_memory=args.use_memory,
        seed=args.seed,
        config_snapshot=config_snapshot,
        metadata={_METADATA_REPORT_KEY: True},
        experiment=_build_experiment_payload(args, suite_id),
    )
    persisted_run_id = await persist_benchmark_payload(payload)
    logger.info("Persisted benchmark run as %s", persisted_run_id)
    if args.experiment_key:
        async with async_session() as db:
            summary = await get_benchmark_experiment_summary_by_key(db, args.experiment_key)
        if summary:
            _print_experiment_summary(summary)
    return persisted_run_id
