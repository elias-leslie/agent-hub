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
from app.services.benchmark_aggregation import (
    EFFICIENCY_METADATA_KEY,
    run_has_scored_attempts,
    run_scored_attempt_count,
)

from ._benchmark_config import (
    heartbeat_prompt_descriptor,
    memory_state_descriptor,
    run_config_fingerprint,
)

_NON_SIGNAL_RUN_KINDS = frozenset({"honing_iteration"})


def _round_metric(value: float | None, digits: int = 1) -> float | None:
    if value is None:
        return None
    return round(float(value), digits)


def _sample_mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def is_signal_run_kind(run_kind: str | None) -> bool:
    """Return True when a run kind represents primary benchmark evidence."""
    return str(run_kind or "").strip().lower() not in _NON_SIGNAL_RUN_KINDS


def benchmark_signal_run_clause(model: Any) -> Any:
    """Return the shared SQL filter for primary benchmark evidence."""
    return model.run_kind.not_in(tuple(sorted(_NON_SIGNAL_RUN_KINDS)))


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


def _run_metadata_dict(run: Any) -> dict[str, Any]:
    raw = run.get("run_metadata") if isinstance(run, dict) else getattr(run, "run_metadata", None)
    if not isinstance(raw, dict):
        raw = run.get("metadata") if isinstance(run, dict) else getattr(run, "metadata", None)
    return dict(raw or {}) if isinstance(raw, dict) else {}


def _run_efficiency_metric(run: Any, metric_name: str) -> float | None:
    efficiency = _run_metadata_dict(run).get(EFFICIENCY_METADATA_KEY)
    if not isinstance(efficiency, dict):
        return None
    value = efficiency.get(metric_name)
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _quality_is_non_inferior(
    score_delta: dict[str, float | None],
    pass_rate_delta: dict[str, float | None],
) -> bool:
    score_low = score_delta.get("ci_low")
    pass_low = pass_rate_delta.get("ci_low")
    if score_low is None or pass_low is None:
        return False
    return float(score_low) >= -0.5 and float(pass_low) >= -1.0


def _quality_is_not_superior(
    score_delta: dict[str, float | None],
    pass_rate_delta: dict[str, float | None],
) -> bool:
    score_high = score_delta.get("ci_high")
    pass_high = pass_rate_delta.get("ci_high")
    if score_high is None or pass_high is None:
        return False
    return float(score_high) <= 0.5 and float(pass_high) <= 1.0


def _summarize_experiment_arm(
    runs: list[AgentBenchmarkRun],
    *,
    label: str,
) -> dict[str, Any]:
    scored_runs = [run for run in runs if run_has_scored_attempts(run)]
    scores = [float(run.avg_score) for run in scored_runs if run.avg_score is not None]
    pass_rates = [float(run.pass_rate) for run in scored_runs if run.pass_rate is not None]
    avg_tool_calls = [
        metric for run in scored_runs
        if (metric := _run_efficiency_metric(run, "avg_tool_calls")) is not None
    ]
    avg_total_tokens = [
        metric for run in scored_runs
        if (metric := _run_efficiency_metric(run, "avg_total_tokens")) is not None
    ]
    avg_turns = [
        metric for run in scored_runs
        if (metric := _run_efficiency_metric(run, "avg_turns")) is not None
    ]
    fingerprints = sorted({run_config_fingerprint(run) for run in scored_runs})

    prompt_version_set: set[str] = set()
    for run in scored_runs:
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
        (run.completed_at for run in scored_runs if run.completed_at is not None),
        default=None,
    )
    return {
        "label": label,
        "run_count": len(scored_runs),
        "infra_only_run_count": len(runs) - len(scored_runs),
        "avg_score": _round_metric(_sample_mean(scores)) if scores else None,
        "avg_pass_rate": _round_metric(_sample_mean(pass_rates)) if pass_rates else None,
        "avg_tool_calls": _round_metric(_sample_mean(avg_tool_calls), 2) if avg_tool_calls else None,
        "avg_total_tokens": _round_metric(_sample_mean(avg_total_tokens), 1) if avg_total_tokens else None,
        "avg_turns": _round_metric(_sample_mean(avg_turns), 2) if avg_turns else None,
        "config_fingerprints": fingerprints,
        "config_stable": len(fingerprints) <= 1,
        "prompt_versions": prompt_versions,
        "latest_completed_at": latest_completed.isoformat() if latest_completed else None,
        "_scores": scores,
        "_pass_rates": pass_rates,
        "_avg_tool_calls": avg_tool_calls,
        "_avg_total_tokens": avg_total_tokens,
        "_avg_turns": avg_turns,
    }


def _decide_experiment_outcome(
    baseline: dict[str, Any],
    candidate: dict[str, Any],
    score_delta: dict[str, float | None],
    pass_rate_delta: dict[str, float | None],
    tool_call_delta: dict[str, float | None],
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
    if (
        _quality_is_non_inferior(score_delta, pass_rate_delta)
        and tool_call_delta["ci_high"] is not None
        and float(tool_call_delta["ci_high"]) < 0.0
    ):
        return "promote", "candidate_matches_quality_with_fewer_tool_calls"
    if (
        _quality_is_not_superior(score_delta, pass_rate_delta)
        and tool_call_delta["ci_low"] is not None
        and float(tool_call_delta["ci_low"]) > 0.0
    ):
        return "rollback", "candidate_matches_quality_with_more_tool_calls"
    return "hold", "no_clear_winner"


def _effective_experiment_status(stored_status: str | None, decision: str) -> str:
    if decision in {"promote", "rollback"}:
        return "closed"
    return stored_status or "open"


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
    tool_call_delta = _bootstrap_mean_delta(
        baseline["_avg_tool_calls"], candidate["_avg_tool_calls"],
        seed_material=f"{experiment.experiment_key}:tool_calls",
    )

    min_runs = int(experiment.min_runs_per_cohort or 3)
    decision, reason = _decide_experiment_outcome(
        baseline, candidate, score_delta, pass_rate_delta, tool_call_delta, min_runs,
    )

    return {
        "experiment_key": experiment.experiment_key,
        "name": experiment.name,
        "suite_id": experiment.suite_id,
        "status": _effective_experiment_status(experiment.status, decision),
        "decision": decision,
        "decision_reason": reason,
        "hypothesis": experiment.hypothesis,
        "min_runs_per_cohort": min_runs,
        "baseline": {k: v for k, v in baseline.items() if not k.startswith("_")},
        "candidate": {k: v for k, v in candidate.items() if not k.startswith("_")},
        "score_delta": score_delta,
        "pass_rate_delta": pass_rate_delta,
        "tool_call_delta": tool_call_delta,
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
            benchmark_signal_run_clause(AgentBenchmarkRun),
            AgentBenchmarkRun.attempt_count > AgentBenchmarkRun.infra_failure_count,
        )
        .order_by(AgentBenchmarkRun.completed_at.desc())
    )
    if suite_id:
        stmt = stmt.where(AgentBenchmarkRun.suite_id == suite_id)
    return list((await db.execute(stmt)).scalars().all())


async def _query_open_clusters(
    db: AsyncSession,
    agent_slug: str,
    cutoff: datetime,
    suite_id: str | None,
) -> list[AgentRegressionCluster]:
    return await query_open_regression_clusters(
        db,
        agent_slug=agent_slug,
        cutoff=cutoff,
        suite_id=suite_id,
    )


async def query_open_regression_clusters(
    db: AsyncSession,
    *,
    agent_slug: str,
    cutoff: datetime,
    suite_id: str | None = None,
    project_id: str | None = None,
    limit: int | None = None,
) -> list[AgentRegressionCluster]:
    scoped_run_id = func.coalesce(
        AgentRegressionCluster.last_seen_run_id,
        AgentRegressionCluster.first_seen_run_id,
    )
    stmt = (
        select(AgentRegressionCluster)
        .join(AgentBenchmarkRun, AgentBenchmarkRun.id == scoped_run_id)
        .where(
            AgentRegressionCluster.agent_slug == agent_slug,
            AgentRegressionCluster.status == "open",
            AgentRegressionCluster.last_seen_at >= cutoff,
            AgentBenchmarkRun.completed_at.is_not(None),
            benchmark_signal_run_clause(AgentBenchmarkRun),
        )
        .order_by(AgentRegressionCluster.last_seen_at.desc())
    )
    if suite_id:
        stmt = stmt.where(AgentRegressionCluster.suite_id == suite_id)
    if project_id:
        stmt = stmt.where(AgentBenchmarkRun.project_id == project_id)
    if limit is not None:
        stmt = stmt.limit(limit)
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
            func.avg(AgentBenchmarkAttempt.total_tokens),
            func.avg(AgentBenchmarkAttempt.turns),
            func.avg(AgentBenchmarkAttempt.tool_calls_count),
            func.max(AgentBenchmarkRun.completed_at),
        )
        .join(AgentBenchmarkRun, AgentBenchmarkRun.id == AgentBenchmarkAttempt.benchmark_run_id)
        .where(
            AgentBenchmarkAttempt.agent_slug == agent_slug,
            AgentBenchmarkAttempt.infra_failure.is_(False),
            AgentBenchmarkRun.completed_at.is_not(None),
            AgentBenchmarkRun.completed_at >= cutoff,
            benchmark_signal_run_clause(AgentBenchmarkRun),
        )
        .group_by(AgentBenchmarkAttempt.model_id)
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
            AgentBenchmarkAttempt.infra_failure.is_(False),
            AgentBenchmarkRun.completed_at.is_not(None),
            AgentBenchmarkRun.completed_at >= cutoff,
            benchmark_signal_run_clause(AgentBenchmarkRun),
        )
        .order_by(AgentBenchmarkRun.completed_at.desc(), AgentBenchmarkAttempt.created_at.desc())
    )
    if suite_id:
        stmt = stmt.where(AgentBenchmarkRun.suite_id == suite_id)
    return list((await db.execute(stmt)).all())


async def _query_experiment_summaries(
    db: AsyncSession,
    agent_slug: str,
    cutoff: datetime,
    suite_id: str | None,
) -> list[dict[str, Any]]:
    experiments = await query_signal_experiments(
        db,
        agent_slug=agent_slug,
        cutoff=cutoff,
        suite_id=suite_id,
        limit=10,
    )
    if not experiments:
        return []

    exp_run_rows = (
        await db.execute(
            select(AgentBenchmarkRun)
            .where(
                AgentBenchmarkRun.experiment_id.in_([exp.id for exp in experiments]),
                AgentBenchmarkRun.completed_at.is_not(None),
                benchmark_signal_run_clause(AgentBenchmarkRun),
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
        for exp in experiments
    ]


async def query_signal_experiments(
    db: AsyncSession,
    *,
    agent_slug: str,
    cutoff: datetime,
    suite_id: str | None = None,
    project_id: str | None = None,
    limit: int = 10,
) -> list[AgentBenchmarkExperiment]:
    latest_signal_completed_at = func.max(AgentBenchmarkRun.completed_at).label(
        "latest_signal_completed_at"
    )
    stmt = (
        select(AgentBenchmarkExperiment, latest_signal_completed_at)
        .join(AgentBenchmarkRun, AgentBenchmarkRun.experiment_id == AgentBenchmarkExperiment.id)
        .where(
            AgentBenchmarkExperiment.agent_slug == agent_slug,
            AgentBenchmarkRun.completed_at.is_not(None),
            AgentBenchmarkRun.completed_at >= cutoff,
            benchmark_signal_run_clause(AgentBenchmarkRun),
        )
        .group_by(AgentBenchmarkExperiment.id)
        .order_by(latest_signal_completed_at.desc())
        .limit(limit)
    )
    if suite_id:
        stmt = stmt.where(AgentBenchmarkExperiment.suite_id == suite_id)
    if project_id:
        stmt = stmt.where(
            AgentBenchmarkExperiment.project_id == project_id,
            AgentBenchmarkRun.project_id == project_id,
        )
    return [row[0] for row in (await db.execute(stmt)).all()]


def _build_overview(runs: list[AgentBenchmarkRun], open_clusters_count: int) -> dict[str, Any]:
    total_attempts = sum(run_scored_attempt_count(run) for run in runs)
    total_passed = sum(int(run.passed_attempt_count or 0) for run in runs)
    score_values = [float(run.avg_score) for run in runs if run.avg_score is not None]
    avg_score = (
        round(sum(score_values) / len(score_values), 1) if score_values else 0.0
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
    formatted = [
        {
            "model_id": str(row[0]),
            "attempts": int(row[1] or 0),
            "avg_score": _round_metric(row[2]),
            "pass_rate": round((int(row[3] or 0) / int(row[1] or 1)) * 100, 1) if row[1] else 0.0,
            "avg_latency_ms": _round_metric(row[4]),
            "avg_total_tokens": _round_metric(row[5]),
            "avg_turns": _round_metric(row[6], 2),
            "avg_tool_calls": _round_metric(row[7], 2),
            "latest_completed_at": row[8].isoformat() if row[8] else None,
        }
        for row in model_rows
    ]
    def _sort_key(row: dict[str, Any]) -> tuple[Any, ...]:
        latest_completed_at = row["latest_completed_at"]
        latest_timestamp = (
            -datetime.fromisoformat(latest_completed_at).timestamp()
            if latest_completed_at
            else float("inf")
        )
        return (
            -(row["avg_score"] if row["avg_score"] is not None else -1.0),
            -row["pass_rate"],
            row["avg_tool_calls"] if row["avg_tool_calls"] is not None else float("inf"),
            row["avg_total_tokens"] if row["avg_total_tokens"] is not None else float("inf"),
            row["avg_turns"] if row["avg_turns"] is not None else float("inf"),
            -row["attempts"],
            latest_timestamp,
            row["model_id"],
        )

    return sorted(formatted, key=_sort_key)


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
        suite["attempt_count"] += run_scored_attempt_count(run)
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
    from scripts.persona_benchmark_cases import get_case_name_map

    case_names = get_case_name_map()

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
                "case_name": case_names.get(case["case_id"]),
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


async def get_agent_benchmark_run_detail(
    db: AsyncSession,
    agent_slug: str,
    run_id: str,
) -> dict[str, Any] | None:
    """Return one benchmark run with its individual attempt results."""
    from scripts.persona_benchmark_cases import get_case_name_map

    stmt = select(AgentBenchmarkRun).where(
        AgentBenchmarkRun.id == run_id,
        AgentBenchmarkRun.agent_slug == agent_slug,
    )
    run = (await db.execute(stmt)).scalars().first()
    if not run:
        return None

    attempts_stmt = (
        select(AgentBenchmarkAttempt)
        .where(AgentBenchmarkAttempt.benchmark_run_id == run_id)
        .order_by(AgentBenchmarkAttempt.case_id, AgentBenchmarkAttempt.model_id, AgentBenchmarkAttempt.run_number)
    )
    attempts = list((await db.execute(attempts_stmt)).scalars().all())
    case_names = get_case_name_map()

    return {
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
        "attempts": [
            {
                "id": attempt.id,
                "model_id": attempt.model_id,
                "case_id": attempt.case_id,
                "case_name": case_names.get(attempt.case_id),
                "run_number": attempt.run_number,
                "passed": attempt.passed,
                "composite_score": float(attempt.composite_score or 0.0),
                "correctness_score": float(attempt.correctness_score or 0.0),
                "primary_action": attempt.primary_action,
                "confidence": attempt.confidence,
                "summary": attempt.summary,
                "failure_kind": attempt.failure_kind,
                "failure_detail": attempt.failure_detail,
                "infra_failure": attempt.infra_failure,
                "tool_requirement_met": attempt.tool_requirement_met,
                "latency_ms": int(attempt.latency_ms or 0),
                "total_tokens": int(attempt.total_tokens or 0),
                "turns": int(attempt.turns or 0),
                "tool_calls_count": int(attempt.tool_calls_count or 0),
                "fallback_used": attempt.fallback_used,
                "provider": attempt.provider,
                "effective_model": attempt.effective_model,
            }
            for attempt in attempts
        ],
    }


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
    open_clusters = await _query_open_clusters(db, agent_slug, cutoff, suite_id)
    model_rows = await _query_model_performance(db, agent_slug, cutoff, suite_id)
    case_rows = await _query_case_attempts(db, agent_slug, cutoff, suite_id)
    experiment_summaries = await _query_experiment_summaries(db, agent_slug, cutoff, suite_id)
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
