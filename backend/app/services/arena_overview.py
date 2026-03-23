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


def _round_metric(value: float | None, digits: int = 1) -> float | None:
    if value is None:
        return None
    return round(float(value), digits)


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

    benchmark_rows: dict[str, dict[str, Any]] = {}
    regression_rows: dict[str, int] = {}
    if agent_slugs:
        benchmark_stmt = (
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
            )
            .group_by(AgentBenchmarkRun.agent_slug)
        )
        benchmark_result = (await db.execute(benchmark_stmt)).all()
        benchmark_rows = {
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
            for row in benchmark_result
        }

        regression_stmt = (
            select(
                AgentRegressionCluster.agent_slug.label("agent_slug"),
                AgentRegressionCluster.failure_detail.label("failure_detail"),
            )
            .where(
                AgentRegressionCluster.agent_slug.in_(agent_slugs),
                AgentRegressionCluster.status == "open",
            )
        )
        regression_result = (await db.execute(regression_stmt)).all()
        for row in regression_result:
            failure_category = categorize_benchmark_failure_detail(str(row.failure_detail or ""))
            if failure_category != "behavior":
                continue
            regression_rows[str(row.agent_slug)] = regression_rows.get(str(row.agent_slug), 0) + 1

    persona_id_stmt = (
        select(Persona.id)
        .join(Agent, Agent.id == Persona.agent_id)
        .where(Agent.slug == primary_agent_slug)
    )
    persona_id = (await db.execute(persona_id_stmt)).scalar_one_or_none()

    scheduled_jobs: list[dict[str, Any]] = []
    if persona_id is not None:
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
        scheduled_jobs = [
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
    signal_volume_by_agent = {
        item["agent_slug"]: item for item in signal_snapshot["agent_signal_volume"]
    }
    top_issue_by_agent: dict[str, dict[str, Any]] = {}
    for item in signal_snapshot["repeated_issues"]:
        top_issue_by_agent.setdefault(item["agent_slug"], item)

    agent_summaries: list[dict[str, Any]] = []
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

        agent_summaries.append({
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

    def _sort_key(item: dict[str, Any]) -> tuple[Any, ...]:
        bench = item["benchmark"]
        signals = item.get("signal_volume") or {}
        return (
            -int(bench["open_regressions"] or 0),
            float(bench["avg_score"] if bench["avg_score"] is not None else 999.0),
            -int(signals.get("friction", 0)),
            item["slug"],
        )

    agent_summaries.sort(key=_sort_key)

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
        },
        "scheduled_jobs": scheduled_jobs,
        "agent_signal_volume": signal_snapshot["agent_signal_volume"],
        "repeated_issues": signal_snapshot["repeated_issues"],
        "recent_benchmark_experiments": signal_snapshot["recent_benchmark_experiments"],
        "open_regression_clusters": signal_snapshot["open_regression_clusters"],
        "memory_utilization": signal_snapshot["memory_utilization"],
        "low_yield_references": signal_snapshot["low_yield_references"],
        "agents": agent_summaries,
    }
