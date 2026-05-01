"""Arena system overview aggregation for the command center."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Agent,
    AgentBenchmarkRun,
    AgentRegressionCluster,
    Persona,
    PersonaScheduledJob,
)
from app.services.benchmark_failure_classification import categorize_benchmark_failure_detail
from app.services.improvement_signals import collect_improvement_signal_snapshot

from ._benchmark_dashboard import benchmark_signal_run_clause


def _round_metric(value: float | None, digits: int = 1) -> float | None:
    if value is None:
        return None
    return round(float(value), digits)


async def _query_benchmark_rows(
    db: AsyncSession,
    agent_slugs: list[str],
    cutoff: datetime,
    project_id: str | None,
) -> dict[str, dict[str, Any]]:
    stmt = (
        select(
            AgentBenchmarkRun.agent_slug.label("agent_slug"),
            func.count(AgentBenchmarkRun.id).label("total_runs"),
            func.avg(AgentBenchmarkRun.avg_score).label("avg_score"),
            func.coalesce(func.sum(AgentBenchmarkRun.attempt_count), 0).label("attempts"),
            func.coalesce(func.sum(AgentBenchmarkRun.passed_attempt_count), 0).label("passed"),
            func.max(AgentBenchmarkRun.completed_at).label("latest_completed_at"),
        )
        .where(
            AgentBenchmarkRun.agent_slug.in_(agent_slugs),
            AgentBenchmarkRun.completed_at.is_not(None),
            AgentBenchmarkRun.completed_at >= cutoff,
            benchmark_signal_run_clause(AgentBenchmarkRun),
        )
        .group_by(AgentBenchmarkRun.agent_slug)
    )
    if project_id:
        stmt = stmt.where(AgentBenchmarkRun.project_id == project_id)
    result = (await db.execute(stmt)).all()
    return {
        str(row.agent_slug): {
            "total_runs": int(row.total_runs or 0),
            "avg_score": _round_metric(row.avg_score),
            "pass_rate": _round_metric(
                (float(row.passed or 0) / float(row.attempts or 0) * 100.0)
                if row.attempts
                else None
            ),
            "latest_completed_at": (
                row.latest_completed_at.isoformat() if row.latest_completed_at else None
            ),
        }
        for row in result
    }


async def _query_regression_rows(
    db: AsyncSession,
    agent_slugs: list[str],
    cutoff: datetime,
    project_id: str | None,
) -> tuple[dict[str, int], dict[str, int]]:
    scoped_run_id = func.coalesce(
        AgentRegressionCluster.last_seen_run_id,
        AgentRegressionCluster.first_seen_run_id,
    )
    stmt = (
        select(
            AgentRegressionCluster.agent_slug.label("agent_slug"),
            AgentRegressionCluster.failure_detail.label("failure_detail"),
        )
        .join(AgentBenchmarkRun, AgentBenchmarkRun.id == scoped_run_id)
        .where(
            AgentRegressionCluster.agent_slug.in_(agent_slugs),
            AgentRegressionCluster.status == "open",
            AgentRegressionCluster.last_seen_at >= cutoff,
            AgentBenchmarkRun.completed_at.is_not(None),
            benchmark_signal_run_clause(AgentBenchmarkRun),
        )
    )
    if project_id:
        stmt = stmt.where(AgentBenchmarkRun.project_id == project_id)
    regression_rows: dict[str, int] = {}
    regression_by_category: dict[str, int] = {}
    for row in (await db.execute(stmt)).all():
        category = categorize_benchmark_failure_detail(str(row.failure_detail or "")) or "unknown"
        regression_by_category[category] = regression_by_category.get(category, 0) + 1
        if category == "behavior":
            slug = str(row.agent_slug)
            regression_rows[slug] = regression_rows.get(slug, 0) + 1
    return regression_rows, regression_by_category


async def _query_scheduled_jobs(
    db: AsyncSession,
    primary_agent_slug: str,
) -> list[dict[str, Any]]:
    persona_id_stmt = (
        select(Persona.id)
        .join(Agent, Agent.id == Persona.agent_id)
        .where(Agent.slug == primary_agent_slug)
    )
    persona_id = (await db.execute(persona_id_stmt)).scalar_one_or_none()
    if persona_id is None:
        return []
    jobs_stmt = (
        select(PersonaScheduledJob)
        .where(
            PersonaScheduledJob.persona_id == persona_id,
            PersonaScheduledJob.enabled.is_(True),
        )
        .order_by(
            PersonaScheduledJob.next_run_at.asc().nulls_last(),
            PersonaScheduledJob.created_at.desc(),
        )
    )
    return [
        {
            "id": job.id,
            "name": job.name,
            "payload_type": job.payload_type,
            "enabled": bool(job.enabled),
            "last_run_at": job.last_run_at.isoformat() if job.last_run_at else None,
            "next_run_at": job.next_run_at.isoformat() if job.next_run_at else None,
            "run_count": int(job.run_count or 0),
        }
        for job in (await db.execute(jobs_stmt)).scalars().all()
    ]


def _index_signal_snapshot(
    signal_snapshot: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    signal_volume_by_agent = {
        item["agent_slug"]: item for item in signal_snapshot["agent_signal_volume"]
    }
    top_issue_by_agent: dict[str, dict[str, Any]] = {}
    for item in signal_snapshot["repeated_issues"]:
        top_issue_by_agent.setdefault(item["agent_slug"], item)
    return signal_volume_by_agent, top_issue_by_agent


def _agent_sort_key(item: dict[str, Any]) -> tuple[Any, ...]:
    bench = item["benchmark"]
    signals = item.get("signal_volume") or {}
    return (
        -int(bench["open_regressions"] or 0),
        float(bench["avg_score"] if bench["avg_score"] is not None else 999.0),
        -int(signals.get("friction", 0)),
        item["slug"],
    )


def _build_agent_summaries(
    agent_rows: list[Any],
    benchmark_rows: dict[str, dict[str, Any]],
    regression_rows: dict[str, int],
    signal_volume_by_agent: dict[str, Any],
    top_issue_by_agent: dict[str, dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[float], list[float], int, int, int]:
    summaries: list[dict[str, Any]] = []
    score_values: list[float] = []
    pass_values: list[float] = []
    total_runs = 0
    total_regressions = 0
    agents_with_history = 0
    for agent in agent_rows:
        slug = str(agent.slug)
        bench = benchmark_rows.get(slug)
        open_regressions = regression_rows.get(slug, 0)
        total_regressions += open_regressions
        if bench:
            agents_with_history += 1
            total_runs += bench["total_runs"]
            if bench["avg_score"] is not None:
                score_values.append(float(bench["avg_score"]))
            if bench["pass_rate"] is not None:
                pass_values.append(float(bench["pass_rate"]))
        summaries.append({
            "slug": slug,
            "name": str(agent.name),
            "description": getattr(agent, "description", None),
            "benchmark": {
                "total_runs": int((bench or {}).get("total_runs") or 0),
                "avg_score": (bench or {}).get("avg_score"),
                "pass_rate": (bench or {}).get("pass_rate"),
                "open_regressions": open_regressions,
                "latest_completed_at": (bench or {}).get("latest_completed_at"),
            },
            "signal_volume": signal_volume_by_agent.get(slug),
            "top_issue": top_issue_by_agent.get(slug),
        })
    summaries.sort(key=_agent_sort_key)
    return summaries, score_values, pass_values, total_runs, total_regressions, agents_with_history


async def _fetch_arena_data(
    db: AsyncSession,
    agent_slugs: list[str],
    cutoff: datetime,
    primary_agent_slug: str,
    project_id: str | None,
    days: int,
) -> tuple[dict[str, dict[str, Any]], dict[str, int], dict[str, int], list[dict[str, Any]], dict[str, Any], dict[str, Any], dict[str, Any]]:
    benchmark_rows: dict[str, dict[str, Any]] = {}
    regression_rows: dict[str, int] = {}
    regression_by_category: dict[str, int] = {}
    if agent_slugs:
        benchmark_rows = await _query_benchmark_rows(db, agent_slugs, cutoff, project_id)
        regression_rows, regression_by_category = await _query_regression_rows(
            db,
            agent_slugs,
            cutoff,
            project_id,
        )
    scheduled_jobs = await _query_scheduled_jobs(db, primary_agent_slug)
    signal_snapshot = await collect_improvement_signal_snapshot(
        project_id=project_id,
        primary_agent_slug=primary_agent_slug,
        days_back=days,
        include_team=True,
        max_agents=8,
        max_experiments=4,
        max_clusters=6,
        max_reference_items=6,
    )
    signal_volume_by_agent, top_issue_by_agent = _index_signal_snapshot(signal_snapshot)
    return (
        benchmark_rows, regression_rows, regression_by_category,
        scheduled_jobs, signal_snapshot, signal_volume_by_agent, top_issue_by_agent,
    )


async def get_arena_overview(
    db: AsyncSession,
    *,
    active_agents: Sequence[Any],
    days: int = 30,
    project_id: str | None = None,
    primary_agent_slug: str = "persona",
) -> dict[str, Any]:
    """Return one aggregated payload for the Arena command center."""
    generated_at = datetime.now(UTC)
    cutoff = generated_at - timedelta(days=days)
    agent_rows = [agent for agent in active_agents if bool(getattr(agent, "is_active", True))]
    agent_slugs = [str(agent.slug) for agent in agent_rows if getattr(agent, "slug", None)]
    (
        benchmark_rows, regression_rows, regression_by_category,
        scheduled_jobs, signal_snapshot, signal_volume_by_agent, top_issue_by_agent,
    ) = await _fetch_arena_data(db, agent_slugs, cutoff, primary_agent_slug, project_id, days)
    agent_summaries, score_values, pass_values, total_runs, total_regressions, agents_with_history = (
        _build_agent_summaries(agent_rows, benchmark_rows, regression_rows, signal_volume_by_agent, top_issue_by_agent)
    )
    return {
        "generated_at": generated_at.isoformat(),
        "project_id": project_id,
        "primary_agent_slug": primary_agent_slug,
        "days": days,
        "system": {
            "total_agents": len(agent_rows),
            "agents_with_history": agents_with_history,
            "total_runs": total_runs,
            "avg_score": _round_metric(sum(score_values) / len(score_values)) if score_values else None,
            "avg_pass_rate": _round_metric(sum(pass_values) / len(pass_values)) if pass_values else None,
            "total_regressions": total_regressions,
            "regressions_by_category": regression_by_category,
        },
        "scheduled_jobs": scheduled_jobs,
        "agent_signal_volume": signal_snapshot["agent_signal_volume"],
        "repeated_issues": signal_snapshot["repeated_issues"],
        "recent_benchmark_experiments": signal_snapshot["recent_benchmark_experiments"],
        "open_regression_clusters": signal_snapshot["open_regression_clusters"],
        "memory_utilization": signal_snapshot["memory_utilization"],
        "memory_governance": signal_snapshot["memory_governance"],
        "low_yield_references": signal_snapshot["low_yield_references"],
        "agents": agent_summaries,
    }
