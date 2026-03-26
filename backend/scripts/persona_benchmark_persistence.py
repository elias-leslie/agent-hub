"""Persistence and experiment helpers for the persona model benchmark."""
from __future__ import annotations

import argparse
import logging

from app.db import async_session
from app.services.agent_benchmark_service import (
    capture_benchmark_config_snapshot,
    get_benchmark_experiment_summary_by_key,
    persist_benchmark_payload,
)
from app.services.benchmark_aggregation import aggregate_attempts, merge_efficiency_metadata
from app.services.memory.settings import set_active_memory_variant
from scripts.persona_benchmark_eval import PersonaBenchmarkRun

logger = logging.getLogger(__name__)

_STATUS_COMPLETED = "completed"
_RUN_KIND = "benchmark"
_COHORT_CANDIDATE = "candidate"
_DECISION_PROMOTE = "promote"
_METADATA_REPORT_KEY = "report_generated"
_CONFIG_TASK_TYPE_KEY = "benchmark_task_type"


def _normalize_attempt(attempt: dict) -> dict:
    """Flatten parsed JSON fields onto the attempt dict."""
    parsed = attempt.get("parsed") if isinstance(attempt.get("parsed"), dict) else {}
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
        "metadata": merge_efficiency_metadata(metadata, aggregate),
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


async def _maybe_promote_memory_variant(
    args: argparse.Namespace,
    summary: dict[str, object] | None,
) -> None:
    """Promote a winning candidate variant into the global memory settings row."""
    if (
        not args.promote_on_win
        or args.experiment_cohort != _COHORT_CANDIDATE
        or not args.memory_variant_override
        or not summary
        or summary.get("decision") != _DECISION_PROMOTE
    ):
        return
    await set_active_memory_variant(args.memory_variant_override)
    logger.info("Promoted active memory variant to %s", args.memory_variant_override)


async def _persist_run(
    run: PersonaBenchmarkRun,
    args: argparse.Namespace,
    suite_id: str,
) -> str | None:
    config_snapshot = await capture_benchmark_config_snapshot(
        args.agent_slug,
        task_type=args.task_type,
        memory_variant_override=args.memory_variant_override,
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
            await _maybe_promote_memory_variant(args, summary)
    return persisted_run_id
