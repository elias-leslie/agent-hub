"""Persistence and dashboard queries for agent benchmark tracking.

Split into sub-modules for maintainability:
  - _benchmark_config.py: config snapshot capture and fingerprinting
  - _benchmark_persistence.py: persist runs, regression clusters
  - _benchmark_dashboard.py: dashboard queries and formatting
"""

from __future__ import annotations

import random
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AgentBenchmarkExperiment, AgentBenchmarkRun

# ---------------------------------------------------------------------------
# Re-exports (preserve public API for all importers)
# ---------------------------------------------------------------------------
from ._benchmark_config import capture_benchmark_config_snapshot  # noqa: F401
from ._benchmark_config import (
    heartbeat_prompt_descriptor as _heartbeat_prompt_descriptor,
)
from ._benchmark_config import (
    memory_state_descriptor as _memory_state_descriptor,
)
from ._benchmark_config import (
    run_config_fingerprint as _run_config_fingerprint,
)
from ._benchmark_dashboard import get_agent_benchmark_dashboard  # noqa: F401
from ._benchmark_persistence import persist_benchmark_payload  # noqa: F401
from ._benchmark_persistence import (  # noqa: F401
    should_update_regression_clusters as _should_update_regression_clusters,
)

# ---------------------------------------------------------------------------
# Shared utilities
# ---------------------------------------------------------------------------


def _round_metric(value: float | None, digits: int = 1) -> float | None:
    if value is None:
        return None
    return round(float(value), digits)


def _sample_mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


# ---------------------------------------------------------------------------
# Experiment statistics
# ---------------------------------------------------------------------------


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
    fingerprints = sorted({_run_config_fingerprint(run) for run in runs})

    prompt_version_set: set[str] = set()
    for run in runs:
        cs = dict(run.config_snapshot or {})
        ps = cs.get("prompt_stack")
        if isinstance(ps, dict):
            raw = ps.get("descriptors")
            if isinstance(raw, list):
                prompt_version_set.update(str(item) for item in raw if item)
                continue
        hd = _heartbeat_prompt_descriptor(cs)
        if hd:
            prompt_version_set.add(hd)
        md = _memory_state_descriptor(cs)
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


async def get_benchmark_experiment_summary_by_key(
    db: AsyncSession,
    experiment_key: str,
) -> dict[str, Any] | None:
    experiment = await db.scalar(
        select(AgentBenchmarkExperiment).where(
            AgentBenchmarkExperiment.experiment_key == experiment_key
        )
    )
    if experiment is None:
        return None

    runs = (
        await db.execute(
            select(AgentBenchmarkRun)
            .where(
                AgentBenchmarkRun.experiment_id == experiment.id,
                AgentBenchmarkRun.completed_at.is_not(None),
            )
            .order_by(AgentBenchmarkRun.completed_at.desc())
        )
    ).scalars().all()
    return summarize_benchmark_experiment(experiment, runs)
