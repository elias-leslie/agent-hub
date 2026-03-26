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
    return round(float(value), digits) if value is not None else None


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
    bc, cc = len(baseline_values), len(candidate_values)
    deltas = sorted(
        _sample_mean([candidate_values[rng.randrange(cc)] for _ in range(cc)])
        - _sample_mean([baseline_values[rng.randrange(bc)] for _ in range(bc)])
        for _ in range(iterations)
    )
    mean_delta = _sample_mean(candidate_values) - _sample_mean(baseline_values)
    return {
        "mean_delta": round(mean_delta, 1),
        "ci_low": round(deltas[max(0, int(iterations * 0.025))], 1),
        "ci_high": round(deltas[min(iterations - 1, int(iterations * 0.975))], 1),
    }


def _arm_efficiency(scored_runs: list[AgentBenchmarkRun]) -> dict[str, list[float]]:
    """Collect per-metric efficiency float lists from run metadata."""
    result: dict[str, list[float]] = {"avg_tool_calls": [], "avg_total_tokens": [], "avg_turns": []}
    for run in scored_runs:
        raw = getattr(run, "run_metadata", None) or getattr(run, "metadata", None)
        eff = raw.get(EFFICIENCY_METADATA_KEY) if isinstance(raw, dict) else None
        if not isinstance(eff, dict):
            continue
        for key in result:
            val = eff.get(key)
            if isinstance(val, (int, float)):
                result[key].append(float(val))
    return result


def _summarize_experiment_arm(runs: list[AgentBenchmarkRun], *, label: str) -> dict[str, Any]:
    scored = [r for r in runs if run_has_scored_attempts(r)]
    scores = [float(r.avg_score) for r in scored if r.avg_score is not None]
    prs = [float(r.pass_rate) for r in scored if r.pass_rate is not None]
    eff = _arm_efficiency(scored)
    fp = sorted({run_config_fingerprint(r) for r in scored})
    # collect prompt versions inline
    pv: set[str] = set()
    for run in scored:
        cs = dict(run.config_snapshot or {})
        ps = cs.get("prompt_stack")
        descs = ps.get("descriptors") if isinstance(ps, dict) else None
        if not isinstance(descs, list):
            gc = cs.get("generated_context")
            descs = gc.get("descriptors") if isinstance(gc, dict) else None
        pv.update(str(d) for d in (descs or []) if d)
        if hd := heartbeat_prompt_descriptor(cs):
            pv.add(hd)
        if md := memory_state_descriptor(cs):
            pv.add(f"memory:{md}")
    latest = max((r.completed_at for r in scored if r.completed_at), default=None)
    arm = lambda vs, d=1: _round_metric(_sample_mean(vs), d) if vs else None  # noqa: E731
    return {
        "label": label, "run_count": len(scored), "infra_only_run_count": len(runs) - len(scored),
        "avg_score": arm(scores), "avg_pass_rate": arm(prs),
        "avg_tool_calls": arm(eff["avg_tool_calls"], 2), "avg_total_tokens": arm(eff["avg_total_tokens"]),
        "avg_turns": arm(eff["avg_turns"], 2), "config_fingerprints": fp, "config_stable": len(fp) <= 1,
        "prompt_versions": sorted(pv), "latest_completed_at": latest.isoformat() if latest else None,
        "_scores": scores, "_pass_rates": prs,
        "_avg_tool_calls": eff["avg_tool_calls"], "_avg_total_tokens": eff["avg_total_tokens"],
        "_avg_turns": eff["avg_turns"],
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
    s_low, p_low = score_delta.get("ci_low"), pass_rate_delta.get("ci_low")
    s_high, p_high = score_delta.get("ci_high"), pass_rate_delta.get("ci_high")
    if s_low is not None and p_low is not None and float(s_low) > 0.5 and float(p_low) >= -1.0:
        return "promote", "candidate_outperforms_baseline"
    if s_high is not None and p_high is not None and (
        (float(s_high) <= 0.0 and float(score_delta.get("mean_delta") or 0.0) <= -0.5)
        or (float(p_high) <= 0.0 and float(pass_rate_delta.get("mean_delta") or 0.0) <= -1.0)
    ):
        return "rollback", "candidate_underperforms_baseline"
    tc_high, tc_low = tool_call_delta.get("ci_high"), tool_call_delta.get("ci_low")
    if (s_low is not None and p_low is not None
            and float(s_low) >= -0.5 and float(p_low) >= -1.0
            and tc_high is not None and float(tc_high) < 0.0):
        return "promote", "candidate_matches_quality_with_fewer_tool_calls"
    if (s_high is not None and p_high is not None
            and float(s_high) <= 0.5 and float(p_high) <= 1.0
            and tc_low is not None and float(tc_low) > 0.0):
        return "rollback", "candidate_matches_quality_with_more_tool_calls"
    return "hold", "no_clear_winner"


def summarize_benchmark_experiment(
    experiment: AgentBenchmarkExperiment,
    runs: list[AgentBenchmarkRun],
) -> dict[str, Any]:
    baseline = _summarize_experiment_arm(
        [r for r in runs if r.experiment_cohort == "baseline"], label=experiment.baseline_label,
    )
    candidate = _summarize_experiment_arm(
        [r for r in runs if r.experiment_cohort == "candidate"], label=experiment.candidate_label,
    )
    seed = experiment.experiment_key
    score_delta = _bootstrap_mean_delta(baseline["_scores"], candidate["_scores"], seed_material=f"{seed}:score")
    pass_rate_delta = _bootstrap_mean_delta(baseline["_pass_rates"], candidate["_pass_rates"], seed_material=f"{seed}:pass_rate")
    tool_call_delta = _bootstrap_mean_delta(baseline["_avg_tool_calls"], candidate["_avg_tool_calls"], seed_material=f"{seed}:tool_calls")
    min_runs = int(experiment.min_runs_per_cohort or 3)
    decision, reason = _decide_experiment_outcome(baseline, candidate, score_delta, pass_rate_delta, tool_call_delta, min_runs)
    status = "closed" if decision in {"promote", "rollback"} else (experiment.status or "open")
    return {
        "experiment_key": experiment.experiment_key, "name": experiment.name,
        "suite_id": experiment.suite_id, "status": status, "decision": decision,
        "decision_reason": reason, "hypothesis": experiment.hypothesis,
        "min_runs_per_cohort": min_runs,
        "baseline": {k: v for k, v in baseline.items() if not k.startswith("_")},
        "candidate": {k: v for k, v in candidate.items() if not k.startswith("_")},
        "score_delta": score_delta, "pass_rate_delta": pass_rate_delta, "tool_call_delta": tool_call_delta,
        "updated_at": experiment.updated_at.isoformat() if experiment.updated_at else None,
        "created_at": experiment.created_at.isoformat() if experiment.created_at else None,
    }


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
        AgentRegressionCluster.last_seen_run_id, AgentRegressionCluster.first_seen_run_id,
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
        select(AgentBenchmarkAttempt, AgentBenchmarkRun.suite_id, AgentBenchmarkRun.completed_at)
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
    db: AsyncSession, agent_slug: str, cutoff: datetime, suite_id: str | None,
) -> list[dict[str, Any]]:
    experiments = await query_signal_experiments(db, agent_slug=agent_slug, cutoff=cutoff, suite_id=suite_id, limit=10)
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
    return [summarize_benchmark_experiment(exp, runs_by_experiment.get(exp.id, [])) for exp in experiments]


async def query_signal_experiments(
    db: AsyncSession,
    *,
    agent_slug: str,
    cutoff: datetime,
    suite_id: str | None = None,
    project_id: str | None = None,
    limit: int = 10,
) -> list[AgentBenchmarkExperiment]:
    latest_signal_completed_at = func.max(AgentBenchmarkRun.completed_at).label("latest_signal_completed_at")
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


def _format_dashboard_sections(
    runs: list[AgentBenchmarkRun],
    open_clusters_count: int,
    limited: list[AgentBenchmarkRun],
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    """Build overview dict, trend list, and recent-runs list in one pass."""
    total = sum(run_scored_attempt_count(r) for r in runs)
    passed = sum(int(r.passed_attempt_count or 0) for r in runs)
    scores = [float(r.avg_score) for r in runs if r.avg_score is not None]
    seen: set[str] = set()
    tracked = [m for r in runs for m in (r.models or []) if m not in seen and not seen.add(m)]  # type: ignore[func-returns-value]
    overview = {
        "total_runs": len(runs),
        "avg_score": round(sum(scores) / len(scores), 1) if scores else 0.0,
        "pass_rate": round(passed / total * 100, 1) if total else 0.0,
        "open_regressions": open_clusters_count,
        "latest_completed_at": runs[0].completed_at.isoformat() if runs and runs[0].completed_at else None,
        "tracked_models": tracked,
    }
    trend = [
        {"run_id": r.id, "completed_at": r.completed_at.isoformat() if r.completed_at else None,
         "suite_id": r.suite_id, "run_kind": r.run_kind, "avg_score": _round_metric(r.avg_score),
         "pass_rate": _round_metric(r.pass_rate), "attempts": int(r.attempt_count or 0),
         "prompt_version": heartbeat_prompt_descriptor(dict(r.config_snapshot or {}))}
        for r in reversed(limited)
    ]
    recent = [
        {"run_id": r.id, "benchmark_id": r.benchmark_id, "suite_id": r.suite_id, "run_kind": r.run_kind,
         "started_at": r.started_at.isoformat(), "completed_at": r.completed_at.isoformat() if r.completed_at else None,
         "avg_score": _round_metric(r.avg_score), "pass_rate": _round_metric(r.pass_rate),
         "attempt_count": int(r.attempt_count or 0), "passed_attempt_count": int(r.passed_attempt_count or 0),
         "infra_failure_count": int(r.infra_failure_count or 0), "models": list(r.models or []),
         "case_ids": list(r.case_ids or []), "config_snapshot": dict(r.config_snapshot or {}),
         "metadata": dict(r.run_metadata or {})}
        for r in limited
    ]
    return overview, trend, recent


def _format_model_performance(model_rows: list[Any]) -> list[dict[str, Any]]:
    def _sort_key(row: dict[str, Any]) -> tuple[Any, ...]:
        ts = row["latest_completed_at"]
        return (
            -(row["avg_score"] if row["avg_score"] is not None else -1.0),
            -row["pass_rate"],
            row["avg_tool_calls"] if row["avg_tool_calls"] is not None else float("inf"),
            row["avg_total_tokens"] if row["avg_total_tokens"] is not None else float("inf"),
            row["avg_turns"] if row["avg_turns"] is not None else float("inf"),
            -row["attempts"],
            -datetime.fromisoformat(ts).timestamp() if ts else float("inf"),
            row["model_id"],
        )
    formatted = [
        {"model_id": str(row[0]), "attempts": int(row[1] or 0),
         "avg_score": _round_metric(row[2]),
         "pass_rate": round((int(row[3] or 0) / int(row[1] or 1)) * 100, 1) if row[1] else 0.0,
         "avg_latency_ms": _round_metric(row[4]), "avg_total_tokens": _round_metric(row[5]),
         "avg_turns": _round_metric(row[6], 2), "avg_tool_calls": _round_metric(row[7], 2),
         "latest_completed_at": row[8].isoformat() if row[8] else None}
        for row in model_rows
    ]
    return sorted(formatted, key=_sort_key)


def _format_suites(
    runs: list[AgentBenchmarkRun],
    open_clusters: list[AgentRegressionCluster],
) -> list[dict[str, Any]]:
    regs: dict[str, int] = defaultdict(int)
    for c in open_clusters:
        regs[c.suite_id] += 1
    rollups: dict[str, dict[str, Any]] = {}
    for run in runs:
        s = rollups.setdefault(run.suite_id, {
            "suite_id": run.suite_id, "run_count": 0, "score_values": [],
            "attempt_count": 0, "passed_attempt_count": 0,
            "latest_completed_at": run.completed_at,
            "tracked_models": set(), "case_ids": set(), "run_kinds": set(),
        })
        s["run_count"] += 1
        s["attempt_count"] += run_scored_attempt_count(run)
        s["passed_attempt_count"] += int(run.passed_attempt_count or 0)
        if run.avg_score is not None:
            s["score_values"].append(float(run.avg_score))
        if run.completed_at and (s["latest_completed_at"] is None or run.completed_at > s["latest_completed_at"]):
            s["latest_completed_at"] = run.completed_at
        s["tracked_models"].update(str(m) for m in (run.models or []) if m)
        s["case_ids"].update(str(c) for c in (run.case_ids or []) if c)
        if run.run_kind:
            s["run_kinds"].add(str(run.run_kind))
    out = []
    for s in rollups.values():
        atts, passed = int(s["attempt_count"] or 0), int(s["passed_attempt_count"] or 0)
        scores = list(s["score_values"])
        out.append({
            "suite_id": s["suite_id"], "run_count": int(s["run_count"] or 0),
            "avg_score": _round_metric(_sample_mean(scores)) if scores else None,
            "pass_rate": round(passed / atts * 100, 1) if atts else 0.0,
            "open_regressions": int(regs.get(s["suite_id"], 0)),
            "latest_completed_at": s["latest_completed_at"].isoformat() if s["latest_completed_at"] else None,
            "tracked_models": sorted(s["tracked_models"]),
            "case_ids": sorted(s["case_ids"]),
            "run_kinds": sorted(s["run_kinds"]),
        })
    return sorted(out, key=lambda s: (-(s["open_regressions"]), -(s["avg_score"] if s["avg_score"] is not None else -1.0), s["latest_completed_at"] or ""))


def _format_cases(
    case_rows: list[Any],
    open_clusters: list[AgentRegressionCluster],
) -> list[dict[str, Any]]:
    from scripts.persona_benchmark_cases import get_case_name_map
    case_names = get_case_name_map()
    regs: dict[str, int] = defaultdict(int)
    latest_fail: dict[str, str] = {}
    for c in open_clusters:
        regs[c.case_id] += 1
        latest_fail.setdefault(c.case_id, c.failure_detail)
    rollups: dict[str, dict[str, Any]] = {}
    for attempt, suite_id, completed_at in case_rows:
        case = rollups.setdefault(attempt.case_id, {
            "case_id": attempt.case_id, "attempts": 0, "passed": 0, "score_values": [],
            "latest_completed_at": completed_at, "tracked_models": set(), "suite_ids": set(),
            "latest_failure_detail": latest_fail.get(attempt.case_id),
        })
        case["attempts"] += 1
        case["passed"] += 1 if attempt.passed else 0
        case["score_values"].append(float(attempt.composite_score or 0.0))
        if completed_at and (case["latest_completed_at"] is None or completed_at > case["latest_completed_at"]):
            case["latest_completed_at"] = completed_at
        if attempt.model_id:
            case["tracked_models"].add(str(attempt.model_id))
        if suite_id:
            case["suite_ids"].add(str(suite_id))
        if not case["latest_failure_detail"] and attempt.failure_detail:
            case["latest_failure_detail"] = attempt.failure_detail
    out = []
    for case in rollups.values():
        atts, passed = int(case["attempts"] or 0), int(case["passed"] or 0)
        scores = list(case["score_values"])
        out.append({
            "case_id": case["case_id"], "case_name": case_names.get(case["case_id"]),
            "attempts": atts, "pass_rate": round(passed / atts * 100, 1) if atts else 0.0,
            "avg_score": _round_metric(_sample_mean(scores)) if scores else None,
            "open_regressions": int(regs.get(case["case_id"], 0)),
            "latest_completed_at": case["latest_completed_at"].isoformat() if case["latest_completed_at"] else None,
            "latest_failure_detail": case["latest_failure_detail"],
            "tracked_models": sorted(case["tracked_models"]),
            "suite_ids": sorted(case["suite_ids"]),
        })
    return sorted(out, key=lambda c: (-(c["open_regressions"]), c["avg_score"] if c["avg_score"] is not None else 999.0, -(c["attempts"]), c["latest_completed_at"] or ""))[:20]


async def get_agent_benchmark_run_detail(
    db: AsyncSession,
    agent_slug: str,
    run_id: str,
) -> dict[str, Any] | None:
    """Return one benchmark run with its individual attempt results."""
    from scripts.persona_benchmark_cases import get_case_name_map
    run = (await db.execute(
        select(AgentBenchmarkRun).where(AgentBenchmarkRun.id == run_id, AgentBenchmarkRun.agent_slug == agent_slug)
    )).scalars().first()
    if not run:
        return None
    attempts = list((await db.execute(
        select(AgentBenchmarkAttempt)
        .where(AgentBenchmarkAttempt.benchmark_run_id == run_id)
        .order_by(AgentBenchmarkAttempt.case_id, AgentBenchmarkAttempt.model_id, AgentBenchmarkAttempt.run_number)
    )).scalars().all())
    case_names = get_case_name_map()
    return {
        "run_id": run.id, "benchmark_id": run.benchmark_id, "suite_id": run.suite_id, "run_kind": run.run_kind,
        "started_at": run.started_at.isoformat(),
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
        "avg_score": _round_metric(run.avg_score), "pass_rate": _round_metric(run.pass_rate),
        "attempt_count": int(run.attempt_count or 0), "passed_attempt_count": int(run.passed_attempt_count or 0),
        "infra_failure_count": int(run.infra_failure_count or 0),
        "models": list(run.models or []), "case_ids": list(run.case_ids or []),
        "attempts": [
            {"id": a.id, "model_id": a.model_id, "case_id": a.case_id, "case_name": case_names.get(a.case_id),
             "run_number": a.run_number, "passed": a.passed,
             "composite_score": float(a.composite_score or 0.0), "correctness_score": float(a.correctness_score or 0.0),
             "primary_action": a.primary_action, "confidence": a.confidence, "summary": a.summary,
             "failure_kind": a.failure_kind, "failure_detail": a.failure_detail, "infra_failure": a.infra_failure,
             "tool_requirement_met": a.tool_requirement_met,
             "latency_ms": int(a.latency_ms or 0), "total_tokens": int(a.total_tokens or 0),
             "turns": int(a.turns or 0), "tool_calls_count": int(a.tool_calls_count or 0),
             "fallback_used": a.fallback_used, "provider": a.provider, "effective_model": a.effective_model}
            for a in attempts
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
    runs = list((await db.execute(stmt)).scalars().all())
    open_clusters = await query_open_regression_clusters(db, agent_slug=agent_slug, cutoff=cutoff, suite_id=suite_id)
    model_rows = await _query_model_performance(db, agent_slug, cutoff, suite_id)
    case_rows = await _query_case_attempts(db, agent_slug, cutoff, suite_id)
    experiments = await _query_experiment_summaries(db, agent_slug, cutoff, suite_id)
    overview, trend, recent = _format_dashboard_sections(runs, len(open_clusters), runs[:limit])
    return {
        "agent_slug": agent_slug,
        "overview": overview,
        "trend": trend,
        "recent_runs": recent,
        "open_regressions": [
            {"regression_key": c.regression_key, "suite_id": c.suite_id, "case_id": c.case_id,
             "failure_detail": c.failure_detail, "status": c.status, "occurrence_count": int(c.occurrence_count or 0),
             "latest_avg_score": _round_metric(c.latest_avg_score), "affected_models": list(c.affected_models or []),
             "opened_at": c.opened_at.isoformat() if c.opened_at else None,
             "last_seen_at": c.last_seen_at.isoformat() if c.last_seen_at else None,
             "resolved_at": c.resolved_at.isoformat() if c.resolved_at else None}
            for c in open_clusters[:10]
        ],
        "model_performance": _format_model_performance(model_rows),
        "suites": _format_suites(runs, open_clusters),
        "cases": _format_cases(case_rows, open_clusters),
        "experiments": experiments,
    }
