"""Persistence and dashboard queries for agent benchmark tracking."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import Integer, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import async_session
from app.models import (
    Agent,
    AgentBenchmarkAttempt,
    AgentBenchmarkRun,
    AgentRegressionCluster,
    Prompt,
)


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    normalized = value.replace("Z", "+00:00")
    return datetime.fromisoformat(normalized)


def _round_metric(value: float | None, digits: int = 1) -> float | None:
    if value is None:
        return None
    return round(float(value), digits)


def _heartbeat_prompt_descriptor(config_snapshot: dict[str, Any]) -> str | None:
    heartbeat = config_snapshot.get("heartbeat_prompt")
    if not isinstance(heartbeat, dict):
        return None
    updated_at = heartbeat.get("updated_at")
    content_hash = heartbeat.get("content_hash")
    if not updated_at or not content_hash:
        return None
    return f"{updated_at}:{content_hash}"


def _cluster_regression_key(case_id: str, failure_detail: str) -> str:
    return f"{case_id}::{failure_detail}"


def _group_attempt_failures(attempts: list[dict[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    for attempt in attempts:
        if attempt.get("passed"):
            continue
        case_id = str(attempt.get("case_id") or "")
        failure_detail = str(attempt.get("failure_detail") or "failed")
        key = (case_id, failure_detail)
        bucket = grouped.setdefault(
            key,
            {
                "case_id": case_id,
                "failure_detail": failure_detail,
                "occurrence_count": 0,
                "score_total": 0.0,
                "models": set(),
            },
        )
        bucket["occurrence_count"] += 1
        bucket["score_total"] += float(attempt.get("composite_score") or 0.0)
        model_id = str(attempt.get("model_id") or "")
        if model_id:
            bucket["models"].add(model_id)
    return grouped


async def capture_benchmark_config_snapshot(agent_slug: str) -> dict[str, Any]:
    """Capture the live agent/model/prompt state for a benchmark run."""
    async with async_session() as db:
        agent = await db.scalar(select(Agent).where(Agent.slug == agent_slug))
        if agent is None:
            return {}

        snapshot: dict[str, Any] = {
            "agent_version": agent.version,
            "primary_model_id": agent.primary_model_id,
            "fallback_models": list(agent.fallback_models or []),
            "escalation_model_id": agent.escalation_model_id,
            "thinking_level": agent.thinking_level,
            "temperature": agent.temperature,
            "captured_at": datetime.now(UTC).isoformat(),
        }

        if agent_slug == "persona":
            prompt = await db.scalar(
                select(Prompt).where(Prompt.slug == "persona-heartbeat-instructions")
            )
            if prompt is not None:
                content = prompt.content or ""
                snapshot["heartbeat_prompt"] = {
                    "slug": prompt.slug,
                    "updated_at": prompt.updated_at.isoformat() if prompt.updated_at else None,
                    "content_hash": hashlib.sha256(content.encode("utf-8")).hexdigest()[:8],
                    "content_length": len(content),
                }
        return snapshot


async def persist_benchmark_payload(payload: dict[str, Any]) -> str:
    """Persist one benchmark run and update regression cluster state."""
    async with async_session() as db:
        run_id = await _persist_benchmark_payload(db, payload)
        await db.commit()
        return run_id


async def _persist_benchmark_payload(db: AsyncSession, payload: dict[str, Any]) -> str:
    run = AgentBenchmarkRun(
        benchmark_id=str(payload["benchmark_id"]),
        agent_slug=str(payload["agent_slug"]),
        project_id=str(payload["project_id"]),
        suite_id=str(payload["suite_id"]),
        run_kind=str(payload["run_kind"]),
        status=str(payload.get("status") or "completed"),
        models=list(payload.get("models") or []),
        case_ids=list(payload.get("case_ids") or []),
        runs_per_case=int(payload.get("runs_per_case") or 1),
        use_memory=bool(payload.get("use_memory")),
        seed=payload.get("seed"),
        avg_score=payload.get("avg_score"),
        pass_rate=payload.get("pass_rate"),
        attempt_count=int(payload.get("attempt_count") or 0),
        passed_attempt_count=int(payload.get("passed_attempt_count") or 0),
        infra_failure_count=int(payload.get("infra_failure_count") or 0),
        config_snapshot=dict(payload.get("config_snapshot") or {}),
        run_metadata=dict(payload.get("metadata") or {}),
        started_at=_parse_dt(payload.get("started_at")) or datetime.now(UTC),
        completed_at=_parse_dt(payload.get("completed_at")),
    )
    db.add(run)
    await db.flush()

    attempts = list(payload.get("attempts") or [])
    for attempt_payload in attempts:
        db.add(
            AgentBenchmarkAttempt(
                benchmark_run_id=run.id,
                agent_slug=run.agent_slug,
                model_id=str(attempt_payload.get("model_id") or ""),
                effective_model=attempt_payload.get("effective_model"),
                requested_model=attempt_payload.get("requested_model"),
                case_id=str(attempt_payload.get("case_id") or ""),
                run_number=int(attempt_payload.get("run_number") or 0),
                session_id=attempt_payload.get("session_id"),
                provider=attempt_payload.get("provider"),
                latency_ms=int(attempt_payload.get("latency_ms") or 0),
                input_tokens=int(attempt_payload.get("input_tokens") or 0),
                output_tokens=int(attempt_payload.get("output_tokens") or 0),
                total_tokens=int(attempt_payload.get("total_tokens") or 0),
                turns=int(attempt_payload.get("turns") or 0),
                tool_calls_count=int(attempt_payload.get("tool_calls_count") or 0),
                used_tool_names=list(attempt_payload.get("used_tool_names") or []),
                schema_valid=bool(attempt_payload.get("schema_valid")),
                tool_requirement_met=bool(attempt_payload.get("tool_requirement_met", True)),
                correctness_score=float(attempt_payload.get("correctness_score") or 0.0),
                composite_score=float(attempt_payload.get("composite_score") or 0.0),
                passed=bool(attempt_payload.get("passed")),
                infra_failure=bool(attempt_payload.get("infra_failure")),
                failure_kind=attempt_payload.get("failure_kind"),
                failure_detail=attempt_payload.get("failure_detail"),
                fallback_used=bool(attempt_payload.get("fallback_used")),
                primary_action=attempt_payload.get("primary_action"),
                should_dispatch=attempt_payload.get("should_dispatch"),
                should_close=attempt_payload.get("should_close"),
                confidence=attempt_payload.get("confidence"),
                summary=attempt_payload.get("summary"),
                raw_content=str(attempt_payload.get("content") or ""),
            )
        )

    grouped_failures = _group_attempt_failures(attempts)
    current_keys = {_cluster_regression_key(case_id, detail) for case_id, detail in grouped_failures}

    open_clusters = (
        await db.execute(
            select(AgentRegressionCluster).where(
                AgentRegressionCluster.agent_slug == run.agent_slug,
                AgentRegressionCluster.suite_id == run.suite_id,
                AgentRegressionCluster.status == "open",
            )
        )
    ).scalars().all()

    open_cluster_map = {cluster.regression_key: cluster for cluster in open_clusters}
    completed_at = run.completed_at or datetime.now(UTC)

    for (case_id, failure_detail), bucket in grouped_failures.items():
        regression_key = _cluster_regression_key(case_id, failure_detail)
        cluster = open_cluster_map.get(regression_key)
        if cluster is None:
            cluster = await db.scalar(
                select(AgentRegressionCluster).where(
                    AgentRegressionCluster.agent_slug == run.agent_slug,
                    AgentRegressionCluster.suite_id == run.suite_id,
                    AgentRegressionCluster.regression_key == regression_key,
                )
            )
        latest_avg_score = bucket["score_total"] / bucket["occurrence_count"]
        if cluster is None:
            cluster = AgentRegressionCluster(
                agent_slug=run.agent_slug,
                suite_id=run.suite_id,
                regression_key=regression_key,
                case_id=case_id,
                failure_detail=failure_detail,
                status="open",
                first_seen_run_id=run.id,
                last_seen_run_id=run.id,
                occurrence_count=bucket["occurrence_count"],
                latest_avg_score=latest_avg_score,
                affected_models=sorted(bucket["models"]),
                opened_at=completed_at,
                last_seen_at=completed_at,
            )
            db.add(cluster)
            continue

        cluster.status = "open"
        cluster.resolved_at = None
        cluster.last_seen_run_id = run.id
        cluster.last_seen_at = completed_at
        cluster.occurrence_count = int(cluster.occurrence_count or 0) + bucket["occurrence_count"]
        cluster.latest_avg_score = latest_avg_score
        cluster.affected_models = sorted(bucket["models"])
        if not cluster.first_seen_run_id:
            cluster.first_seen_run_id = run.id
        if not cluster.opened_at:
            cluster.opened_at = completed_at

    for cluster in open_clusters:
        if cluster.regression_key in current_keys:
            continue
        cluster.status = "resolved"
        cluster.resolved_at = completed_at

    return run.id


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
    run_stmt = select(AgentBenchmarkRun).where(
        AgentBenchmarkRun.agent_slug == agent_slug,
        AgentBenchmarkRun.completed_at.is_not(None),
        AgentBenchmarkRun.completed_at >= cutoff,
    )
    if suite_id:
        run_stmt = run_stmt.where(AgentBenchmarkRun.suite_id == suite_id)
    run_stmt = run_stmt.order_by(AgentBenchmarkRun.completed_at.desc())

    runs = (await db.execute(run_stmt)).scalars().all()
    limited_runs = runs[:limit]

    cluster_stmt = select(AgentRegressionCluster).where(
        AgentRegressionCluster.agent_slug == agent_slug,
        AgentRegressionCluster.status == "open",
    )
    if suite_id:
        cluster_stmt = cluster_stmt.where(AgentRegressionCluster.suite_id == suite_id)
    cluster_stmt = cluster_stmt.order_by(AgentRegressionCluster.last_seen_at.desc())
    open_clusters = (await db.execute(cluster_stmt)).scalars().all()

    attempt_stmt = (
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
        attempt_stmt = attempt_stmt.where(AgentBenchmarkRun.suite_id == suite_id)
    model_rows = (await db.execute(attempt_stmt)).all()

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
            if model_id in seen_models:
                continue
            seen_models.add(model_id)
            tracked_models.append(model_id)

    recent_runs = [
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

    trend = [
        {
            "run_id": run.id,
            "completed_at": run.completed_at.isoformat() if run.completed_at else None,
            "suite_id": run.suite_id,
            "run_kind": run.run_kind,
            "avg_score": _round_metric(run.avg_score),
            "pass_rate": _round_metric(run.pass_rate),
            "attempts": int(run.attempt_count or 0),
            "prompt_version": _heartbeat_prompt_descriptor(dict(run.config_snapshot or {})),
        }
        for run in reversed(limited_runs)
    ]

    model_performance = [
        {
            "model_id": str(model_id),
            "attempts": int(attempts or 0),
            "avg_score": _round_metric(avg_model_score),
            "pass_rate": round((int(passed or 0) / int(attempts or 1)) * 100, 1) if attempts else 0.0,
            "avg_latency_ms": _round_metric(avg_latency),
            "latest_completed_at": latest_completed_at.isoformat() if latest_completed_at else None,
        }
        for model_id, attempts, avg_model_score, passed, avg_latency, latest_completed_at in model_rows
    ]

    return {
        "agent_slug": agent_slug,
        "overview": {
            "total_runs": len(runs),
            "avg_score": avg_score,
            "pass_rate": pass_rate,
            "open_regressions": len(open_clusters),
            "latest_completed_at": (
                runs[0].completed_at.isoformat() if runs and runs[0].completed_at else None
            ),
            "tracked_models": tracked_models,
        },
        "trend": trend,
        "recent_runs": recent_runs,
        "open_regressions": [
            {
                "regression_key": cluster.regression_key,
                "suite_id": cluster.suite_id,
                "case_id": cluster.case_id,
                "failure_detail": cluster.failure_detail,
                "status": cluster.status,
                "occurrence_count": int(cluster.occurrence_count or 0),
                "latest_avg_score": _round_metric(cluster.latest_avg_score),
                "affected_models": list(cluster.affected_models or []),
                "opened_at": cluster.opened_at.isoformat() if cluster.opened_at else None,
                "last_seen_at": cluster.last_seen_at.isoformat() if cluster.last_seen_at else None,
                "resolved_at": cluster.resolved_at.isoformat() if cluster.resolved_at else None,
            }
            for cluster in open_clusters[:10]
        ],
        "model_performance": model_performance,
    }
