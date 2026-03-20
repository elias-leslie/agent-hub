"""Dashboard queries for agent benchmark tracking."""

from __future__ import annotations

import random
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import Integer, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    AgentBenchmarkAttempt,
    AgentBenchmarkExperiment,
    AgentBenchmarkRun,
    AgentRegressionCluster,
)

from ._benchmark_config import (
    heartbeat_prompt_descriptor,
    memory_state_descriptor,
    run_config_fingerprint,
)


def _round_metric(value: float | None, digits: int = 1) -> float | None:
    if value is None:
        return None
    return round(float(value), digits)


def _sample_mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _bootstrap_mean_delta(
    baseline_values: list[float],
    candidate_values: list[float],
    *,
    iterations: int = 2000,
    seed_material: str = "benchmark-experiment",
) -> dict[str, float | None]:
    if not baseline_values or not candidate_values:
        return {"mean_delta": None, "ci_low": None, "ci_high": None}

    rng = random.Random(seed_material)
    deltas: list[float] = []
    baseline_count = len(baseline_values)
    candidate_count = len(candidate_values)

    for _ in range(iterations):
        baseline_sample = [baseline_values[rng.randrange(baseline_count)] for _ in range(baseline_count)]
        candidate_sample = [candidate_values[rng.randrange(candidate_count)] for _ in range(candidate_count)]
        deltas.append(_sample_mean(candidate_sample) - _sample_mean(baseline_sample))

    deltas.sort()
    low_index = max(0, int(iterations * 0.025))
    high_index = min(iterations - 1, int(iterations * 0.975))
    mean_delta = _sample_mean(candidate_values) - _sample_mean(baseline_values)
    return {
        "mean_delta": round(mean_delta, 1),
        "ci_low": round(deltas[low_index], 1),
        "ci_high": round(deltas[high_index], 1),
    }


def _summarize_experiment_arm(
    runs: list[AgentBenchmarkRun],
    *,
    label: str,
) -> dict[str, Any]:
    scores = [float(run.avg_score or 0.0) for run in runs]
    pass_rates = [float(run.pass_rate or 0.0) for run in runs]
    fingerprints = sorted({run_config_fingerprint(run) for run in runs})

    prompt_version_set: set[str] = set()
    for run in runs:
        cs = dict(run.config_snapshot or {})
        ps = cs.get("prompt_stack")
        if isinstance(ps, dict):
            raw = ps.get("descriptors")
            if isinstance(raw, list):
                prompt_version_set.update(str(item) for item in raw if item)
                continue
        hd = heartbeat_prompt_descriptor(cs)
        if hd:
            prompt_version_set.add(hd)
        md = memory_state_descriptor(cs)
        if md:
            prompt_version_set.add(f"memory:{md}")
    prompt_versions = sorted(prompt_version_set)

    latest_completed = max(
        (run.completed_at for run in runs if run.completed_at is not None),
        default=None,
    )
    return {
        "label": label,
        "run_count": len(runs),
        "avg_score": _round_metric(_sample_mean(scores)) if scores else None,
        "avg_pass_rate": _round_metric(_sample_mean(pass_rates)) if pass_rates else None,
        "config_fingerprints": fingerprints,
        "config_stable": len(fingerprints) <= 1,
        "prompt_versions": prompt_versions,
        "latest_completed_at": latest_completed.isoformat() if latest_completed else None,
        "_scores": scores,
        "_pass_rates": pass_rates,
    }


def _decide_experiment_outcome(
    baseline: dict[str, Any],
    candidate: dict[str, Any],
    score_delta: dict[str, float | None],
    pass_rate_delta: dict[str, float | None],
    min_runs: int,
) -> tuple[str, str]:
    if min(baseline["run_count"], candidate["run_count"]) < min_runs:
        return "hold", "underpowered"
    if not baseline["config_stable"] or not candidate["config_stable"]:
        return "hold", "mixed_config"
    if (
        score_delta["ci_low"] is not None
        and pass_rate_delta["ci_low"] is not None
        and float(score_delta["ci_low"]) > 0.5
        and float(pass_rate_delta["ci_low"]) >= -1.0
    ):
        return "promote", "candidate_outperforms_baseline"
    if (
        score_delta["ci_high"] is not None
        and pass_rate_delta["ci_high"] is not None
        and (
            (
                float(score_delta["ci_high"]) <= 0.0
                and float(score_delta["mean_delta"] or 0.0) <= -0.5
            )
            or (
                float(pass_rate_delta["ci_high"]) <= 0.0
                and float(pass_rate_delta["mean_delta"] or 0.0) <= -1.0
            )
        )
    ):
        return "rollback", "candidate_underperforms_baseline"
    return "hold", "no_clear_winner"


def summarize_benchmark_experiment(
    experiment: AgentBenchmarkExperiment,
    runs: list[AgentBenchmarkRun],
) -> dict[str, Any]:
    baseline_runs = [run for run in runs if run.experiment_cohort == "baseline"]
    candidate_runs = [run for run in runs if run.experiment_cohort == "candidate"]

    baseline = _summarize_experiment_arm(runs=baseline_runs, label=experiment.baseline_label)
    candidate = _summarize_experiment_arm(runs=candidate_runs, label=experiment.candidate_label)

    score_delta = _bootstrap_mean_delta(
        baseline["_scores"], candidate["_scores"],
        seed_material=f"{experiment.experiment_key}:score",
    )
    pass_rate_delta = _bootstrap_mean_delta(
        baseline["_pass_rates"], candidate["_pass_rates"],
        seed_material=f"{experiment.experiment_key}:pass_rate",
    )

    min_runs = int(experiment.min_runs_per_cohort or 3)
    decision, reason = _decide_experiment_outcome(
        baseline, candidate, score_delta, pass_rate_delta, min_runs,
    )

    return {
        "experiment_key": experiment.experiment_key,
        "name": experiment.name,
        "suite_id": experiment.suite_id,
        "status": experiment.status,
        "decision": decision,
        "decision_reason": reason,
        "hypothesis": experiment.hypothesis,
        "min_runs_per_cohort": min_runs,
        "baseline": {k: v for k, v in baseline.items() if not k.startswith("_")},
        "candidate": {k: v for k, v in candidate.items() if not k.startswith("_")},
        "score_delta": score_delta,
        "pass_rate_delta": pass_rate_delta,
        "updated_at": experiment.updated_at.isoformat() if experiment.updated_at else None,
        "created_at": experiment.created_at.isoformat() if experiment.created_at else None,
    }


async def _query_recent_runs(
    db: AsyncSession, agent_slug: str, cutoff: datetime, suite_id: str | None,
) -> list[AgentBenchmarkRun]:
    stmt = (
        select(AgentBenchmarkRun)
        .where(
            AgentBenchmarkRun.agent_slug == agent_slug,
            AgentBenchmarkRun.completed_at.is_not(None),
            AgentBenchmarkRun.completed_at >= cutoff,
        )
        .order_by(AgentBenchmarkRun.completed_at.desc())
    )
    if suite_id:
        stmt = stmt.where(AgentBenchmarkRun.suite_id == suite_id)
    return list((await db.execute(stmt)).scalars().all())


async def _query_open_clusters(
    db: AsyncSession, agent_slug: str, suite_id: str | None,
) -> list[AgentRegressionCluster]:
    stmt = (
        select(AgentRegressionCluster)
        .where(
            AgentRegressionCluster.agent_slug == agent_slug,
            AgentRegressionCluster.status == "open",
        )
        .order_by(AgentRegressionCluster.last_seen_at.desc())
    )
    if suite_id:
        stmt = stmt.where(AgentRegressionCluster.suite_id == suite_id)
    return list((await db.execute(stmt)).scalars().all())


async def _query_model_performance(
    db: AsyncSession, agent_slug: str, cutoff: datetime, suite_id: str | None,
) -> list[Any]:
    stmt = (
        select(
            AgentBenchmarkAttempt.model_id,
            func.count(AgentBenchmarkAttempt.id),
            func.avg(AgentBenchmarkAttempt.composite_score),
            func.sum(func.cast(AgentBenchmarkAttempt.passed, Integer)),
            func.avg(AgentBenchmarkAttempt.latency_ms),
            func.max(AgentBenchmarkRun.completed_at),
        )
        .join(AgentBenchmarkRun, AgentBenchmarkRun.id == AgentBenchmarkAttempt.benchmark_run_id)
        .where(
            AgentBenchmarkAttempt.agent_slug == agent_slug,
            AgentBenchmarkRun.completed_at.is_not(None),
            AgentBenchmarkRun.completed_at >= cutoff,
        )
        .group_by(AgentBenchmarkAttempt.model_id)
        .order_by(func.avg(AgentBenchmarkAttempt.composite_score).desc())
    )
    if suite_id:
        stmt = stmt.where(AgentBenchmarkRun.suite_id == suite_id)
    return list((await db.execute(stmt)).all())


async def _query_case_attempts(
    db: AsyncSession, agent_slug: str, cutoff: datetime, suite_id: str | None,
) -> list[Any]:
    stmt = (
        select(
            AgentBenchmarkAttempt,
            AgentBenchmarkRun.suite_id,
            AgentBenchmarkRun.completed_at,
        )
        .join(AgentBenchmarkRun, AgentBenchmarkRun.id == AgentBenchmarkAttempt.benchmark_run_id)
        .where(
            AgentBenchmarkAttempt.agent_slug == agent_slug,
            AgentBenchmarkRun.completed_at.is_not(None),
            AgentBenchmarkRun.completed_at >= cutoff,
        )
        .order_by(AgentBenchmarkRun.completed_at.desc(), AgentBenchmarkAttempt.created_at.desc())
    )
    if suite_id:
        stmt = stmt.where(AgentBenchmarkRun.suite_id == suite_id)
    return list((await db.execute(stmt)).all())


async def _query_experiment_summaries(
    db: AsyncSession, agent_slug: str, suite_id: str | None,
) -> list[dict[str, Any]]:
    stmt = (
        select(AgentBenchmarkExperiment)
        .where(AgentBenchmarkExperiment.agent_slug == agent_slug)
        .order_by(AgentBenchmarkExperiment.updated_at.desc())
    )
    if suite_id:
        stmt = stmt.where(AgentBenchmarkExperiment.suite_id == suite_id)
    experiments = list((await db.execute(stmt)).scalars().all())

    top_experiments = experiments[:10]
    if not top_experiments:
        return []

    exp_run_rows = (
        await db.execute(
            select(AgentBenchmarkRun)
            .where(
                AgentBenchmarkRun.experiment_id.in_([exp.id for exp in top_experiments]),
                AgentBenchmarkRun.completed_at.is_not(None),
            )
            .order_by(AgentBenchmarkRun.completed_at.desc())
        )
    ).scalars().all()
    runs_by_experiment: dict[str, list[AgentBenchmarkRun]] = {}
    for exp_run in exp_run_rows:
        if exp_run.experiment_id:
            runs_by_experiment.setdefault(exp_run.experiment_id, []).append(exp_run)
    return [
        summarize_benchmark_experiment(exp, runs_by_experiment.get(exp.id, []))
        for exp in top_experiments
    ]


def _build_overview(runs: list[AgentBenchmarkRun], open_clusters_count: int) -> dict[str, Any]:
    total_attempts = sum(int(run.attempt_count or 0) for run in runs)
    total_passed = sum(int(run.passed_attempt_count or 0) for run in runs)
    avg_score = (
        round(sum(float(run.avg_score or 0.0) for run in runs) / len(runs), 1) if runs else 0.0
    )
    pass_rate = round((total_passed / total_attempts) * 100, 1) if total_attempts else 0.0

    tracked_models: list[str] = []
    seen_models: set[str] = set()
    for run in runs:
        for model_id in run.models or []:
            if model_id not in seen_models:
                seen_models.add(model_id)
                tracked_models.append(model_id)

    return {
        "total_runs": len(runs),
        "avg_score": avg_score,
        "pass_rate": pass_rate,
        "open_regressions": open_clusters_count,
        "latest_completed_at": (
            runs[0].completed_at.isoformat() if runs and runs[0].completed_at else None
        ),
        "tracked_models": tracked_models,
    }


def _format_trend(limited_runs: list[AgentBenchmarkRun]) -> list[dict[str, Any]]:
    return [
        {
            "run_id": run.id,
            "completed_at": run.completed_at.isoformat() if run.completed_at else None,
            "suite_id": run.suite_id,
            "run_kind": run.run_kind,
            "avg_score": _round_metric(run.avg_score),
            "pass_rate": _round_metric(run.pass_rate),
            "attempts": int(run.attempt_count or 0),
            "prompt_version": heartbeat_prompt_descriptor(dict(run.config_snapshot or {})),
        }
        for run in reversed(limited_runs)
    ]


def _format_recent_runs(limited_runs: list[AgentBenchmarkRun]) -> list[dict[str, Any]]:
    return [
        {
            "run_id": run.id,
            "benchmark_id": run.benchmark_id,
            "suite_id": run.suite_id,
            "run_kind": run.run_kind,
            "started_at": run.started_at.isoformat(),
            "completed_at": run.completed_at.isoformat() if run.completed_at else None,
            "avg_score": _round_metric(run.avg_score),
            "pass_rate": _round_metric(run.pass_rate),
            "attempt_count": int(run.attempt_count or 0),
            "passed_attempt_count": int(run.passed_attempt_count or 0),
            "infra_failure_count": int(run.infra_failure_count or 0),
            "models": list(run.models or []),
            "case_ids": list(run.case_ids or []),
            "config_snapshot": dict(run.config_snapshot or {}),
            "metadata": dict(run.run_metadata or {}),
        }
        for run in limited_runs
    ]


def _format_regressions(clusters: list[AgentRegressionCluster]) -> list[dict[str, Any]]:
    return [
        {
            "regression_key": c.regression_key,
            "suite_id": c.suite_id,
            "case_id": c.case_id,
            "failure_detail": c.failure_detail,
            "status": c.status,
            "occurrence_count": int(c.occurrence_count or 0),
            "latest_avg_score": _round_metric(c.latest_avg_score),
            "affected_models": list(c.affected_models or []),
            "opened_at": c.opened_at.isoformat() if c.opened_at else None,
            "last_seen_at": c.last_seen_at.isoformat() if c.last_seen_at else None,
            "resolved_at": c.resolved_at.isoformat() if c.resolved_at else None,
        }
        for c in clusters[:10]
    ]


def _format_model_performance(model_rows: list[Any]) -> list[dict[str, Any]]:
    return [
        {
            "model_id": str(row[0]),
            "attempts": int(row[1] or 0),
            "avg_score": _round_metric(row[2]),
            "pass_rate": round((int(row[3] or 0) / int(row[1] or 1)) * 100, 1) if row[1] else 0.0,
            "avg_latency_ms": _round_metric(row[4]),
            "latest_completed_at": row[5].isoformat() if row[5] else None,
        }
        for row in model_rows
    ]


def _format_suites(
    runs: list[AgentBenchmarkRun],
    open_clusters: list[AgentRegressionCluster],
) -> list[dict[str, Any]]:
    regressions_by_suite = defaultdict(int)
    for cluster in open_clusters:
        regressions_by_suite[cluster.suite_id] += 1

    rollups: dict[str, dict[str, Any]] = {}
    for run in runs:
        suite = rollups.setdefault(
            run.suite_id,
            {
                "suite_id": run.suite_id,
                "run_count": 0,
                "score_values": [],
                "attempt_count": 0,
                "passed_attempt_count": 0,
                "latest_completed_at": run.completed_at,
                "tracked_models": set(),
                "case_ids": set(),
                "run_kinds": set(),
            },
        )
        suite["run_count"] += 1
        suite["attempt_count"] += int(run.attempt_count or 0)
        suite["passed_attempt_count"] += int(run.passed_attempt_count or 0)
        if run.avg_score is not None:
            suite["score_values"].append(float(run.avg_score))
        if run.completed_at and (
            suite["latest_completed_at"] is None
            or run.completed_at > suite["latest_completed_at"]
        ):
            suite["latest_completed_at"] = run.completed_at
        suite["tracked_models"].update(str(model) for model in (run.models or []) if model)
        suite["case_ids"].update(str(case_id) for case_id in (run.case_ids or []) if case_id)
        if run.run_kind:
            suite["run_kinds"].add(str(run.run_kind))

    formatted = []
    for suite in rollups.values():
        attempts = int(suite["attempt_count"] or 0)
        passed = int(suite["passed_attempt_count"] or 0)
        score_values = list(suite["score_values"])
        formatted.append(
            {
                "suite_id": suite["suite_id"],
                "run_count": int(suite["run_count"] or 0),
                "avg_score": _round_metric(_sample_mean(score_values)) if score_values else None,
                "pass_rate": round((passed / attempts) * 100, 1) if attempts else 0.0,
                "open_regressions": int(regressions_by_suite.get(suite["suite_id"], 0)),
                "latest_completed_at": (
                    suite["latest_completed_at"].isoformat()
                    if suite["latest_completed_at"]
                    else None
                ),
                "tracked_models": sorted(suite["tracked_models"]),
                "case_ids": sorted(suite["case_ids"]),
                "run_kinds": sorted(suite["run_kinds"]),
            }
        )

    return sorted(
        formatted,
        key=lambda suite: (
            -(suite["open_regressions"]),
            -(suite["avg_score"] if suite["avg_score"] is not None else -1.0),
            suite["latest_completed_at"] or "",
        ),
        reverse=False,
    )


def _format_cases(
    case_rows: list[Any],
    open_clusters: list[AgentRegressionCluster],
) -> list[dict[str, Any]]:
    regressions_by_case = defaultdict(int)
    latest_failure_by_case: dict[str, str] = {}
    for cluster in open_clusters:
        regressions_by_case[cluster.case_id] += 1
        latest_failure_by_case.setdefault(cluster.case_id, cluster.failure_detail)

    rollups: dict[str, dict[str, Any]] = {}
    for attempt, suite_id, completed_at in case_rows:
        case = rollups.setdefault(
            attempt.case_id,
            {
                "case_id": attempt.case_id,
                "attempts": 0,
                "passed": 0,
                "score_values": [],
                "latest_completed_at": completed_at,
                "tracked_models": set(),
                "suite_ids": set(),
                "latest_failure_detail": latest_failure_by_case.get(attempt.case_id),
            },
        )
        case["attempts"] += 1
        case["passed"] += 1 if attempt.passed else 0
        case["score_values"].append(float(attempt.composite_score or 0.0))
        if completed_at and (
            case["latest_completed_at"] is None
            or completed_at > case["latest_completed_at"]
        ):
            case["latest_completed_at"] = completed_at
        if attempt.model_id:
            case["tracked_models"].add(str(attempt.model_id))
        if suite_id:
            case["suite_ids"].add(str(suite_id))
        if not case["latest_failure_detail"] and attempt.failure_detail:
            case["latest_failure_detail"] = attempt.failure_detail

    formatted = []
    for case in rollups.values():
        attempts = int(case["attempts"] or 0)
        passed = int(case["passed"] or 0)
        score_values = list(case["score_values"])
        formatted.append(
            {
                "case_id": case["case_id"],
                "attempts": attempts,
                "pass_rate": round((passed / attempts) * 100, 1) if attempts else 0.0,
                "avg_score": _round_metric(_sample_mean(score_values)) if score_values else None,
                "open_regressions": int(regressions_by_case.get(case["case_id"], 0)),
                "latest_completed_at": (
                    case["latest_completed_at"].isoformat()
                    if case["latest_completed_at"]
                    else None
                ),
                "latest_failure_detail": case["latest_failure_detail"],
                "tracked_models": sorted(case["tracked_models"]),
                "suite_ids": sorted(case["suite_ids"]),
            }
        )

    return sorted(
        formatted,
        key=lambda case: (
            -(case["open_regressions"]),
            case["avg_score"] if case["avg_score"] is not None else 999.0,
            -(case["attempts"]),
            case["latest_completed_at"] or "",
        ),
        reverse=False,
    )[:20]


async def get_agent_benchmark_dashboard(
    db: AsyncSession,
    agent_slug: str,
    *,
    days: int = 30,
    limit: int = 20,
    suite_id: str | None = None,
) -> dict[str, Any]:
    """Return benchmark history, trendlines, and open regression state."""
    cutoff = datetime.now(UTC) - timedelta(days=days)

    runs = await _query_recent_runs(db, agent_slug, cutoff, suite_id)
    open_clusters = await _query_open_clusters(db, agent_slug, suite_id)
    model_rows = await _query_model_performance(db, agent_slug, cutoff, suite_id)
    case_rows = await _query_case_attempts(db, agent_slug, cutoff, suite_id)
    experiment_summaries = await _query_experiment_summaries(db, agent_slug, suite_id)
    limited_runs = runs[:limit]

    return {
        "agent_slug": agent_slug,
        "overview": _build_overview(runs, len(open_clusters)),
        "trend": _format_trend(limited_runs),
        "recent_runs": _format_recent_runs(limited_runs),
        "open_regressions": _format_regressions(open_clusters),
        "model_performance": _format_model_performance(model_rows),
        "suites": _format_suites(runs, open_clusters),
        "cases": _format_cases(case_rows, open_clusters),
        "experiments": experiment_summaries,
    }
