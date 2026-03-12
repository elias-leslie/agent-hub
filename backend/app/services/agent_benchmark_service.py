"""Persistence and dashboard queries for agent benchmark tracking."""

from __future__ import annotations

import hashlib
import json
import random
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import Integer, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import async_session
from app.models import (
    Agent,
    AgentBenchmarkAttempt,
    AgentBenchmarkExperiment,
    AgentBenchmarkRun,
    AgentRegressionCluster,
    Persona,
    Prompt,
)
from app.services.prompt_catalog import (
    COMPLETION_REVIEW_PROMPT_SLUG,
    COMPLETION_REVIEW_RULES_PROMPT_SLUG,
    PERSONA_FOCUS_HARNESS_PROMPT_SLUG,
    PERSONA_HEARTBEAT_INSTRUCTIONS_PROMPT_SLUG,
    PERSONA_HEARTBEAT_PROMPT_SLUG,
    PERSONA_WAKE_GUIDANCE_PROMPT_SLUG,
)
from app.services.runtime_prompt_stack import collect_runtime_prompt_sections


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


def _prompt_stack_descriptors(config_snapshot: dict[str, Any]) -> list[str]:
    prompt_stack = config_snapshot.get("prompt_stack")
    if isinstance(prompt_stack, dict):
        descriptors = prompt_stack.get("descriptors")
        if isinstance(descriptors, list):
            return sorted({str(item) for item in descriptors if item})
    heartbeat_descriptor = _heartbeat_prompt_descriptor(config_snapshot)
    return [heartbeat_descriptor] if heartbeat_descriptor else []


def _describe_prompt_row(prompt: Prompt | None) -> dict[str, Any] | None:
    if prompt is None:
        return None
    content = prompt.content or ""
    return {
        "slug": prompt.slug,
        "updated_at": prompt.updated_at.isoformat() if prompt.updated_at else None,
        "content_hash": hashlib.sha256(content.encode("utf-8")).hexdigest()[:8],
        "content_length": len(content),
    }


def _cluster_regression_key(case_id: str, failure_detail: str) -> str:
    return f"{case_id}::{failure_detail}"


def _normalize_config_snapshot_for_fingerprint(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _normalize_config_snapshot_for_fingerprint(item)
            for key, item in value.items()
            if key != "captured_at"
        }
    if isinstance(value, list):
        return [_normalize_config_snapshot_for_fingerprint(item) for item in value]
    return value


def _config_fingerprint(config_snapshot: dict[str, Any]) -> str:
    normalized = _normalize_config_snapshot_for_fingerprint(config_snapshot or {})
    serialized = json.dumps(normalized, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()[:10]


def _run_config_fingerprint(run: AgentBenchmarkRun) -> str:
    payload = {
        "config_snapshot": _normalize_config_snapshot_for_fingerprint(dict(run.config_snapshot or {})),
        "models": list(getattr(run, "models", []) or []),
        "case_ids": list(getattr(run, "case_ids", []) or []),
        "runs_per_case": int(getattr(run, "runs_per_case", 1) or 1),
        "use_memory": bool(getattr(run, "use_memory", False)),
        "run_kind": str(getattr(run, "run_kind", "") or ""),
    }
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()[:10]


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
    fingerprints = sorted({_run_config_fingerprint(run) for run in runs})
    prompt_versions = sorted(
        {
            descriptor
            for run in runs
            for descriptor in _prompt_stack_descriptors(dict(run.config_snapshot or {}))
            if descriptor
        }
    )
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
    """Return (decision, reason) based on experiment arm statistics."""
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
        baseline["_scores"],
        candidate["_scores"],
        seed_material=f"{experiment.experiment_key}:score",
    )
    pass_rate_delta = _bootstrap_mean_delta(
        baseline["_pass_rates"],
        candidate["_pass_rates"],
        seed_material=f"{experiment.experiment_key}:pass_rate",
    )

    min_runs = int(experiment.min_runs_per_cohort or 3)
    decision, reason = _decide_experiment_outcome(baseline, candidate, score_delta, pass_rate_delta, min_runs)

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


def _should_update_regression_clusters(
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


async def _refresh_benchmark_experiment(
    db: AsyncSession,
    experiment: AgentBenchmarkExperiment,
) -> dict[str, Any]:
    runs = (
        await db.execute(
            select(AgentBenchmarkRun).where(
                AgentBenchmarkRun.experiment_id == experiment.id,
                AgentBenchmarkRun.completed_at.is_not(None),
            )
        )
    ).scalars().all()

    summary = summarize_benchmark_experiment(experiment, runs)
    experiment.decision = str(summary["decision"])
    experiment.decision_reason = summary["decision_reason"]
    experiment.evidence = {
        "baseline": summary["baseline"],
        "candidate": summary["candidate"],
        "score_delta": summary["score_delta"],
        "pass_rate_delta": summary["pass_rate_delta"],
        "min_runs_per_cohort": summary["min_runs_per_cohort"],
    }
    return summary


def _task_prompt_slugs(task_type: str | None) -> list[str]:
    if task_type == "heartbeat":
        return [
            PERSONA_HEARTBEAT_PROMPT_SLUG,
            PERSONA_HEARTBEAT_INSTRUCTIONS_PROMPT_SLUG,
            PERSONA_FOCUS_HARNESS_PROMPT_SLUG,
        ]
    if task_type == "wake":
        return [
            PERSONA_WAKE_GUIDANCE_PROMPT_SLUG,
            PERSONA_FOCUS_HARNESS_PROMPT_SLUG,
        ]
    if task_type == "review":
        return [
            COMPLETION_REVIEW_PROMPT_SLUG,
            COMPLETION_REVIEW_RULES_PROMPT_SLUG,
        ]
    return []


async def _capture_persona_snapshot(db: AsyncSession, agent: Agent) -> dict[str, Any]:
    """Return persona-specific config fields for the benchmark snapshot."""
    persona = await db.scalar(select(Persona).where(Persona.agent_id == agent.id))
    snapshot: dict[str, Any] = {}

    if persona is not None:
        from app.services.persona_document_prompt_service import (
            get_persona_personality_document,
            get_persona_user_context_document,
        )

        personality_text = await get_persona_personality_document(db) or ""
        user_context_text = await get_persona_user_context_document(db) or ""
        snapshot["persona_documents"] = {
            "personality": {
                "content_hash": hashlib.sha256(personality_text.encode("utf-8")).hexdigest()[:8],
                "content_length": len(personality_text),
            },
            "user_context": {
                "content_hash": hashlib.sha256(user_context_text.encode("utf-8")).hexdigest()[:8],
                "content_length": len(user_context_text),
            },
            "user_profile": {
                "content_hash": hashlib.sha256(
                    json.dumps(persona.user_profile or {}, sort_keys=True).encode("utf-8")
                ).hexdigest()[:8],
                "field_count": len(persona.user_profile or {}),
            },
            "onboarding_phase": persona.onboarding_phase,
        }

    prompt = await db.scalar(
        select(Prompt).where(Prompt.slug == PERSONA_HEARTBEAT_INSTRUCTIONS_PROMPT_SLUG)
    )
    descriptor = _describe_prompt_row(prompt)
    if descriptor is not None:
        snapshot["heartbeat_prompt"] = descriptor

    reviewer_agent = await db.scalar(select(Agent).where(Agent.slug == "supervisor"))
    if reviewer_agent is not None:
        snapshot["completion_reviewer"] = {
            "agent_slug": reviewer_agent.slug,
            "agent_version": reviewer_agent.version,
            "primary_model_id": reviewer_agent.primary_model_id,
            "fallback_models": list(reviewer_agent.fallback_models or []),
            "escalation_model_id": reviewer_agent.escalation_model_id,
            "thinking_level": reviewer_agent.thinking_level,
            "temperature": reviewer_agent.temperature,
        }
    return snapshot


async def capture_benchmark_config_snapshot(
    agent_slug: str,
    *,
    task_type: str | None = None,
) -> dict[str, Any]:
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

        prompt_sections = await collect_runtime_prompt_sections(db, agent, task_type=task_type)
        snapshot["prompt_stack"] = {
            "task_type": task_type,
            "system_sections": [section.to_snapshot_dict() for section in prompt_sections],
            "descriptors": [
                f"{section.source_kind}:{section.source_id}:{section.content_hash}"
                for section in prompt_sections
            ],
        }

        task_prompt_sources: list[dict[str, Any]] = []
        for prompt_slug in _task_prompt_slugs(task_type):
            prompt = await db.scalar(select(Prompt).where(Prompt.slug == prompt_slug))
            descriptor = _describe_prompt_row(prompt)
            if descriptor:
                task_prompt_sources.append(descriptor)
        if task_prompt_sources:
            snapshot["prompt_stack"]["task_prompt_sources"] = task_prompt_sources

        if agent_slug == "persona":
            snapshot.update(await _capture_persona_snapshot(db, agent))

        return snapshot


async def persist_benchmark_payload(payload: dict[str, Any]) -> str:
    """Persist one benchmark run and update regression cluster state."""
    async with async_session() as db:
        run_id = await _persist_benchmark_payload(db, payload)
        await db.commit()
        return run_id


def _make_run(
    payload: dict[str, Any],
    experiment: AgentBenchmarkExperiment | None,
    experiment_cohort: str | None,
    metadata: dict[str, Any],
) -> AgentBenchmarkRun:
    """Construct an AgentBenchmarkRun from a payload dict."""
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
        started_at=_parse_dt(payload.get("started_at")) or datetime.now(UTC),
        completed_at=_parse_dt(payload.get("completed_at")),
    )


def _make_attempt(run: AgentBenchmarkRun, attempt_payload: dict[str, Any]) -> AgentBenchmarkAttempt:
    """Construct an AgentBenchmarkAttempt from a payload dict."""
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


async def _upsert_regression_cluster(
    db: AsyncSession,
    run: AgentBenchmarkRun,
    case_id: str,
    failure_detail: str,
    bucket: dict[str, Any],
    open_cluster_map: dict[str, AgentRegressionCluster],
    completed_at: datetime,
) -> None:
    """Create or update a single regression cluster for one failure bucket."""
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
        db.add(AgentRegressionCluster(
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
        ))
        return
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


async def _update_regression_clusters(
    db: AsyncSession,
    run: AgentBenchmarkRun,
    grouped_failures: dict[tuple[str, str], dict[str, Any]],
) -> None:
    """Upsert open/resolved regression clusters based on this run's failures."""
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
        await _upsert_regression_cluster(
            db, run, case_id, failure_detail, bucket, open_cluster_map, completed_at
        )
    for cluster in open_clusters:
        if cluster.regression_key not in current_keys:
            cluster.status = "resolved"
            cluster.resolved_at = completed_at


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

    if _should_update_regression_clusters(experiment_cohort=experiment_cohort, metadata=metadata):
        await _update_regression_clusters(db, run, _group_attempt_failures(attempts))

    if experiment is not None:
        await _refresh_benchmark_experiment(db, experiment)

    return run.id


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


# --- Dashboard query helpers -------------------------------------------------


async def _query_recent_runs(
    db: AsyncSession,
    agent_slug: str,
    suite_id: str | None,
    cutoff: datetime,
):
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
    return (await db.execute(stmt)).scalars().all()


async def _query_open_clusters(
    db: AsyncSession,
    agent_slug: str,
    suite_id: str | None,
):
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
    return (await db.execute(stmt)).scalars().all()


async def _query_experiments(
    db: AsyncSession,
    agent_slug: str,
    suite_id: str | None,
):
    stmt = (
        select(AgentBenchmarkExperiment)
        .where(AgentBenchmarkExperiment.agent_slug == agent_slug)
        .order_by(AgentBenchmarkExperiment.updated_at.desc())
    )
    if suite_id:
        stmt = stmt.where(AgentBenchmarkExperiment.suite_id == suite_id)
    return (await db.execute(stmt)).scalars().all()


async def _query_model_performance(
    db: AsyncSession,
    agent_slug: str,
    suite_id: str | None,
    cutoff: datetime,
):
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
    return (await db.execute(stmt)).all()


async def _fetch_experiment_summaries(
    db: AsyncSession,
    experiments: list[AgentBenchmarkExperiment],
) -> list[dict[str, Any]]:
    if not experiments:
        return []
    experiment_run_rows = (
        await db.execute(
            select(AgentBenchmarkRun)
            .where(
                AgentBenchmarkRun.experiment_id.in_([exp.id for exp in experiments]),
                AgentBenchmarkRun.completed_at.is_not(None),
            )
            .order_by(AgentBenchmarkRun.completed_at.desc())
        )
    ).scalars().all()

    runs_by_experiment: dict[str, list[AgentBenchmarkRun]] = {}
    for run in experiment_run_rows:
        if run.experiment_id:
            runs_by_experiment.setdefault(run.experiment_id, []).append(run)

    return [
        summarize_benchmark_experiment(exp, runs_by_experiment.get(exp.id, []))
        for exp in experiments
    ]


# --- Dashboard serializers ---------------------------------------------------


def _serialize_run(run: AgentBenchmarkRun) -> dict[str, Any]:
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
        "config_snapshot": dict(run.config_snapshot or {}),
        "metadata": dict(run.run_metadata or {}),
    }


def _serialize_trend_point(run: AgentBenchmarkRun) -> dict[str, Any]:
    return {
        "run_id": run.id,
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
        "suite_id": run.suite_id,
        "run_kind": run.run_kind,
        "avg_score": _round_metric(run.avg_score),
        "pass_rate": _round_metric(run.pass_rate),
        "attempts": int(run.attempt_count or 0),
        "prompt_version": _heartbeat_prompt_descriptor(dict(run.config_snapshot or {})),
    }


def _serialize_cluster(cluster: AgentRegressionCluster) -> dict[str, Any]:
    return {
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


def _serialize_model_row(row: Any) -> dict[str, Any]:
    model_id, attempts, avg_model_score, passed, avg_latency, latest_completed_at = row
    return {
        "model_id": str(model_id),
        "attempts": int(attempts or 0),
        "avg_score": _round_metric(avg_model_score),
        "pass_rate": round((int(passed or 0) / int(attempts or 1)) * 100, 1) if attempts else 0.0,
        "avg_latency_ms": _round_metric(avg_latency),
        "latest_completed_at": latest_completed_at.isoformat() if latest_completed_at else None,
    }


def _collect_tracked_models(runs: list[AgentBenchmarkRun]) -> list[str]:
    tracked: list[str] = []
    seen: set[str] = set()
    for run in runs:
        for model_id in run.models or []:
            if model_id not in seen:
                seen.add(model_id)
                tracked.append(model_id)
    return tracked


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
    runs = await _query_recent_runs(db, agent_slug, suite_id, cutoff)
    limited_runs = runs[:limit]
    open_clusters = await _query_open_clusters(db, agent_slug, suite_id)
    experiments = await _query_experiments(db, agent_slug, suite_id)
    model_rows = await _query_model_performance(db, agent_slug, suite_id, cutoff)

    total_attempts = sum(int(run.attempt_count or 0) for run in runs)
    total_passed = sum(int(run.passed_attempt_count or 0) for run in runs)
    avg_score = (
        round(sum(float(run.avg_score or 0.0) for run in runs) / len(runs), 1) if runs else 0.0
    )
    pass_rate = round((total_passed / total_attempts) * 100, 1) if total_attempts else 0.0

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
            "tracked_models": _collect_tracked_models(runs),
        },
        "trend": [_serialize_trend_point(run) for run in reversed(limited_runs)],
        "recent_runs": [_serialize_run(run) for run in limited_runs],
        "open_regressions": [_serialize_cluster(c) for c in open_clusters[:10]],
        "model_performance": [_serialize_model_row(row) for row in model_rows],
        "experiments": await _fetch_experiment_summaries(db, experiments[:10]),
    }
