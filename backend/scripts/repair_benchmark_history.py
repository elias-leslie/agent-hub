#!/usr/bin/env python3
"""Repair persisted benchmark history using current infra/model classification rules."""
# ruff: noqa: E402

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
VENV_DIR = ROOT / "backend" / ".venv"
VENV_PYTHON = VENV_DIR / "bin" / "python"

if (
    VENV_PYTHON.exists()
    and Path(sys.prefix).resolve() != VENV_DIR.resolve()
    and os.environ.get("BENCHMARK_REPAIR_NO_REEXEC") != "1"
):
    os.environ["BENCHMARK_REPAIR_NO_REEXEC"] = "1"
    os.execv(str(VENV_PYTHON), [str(VENV_PYTHON), __file__, *sys.argv[1:]])

sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

from sqlalchemy import delete, select

from app.db import async_session
from app.models import (
    AgentBenchmarkAttempt,
    AgentBenchmarkExperiment,
    AgentBenchmarkRun,
    AgentRegressionCluster,
)
from app.services._benchmark_persistence import (
    _group_attempt_failures,
    _has_scored_attempts,
    _refresh_experiment_decision,
    _update_regression_clusters,
    should_update_regression_clusters,
)
from app.services.benchmark_aggregation import aggregate_attempts, merge_efficiency_metadata
from app.services.benchmark_failure_classification import categorize_benchmark_failure_detail
from scripts.persona_benchmark_eval import normalize_attempt_identity


def _parse_csv(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


async def _load_target_runs(
    *,
    agent_slug: str,
    run_ids: list[str],
    suite_ids: list[str],
) -> list[AgentBenchmarkRun]:
    stmt = select(AgentBenchmarkRun).where(AgentBenchmarkRun.agent_slug == agent_slug)
    if run_ids:
        stmt = stmt.where(AgentBenchmarkRun.id.in_(run_ids))
    elif suite_ids:
        stmt = stmt.where(AgentBenchmarkRun.suite_id.in_(suite_ids))
    else:
        raise ValueError("Pass --run-ids or --suite-ids")

    async with async_session() as db:
        return list((await db.execute(stmt.order_by(AgentBenchmarkRun.created_at.asc()))).scalars().all())


def _reclassify_attempt(attempt: AgentBenchmarkAttempt) -> bool:
    """Return True when classification changed."""
    previous = (bool(attempt.infra_failure), attempt.failure_kind)
    category = categorize_benchmark_failure_detail(attempt.failure_detail)
    if category == "infra":
        attempt.infra_failure = True
        attempt.failure_kind = "infra"
    elif attempt.failure_detail:
        attempt.infra_failure = False
        if attempt.failure_kind in {None, "", "infra"}:
            attempt.failure_kind = "model"
    else:
        attempt.infra_failure = False
        if attempt.passed:
            attempt.failure_kind = None
    current = (bool(attempt.infra_failure), attempt.failure_kind)
    return current != previous


def _normalize_attempt_identity_fields(attempt: AgentBenchmarkAttempt) -> bool:
    """Backfill provider/model identity fields on persisted benchmark attempts."""
    model_id = str(attempt.model_id or "").strip()
    if not model_id:
        return False
    provider, effective_model, requested_model = normalize_attempt_identity(
        model_id=model_id,
        provider=attempt.provider,
        effective_model=attempt.effective_model,
        requested_model=attempt.requested_model,
    )
    changed = False
    if attempt.provider != provider:
        attempt.provider = provider
        changed = True
    if attempt.effective_model != effective_model:
        attempt.effective_model = effective_model
        changed = True
    if attempt.requested_model != requested_model:
        attempt.requested_model = requested_model
        changed = True
    return changed


def _attempt_payload(attempt: AgentBenchmarkAttempt) -> dict[str, object]:
    return {
        "case_id": attempt.case_id,
        "failure_detail": attempt.failure_detail,
        "failure_kind": attempt.failure_kind,
        "infra_failure": bool(attempt.infra_failure),
        "passed": bool(attempt.passed),
        "composite_score": float(attempt.composite_score or 0.0),
        "model_id": attempt.model_id,
    }


async def repair_history(
    *,
    agent_slug: str,
    run_ids: list[str],
    suite_ids: list[str],
    delete_infra_only_runs: bool,
    dry_run: bool,
) -> dict[str, object]:
    target_runs = await _load_target_runs(agent_slug=agent_slug, run_ids=run_ids, suite_ids=suite_ids)
    target_run_ids = [run.id for run in target_runs]
    affected_suite_ids = sorted({run.suite_id for run in target_runs if run.suite_id})
    affected_experiment_ids = sorted({run.experiment_id for run in target_runs if run.experiment_id})

    if not target_runs:
        return {
            "agent_slug": agent_slug,
            "target_runs": 0,
            "reclassified_attempts": 0,
            "normalized_attempts": 0,
            "deleted_runs": [],
            "updated_runs": [],
            "rebuilt_suite_ids": [],
            "refreshed_experiments": [],
        }

    async with async_session() as db:
        runs = (
            await db.execute(
                select(AgentBenchmarkRun)
                .where(AgentBenchmarkRun.id.in_(target_run_ids))
                .order_by(AgentBenchmarkRun.created_at.asc())
            )
        ).scalars().all()

        attempt_rows = (
            await db.execute(
                select(AgentBenchmarkAttempt)
                .where(AgentBenchmarkAttempt.benchmark_run_id.in_(target_run_ids))
                .order_by(AgentBenchmarkAttempt.created_at.asc())
            )
        ).scalars().all()

        attempts_by_run: dict[str, list[AgentBenchmarkAttempt]] = {}
        reclassified_attempts = 0
        normalized_attempts = 0
        for attempt in attempt_rows:
            attempts_by_run.setdefault(attempt.benchmark_run_id, []).append(attempt)
            if _reclassify_attempt(attempt):
                reclassified_attempts += 1
            if _normalize_attempt_identity_fields(attempt):
                normalized_attempts += 1

        deleted_run_ids: list[str] = []
        updated_run_ids: list[str] = []
        for run in runs:
            run_attempts = attempts_by_run.get(run.id, [])
            aggregate = aggregate_attempts(run_attempts)
            if delete_infra_only_runs and aggregate.scored_attempts == 0:
                deleted_run_ids.append(run.id)
                if not dry_run:
                    await db.delete(run)
                continue

            run.avg_score = aggregate.avg_score
            run.pass_rate = aggregate.pass_rate
            run.attempt_count = aggregate.total_attempts
            run.passed_attempt_count = aggregate.passed_attempt_count
            run.infra_failure_count = aggregate.infra_failure_count
            run.run_metadata = merge_efficiency_metadata(dict(run.run_metadata or {}), aggregate)
            updated_run_ids.append(run.id)

        if affected_experiment_ids:
            experiments = (
                await db.execute(
                    select(AgentBenchmarkExperiment).where(
                        AgentBenchmarkExperiment.id.in_(affected_experiment_ids)
                    )
                )
            ).scalars().all()
            for experiment in experiments:
                await _refresh_experiment_decision(db, experiment)

        if affected_suite_ids:
            if not dry_run:
                await db.execute(
                    delete(AgentRegressionCluster).where(
                        AgentRegressionCluster.agent_slug == agent_slug,
                        AgentRegressionCluster.suite_id.in_(affected_suite_ids),
                    )
                )

            surviving_runs = (
                await db.execute(
                    select(AgentBenchmarkRun)
                    .where(
                        AgentBenchmarkRun.agent_slug == agent_slug,
                        AgentBenchmarkRun.suite_id.in_(affected_suite_ids),
                        AgentBenchmarkRun.completed_at.is_not(None),
                    )
                    .order_by(AgentBenchmarkRun.completed_at.asc(), AgentBenchmarkRun.created_at.asc())
                )
            ).scalars().all()

            surviving_run_ids = [run.id for run in surviving_runs]
            surviving_attempts = (
                await db.execute(
                    select(AgentBenchmarkAttempt)
                    .where(AgentBenchmarkAttempt.benchmark_run_id.in_(surviving_run_ids))
                    .order_by(AgentBenchmarkAttempt.created_at.asc())
                )
            ).scalars().all() if surviving_run_ids else []
            surviving_attempts_by_run: dict[str, list[AgentBenchmarkAttempt]] = {}
            for attempt in surviving_attempts:
                surviving_attempts_by_run.setdefault(attempt.benchmark_run_id, []).append(attempt)

            if not dry_run:
                for run in surviving_runs:
                    run_attempt_payloads = [
                        _attempt_payload(attempt)
                        for attempt in surviving_attempts_by_run.get(run.id, [])
                    ]
                    if not should_update_regression_clusters(
                        experiment_cohort=run.experiment_cohort,
                        metadata=dict(run.run_metadata or {}),
                    ):
                        continue
                    if not _has_scored_attempts(run_attempt_payloads):
                        continue
                    grouped = _group_attempt_failures(run_attempt_payloads)
                    await _update_regression_clusters(db, run, grouped)

        if dry_run:
            await db.rollback()
        else:
            await db.commit()

    return {
        "agent_slug": agent_slug,
        "target_runs": len(target_runs),
        "reclassified_attempts": reclassified_attempts,
        "normalized_attempts": normalized_attempts,
        "deleted_runs": deleted_run_ids,
        "updated_runs": updated_run_ids,
        "rebuilt_suite_ids": affected_suite_ids,
        "refreshed_experiments": affected_experiment_ids,
    }


async def main() -> None:
    parser = argparse.ArgumentParser(description="Repair persisted benchmark history")
    parser.add_argument("--agent-slug", default="persona")
    parser.add_argument("--run-ids", help="Comma-separated benchmark run ids to repair")
    parser.add_argument("--suite-ids", help="Comma-separated suite ids to repair")
    parser.add_argument("--delete-infra-only-runs", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    result = await repair_history(
        agent_slug=args.agent_slug,
        run_ids=_parse_csv(args.run_ids),
        suite_ids=_parse_csv(args.suite_ids),
        delete_infra_only_runs=args.delete_infra_only_runs,
        dry_run=args.dry_run,
    )
    print(result)


if __name__ == "__main__":
    asyncio.run(main())
