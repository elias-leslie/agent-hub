"""Persistence pipeline for agent benchmark runs and regression clusters."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import async_session
from app.models import (
    AgentBenchmarkAttempt,
    AgentBenchmarkExperiment,
    AgentBenchmarkRun,
    AgentRegressionCluster,
)
from app.services.benchmark_aggregation import aggregate_attempts

from ._benchmark_dashboard import benchmark_signal_run_clause, summarize_benchmark_experiment


def should_update_regression_clusters(
    *,
    experiment_cohort: str | None,
    metadata: dict[str, Any],
) -> bool:
    override = metadata.get("update_regression_clusters")
    if override is not None:
        return bool(override)
    return experiment_cohort != "candidate"


async def _ensure_benchmark_experiment(
    db: AsyncSession,
    *,
    payload: dict[str, Any],
    run_agent_slug: str,
    run_project_id: str,
    run_suite_id: str,
) -> AgentBenchmarkExperiment:
    experiment_key = str(payload["experiment_key"])
    experiment = await db.scalar(
        select(AgentBenchmarkExperiment).where(
            AgentBenchmarkExperiment.experiment_key == experiment_key
        )
    )
    if experiment is None:
        experiment = AgentBenchmarkExperiment(
            experiment_key=experiment_key,
            agent_slug=run_agent_slug,
            project_id=str(payload.get("project_id") or run_project_id),
            suite_id=str(payload.get("suite_id") or run_suite_id),
            name=str(payload.get("name") or experiment_key),
            hypothesis=payload.get("hypothesis"),
            baseline_label=str(payload.get("baseline_label") or "baseline"),
            candidate_label=str(payload.get("candidate_label") or "candidate"),
            min_runs_per_cohort=int(payload.get("min_runs_per_cohort") or 3),
        )
        db.add(experiment)
        await db.flush()
        return experiment

    if payload.get("name"):
        experiment.name = str(payload["name"])
    if payload.get("hypothesis"):
        experiment.hypothesis = str(payload["hypothesis"])
    if payload.get("baseline_label"):
        experiment.baseline_label = str(payload["baseline_label"])
    if payload.get("candidate_label"):
        experiment.candidate_label = str(payload["candidate_label"])
    if payload.get("min_runs_per_cohort"):
        experiment.min_runs_per_cohort = int(payload["min_runs_per_cohort"])
    return experiment


def _make_run(
    payload: dict[str, Any],
    experiment: AgentBenchmarkExperiment | None,
    experiment_cohort: str | None,
    metadata: dict[str, Any],
) -> AgentBenchmarkRun:
    raw_started = payload.get("started_at")
    raw_completed = payload.get("completed_at")
    return AgentBenchmarkRun(
        benchmark_id=str(payload["benchmark_id"]),
        agent_slug=str(payload["agent_slug"]),
        project_id=str(payload["project_id"]),
        suite_id=str(payload["suite_id"]),
        run_kind=str(payload["run_kind"]),
        status=str(payload.get("status") or "completed"),
        experiment_id=experiment.id if experiment else None,
        experiment_cohort=experiment_cohort,
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
        run_metadata=metadata,
        started_at=(
            datetime.fromisoformat(raw_started.replace("Z", "+00:00")) if raw_started else None
        ) or datetime.now(UTC),
        completed_at=(
            datetime.fromisoformat(raw_completed.replace("Z", "+00:00")) if raw_completed else None
        ),
    )


def _make_attempt(run: AgentBenchmarkRun, attempt_payload: dict[str, Any]) -> AgentBenchmarkAttempt:
    return AgentBenchmarkAttempt(
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


def _group_attempt_failures(attempts: list[dict[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    for attempt in attempts:
        if attempt.get("passed"):
            continue
        if attempt.get("infra_failure") or str(attempt.get("failure_kind") or "") == "infra":
            continue
        case_id = str(attempt.get("case_id") or "")
        failure_detail = str(attempt.get("failure_detail") or "failed")
        key = (case_id, failure_detail)
        bucket = grouped.setdefault(
            key,
            {"case_id": case_id, "failure_detail": failure_detail,
             "occurrence_count": 0, "score_total": 0.0, "models": set()},
        )
        bucket["occurrence_count"] += 1
        bucket["score_total"] += float(attempt.get("composite_score") or 0.0)
        if model_id := str(attempt.get("model_id") or ""):
            bucket["models"].add(model_id)
    return grouped


def _has_scored_attempts(attempts: list[dict[str, Any]]) -> bool:
    """Return True when a run payload contains at least one non-infra attempt."""
    return aggregate_attempts(attempts).scored_attempts > 0


def _create_regression_cluster(
    run: AgentBenchmarkRun,
    regression_key: str,
    case_id: str,
    failure_detail: str,
    bucket: dict[str, Any],
    completed_at: datetime,
) -> AgentRegressionCluster:
    return AgentRegressionCluster(
        agent_slug=run.agent_slug,
        suite_id=run.suite_id,
        regression_key=regression_key,
        case_id=case_id,
        failure_detail=failure_detail,
        status="open",
        first_seen_run_id=run.id,
        last_seen_run_id=run.id,
        occurrence_count=bucket["occurrence_count"],
        latest_avg_score=bucket["score_total"] / bucket["occurrence_count"],
        affected_models=sorted(bucket["models"]),
        opened_at=completed_at,
        last_seen_at=completed_at,
    )


def _update_existing_cluster(
    cluster: AgentRegressionCluster,
    run: AgentBenchmarkRun,
    bucket: dict[str, Any],
    completed_at: datetime,
) -> None:
    cluster.status = "open"
    cluster.resolved_at = None
    cluster.last_seen_run_id = run.id
    cluster.last_seen_at = completed_at
    cluster.occurrence_count = int(cluster.occurrence_count or 0) + bucket["occurrence_count"]
    cluster.latest_avg_score = bucket["score_total"] / bucket["occurrence_count"]
    cluster.affected_models = sorted(bucket["models"])
    if not cluster.first_seen_run_id:
        cluster.first_seen_run_id = run.id
    if not cluster.opened_at:
        cluster.opened_at = completed_at


async def _update_regression_clusters(
    db: AsyncSession,
    run: AgentBenchmarkRun,
    grouped_failures: dict[tuple[str, str], dict[str, Any]],
) -> None:
    current_keys = {f"{case_id}::{detail}" for case_id, detail in grouped_failures}
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
        regression_key = f"{case_id}::{failure_detail}"
        cluster = open_cluster_map.get(regression_key) or await db.scalar(
            select(AgentRegressionCluster).where(
                AgentRegressionCluster.agent_slug == run.agent_slug,
                AgentRegressionCluster.suite_id == run.suite_id,
                AgentRegressionCluster.regression_key == regression_key,
            )
        )
        if cluster is None:
            db.add(_create_regression_cluster(
                run, regression_key, case_id, failure_detail, bucket, completed_at
            ))
        else:
            _update_existing_cluster(cluster, run, bucket, completed_at)

    for cluster in open_clusters:
        if cluster.regression_key not in current_keys:
            cluster.status = "resolved"
            cluster.resolved_at = completed_at


async def _refresh_experiment_decision(
    db: AsyncSession,
    experiment: AgentBenchmarkExperiment,
) -> None:
    exp_runs = (
        await db.execute(
            select(AgentBenchmarkRun).where(
                AgentBenchmarkRun.experiment_id == experiment.id,
                AgentBenchmarkRun.completed_at.is_not(None),
                benchmark_signal_run_clause(AgentBenchmarkRun),
            )
        )
    ).scalars().all()
    summary = summarize_benchmark_experiment(experiment, list(exp_runs))
    decision = str(summary["decision"])
    experiment.decision = decision
    experiment.decision_reason = summary["decision_reason"]
    experiment.status = "closed" if decision in {"promote", "rollback"} else "open"
    experiment.evidence = {
        "baseline": summary["baseline"],
        "candidate": summary["candidate"],
        "score_delta": summary["score_delta"],
        "pass_rate_delta": summary["pass_rate_delta"],
        "min_runs_per_cohort": summary["min_runs_per_cohort"],
    }


async def _persist_benchmark_payload(db: AsyncSession, payload: dict[str, Any]) -> str:
    experiment_payload = payload.get("experiment")
    experiment: AgentBenchmarkExperiment | None = None
    experiment_cohort: str | None = None
    metadata = dict(payload.get("metadata") or {})
    if isinstance(experiment_payload, dict):
        experiment = await _ensure_benchmark_experiment(
            db,
            payload=experiment_payload,
            run_agent_slug=str(payload["agent_slug"]),
            run_project_id=str(payload["project_id"]),
            run_suite_id=str(payload["suite_id"]),
        )
        experiment_cohort = str(experiment_payload.get("cohort") or "").strip().lower() or None

    run = _make_run(payload, experiment, experiment_cohort, metadata)
    db.add(run)
    await db.flush()

    attempts = list(payload.get("attempts") or [])
    for attempt_payload in attempts:
        db.add(_make_attempt(run, attempt_payload))

    if (
        should_update_regression_clusters(experiment_cohort=experiment_cohort, metadata=metadata)
        and _has_scored_attempts(attempts)
    ):
        grouped = _group_attempt_failures(attempts)
        await _update_regression_clusters(db, run, grouped)

    if experiment is not None:
        await _refresh_experiment_decision(db, experiment)

    return run.id


async def persist_benchmark_payload(payload: dict[str, Any]) -> str:
    """Persist one benchmark run and update regression cluster state."""
    async with async_session() as db:
        run_id = await _persist_benchmark_payload(db, payload)
        await db.commit()
        return run_id
