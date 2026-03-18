"""Dashboard queries for agent benchmark tracking."""

from __future__ import annotations

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

from ._benchmark_config import heartbeat_prompt_descriptor
from .agent_benchmark_service import summarize_benchmark_experiment


def _round_metric(value: float | None, digits: int = 1) -> float | None:
    if value is None:
        return None
    return round(float(value), digits)


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
    experiment_summaries = await _query_experiment_summaries(db, agent_slug, suite_id)
    limited_runs = runs[:limit]

    return {
        "agent_slug": agent_slug,
        "overview": _build_overview(runs, len(open_clusters)),
        "trend": _format_trend(limited_runs),
        "recent_runs": _format_recent_runs(limited_runs),
        "open_regressions": _format_regressions(open_clusters),
        "model_performance": _format_model_performance(model_rows),
        "experiments": experiment_summaries,
    }
