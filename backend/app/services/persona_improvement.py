"""Jenny improvement dashboard metrics and self-honing schedule helpers."""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    AgentBenchmarkExperiment,
    AgentBenchmarkRun,
    AgentPerformanceLog,
    CostLog,
    PersonaScheduledJob,
    Session,
    SessionEvent,
    SessionEventType,
)
from app.services._benchmark_dashboard import (
    query_open_regression_clusters,
)
from app.services.benchmark_aggregation import aggregate_attempts, attempt_is_infra
from app.services.persona_service import get_or_create_persona
from app.workflows.persona_scheduler import compute_next_run
from scripts.persona_benchmark_cases import get_case_by_id

JENNY_IMPROVEMENT_SUITE_ID = "persona-suite-jenny-improvement"
SELF_HONING_JOB_NAME = "Jenny improvement loop"
SELF_HONING_PAYLOAD_MESSAGE = "Scheduled Jenny improvement run."
DEFAULT_SELF_HONING_CADENCE_MINUTES = 15
MIN_SELF_HONING_CADENCE_MINUTES = 15
MAX_SELF_HONING_CADENCE_MINUTES = 7 * 24 * 60
PRODUCTIVE_ACTIONS = frozenset({"dispatch", "monitor", "reconcile"})
HEARTBEAT_FIELD_LOOKBACK_DAYS = 7
HEARTBEAT_FIELD_LIMIT = 8
HEARTBEAT_FIELD_PROMPT_LIMIT = 4
FIELD_REVIEW_RELIABILITY_FLOOR = 88.0
FIELD_REVIEW_TRUTH_FLOOR = 85.0

_HEARTBEAT_CRITICAL_ISSUES = frozenset(
    {
        "runtime_error",
        "post_run_residue",
        "cleanup_actionable",
        "stale_running_task",
        "completed_ready_for_closure",
        "completion_review_continue",
        "completion_review_escalate",
    }
)
_HEARTBEAT_ISSUE_LABELS = {
    "runtime_error": "runtime error",
    "missing_prefix": "missing prefix",
    "missing_summary": "missing summary tag",
    "missing_progress": "missing progress tags",
    "post_run_residue": "post-run residue",
    "cleanup_actionable": "cleanup still actionable",
    "stale_running_task": "stale running task missed",
    "completed_ready_for_closure": "closeout residue missed",
    "completion_review_continue": "completion review said continue",
    "completion_review_escalate": "completion review escalated",
}
_HEARTBEAT_RELIABILITY_PENALTIES = {
    "runtime_error": 60,
    "post_run_residue": 35,
    "cleanup_actionable": 35,
    "stale_running_task": 35,
    "completed_ready_for_closure": 35,
    "completion_review_continue": 30,
    "completion_review_escalate": 35,
    "missing_prefix": 15,
    "missing_summary": 10,
    "missing_progress": 12,
}
_FIELD_REVIEW_REASON_LABELS = {
    "critical_heartbeat_failures": "recent critical heartbeat failures",
    "field_reliability_low": "field reliability below review floor",
    "field_truth_quality_low": "field truth quality below review floor",
}


def _read_field(item: Any, field_name: str, default: Any = None) -> Any:
    if isinstance(item, dict):
        return item.get(field_name, default)
    return getattr(item, field_name, default)


def _round_metric(value: float | None, digits: int = 1) -> float | None:
    if value is None:
        return None
    return round(float(value), digits)


def _coerce_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _format_cadence_label(minutes: int | None) -> str | None:
    if minutes is None or minutes <= 0:
        return None
    if minutes % (24 * 60) == 0:
        days = minutes // (24 * 60)
        return f"{days}d" if days != 1 else "24h"
    if minutes % 60 == 0:
        hours = minutes // 60
        return f"{hours}h"
    return f"{minutes}m"


def _parse_cadence_minutes(job: PersonaScheduledJob | None) -> int | None:
    if job is None or job.schedule_type != "every":
        return None
    interval_ms = _coerce_int(job.schedule_value)
    if interval_ms <= 0:
        return None
    return max(1, interval_ms // 60000)


def _preview_summary_from_snapshot(config_snapshot: dict[str, Any]) -> dict[str, Any] | None:
    preview = config_snapshot.get("preview_summary")
    if isinstance(preview, dict):
        return preview
    return None


def _prompt_tokens_from_snapshot(config_snapshot: dict[str, Any]) -> tuple[int | None, dict[str, int]]:
    preview = _preview_summary_from_snapshot(config_snapshot)
    if not preview:
        return None, {}
    total = preview.get("total_estimated_tokens")
    by_source_kind = preview.get("by_source_kind")
    return (
        _coerce_int(total) if total is not None else None,
        dict(by_source_kind) if isinstance(by_source_kind, dict) else {},
    )


def build_persona_improvement_metadata(
    attempts: list[Any],
    *,
    config_snapshot: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Derive Jenny-focused quality and efficiency metrics for one benchmark run."""
    aggregate = aggregate_attempts(attempts)
    scored_attempts = [attempt for attempt in attempts if not attempt_is_infra(attempt)]
    passed_attempts = [
        attempt for attempt in scored_attempts if bool(_read_field(attempt, "passed", False))
    ]
    productive_attempts: list[Any] = []
    productive_passed = 0
    family_rollups: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"attempts": 0, "passed": 0, "productive_attempts": 0}
    )
    failure_counts: dict[str, int] = defaultdict(int)

    for attempt in scored_attempts:
        case_id = str(_read_field(attempt, "case_id", "") or "")
        case_family = "unknown"
        expected_action = None
        try:
            case = get_case_by_id(case_id)
        except KeyError:
            case = None
        if case is not None:
            case_family = case.family
            expected_action = case.expected.get("primary_action")

        family_rollups[case_family]["attempts"] += 1
        if bool(_read_field(attempt, "passed", False)):
            family_rollups[case_family]["passed"] += 1
        if expected_action in PRODUCTIVE_ACTIONS:
            productive_attempts.append(attempt)
            family_rollups[case_family]["productive_attempts"] += 1
            if bool(_read_field(attempt, "passed", False)):
                productive_passed += 1
        if not bool(_read_field(attempt, "passed", False)):
            failure_detail = str(_read_field(attempt, "failure_detail", "") or "failed")
            failure_counts[failure_detail] += 1

    total_tokens = sum(_coerce_int(_read_field(attempt, "total_tokens", 0)) for attempt in scored_attempts)
    prompt_tokens, prompt_sources = _prompt_tokens_from_snapshot(dict(config_snapshot or {}))
    reliability = aggregate.pass_rate
    effectiveness = (
        round((productive_passed / len(productive_attempts)) * 100, 1)
        if productive_attempts
        else aggregate.pass_rate
    )
    tokens_per_passed_attempt = (
        round(total_tokens / len(passed_attempts), 1) if passed_attempts else None
    )
    top_failure_detail = None
    if failure_counts:
        top_failure_detail = sorted(
            failure_counts.items(),
            key=lambda item: (-item[1], item[0]),
        )[0][0]

    family_breakdown = [
        {
            "family": family,
            "attempts": int(bucket["attempts"]),
            "pass_rate": round((bucket["passed"] / bucket["attempts"]) * 100, 1)
            if bucket["attempts"]
            else 0.0,
            "productive_attempts": int(bucket["productive_attempts"]),
        }
        for family, bucket in sorted(family_rollups.items())
    ]

    return {
        "reliability": _round_metric(reliability),
        "effectiveness": _round_metric(effectiveness),
        "avg_total_tokens": _round_metric(aggregate.avg_total_tokens),
        "tokens_per_passed_attempt": _round_metric(tokens_per_passed_attempt),
        "avg_tool_calls": _round_metric(aggregate.avg_tool_calls, 2),
        "avg_turns": _round_metric(aggregate.avg_turns, 2),
        "prompt_tokens": prompt_tokens,
        "prompt_sources": prompt_sources,
        "scored_attempts": len(scored_attempts),
        "passed_attempts": len(passed_attempts),
        "productive_attempts": len(productive_attempts),
        "failure_count": len(scored_attempts) - len(passed_attempts),
        "top_failure_detail": top_failure_detail,
        "family_breakdown": family_breakdown,
    }


def _metadata_for_run(run: AgentBenchmarkRun) -> dict[str, Any]:
    raw = dict(run.run_metadata or {})
    metrics = raw.get("persona_improvement")
    if isinstance(metrics, dict):
        return metrics
    prompt_tokens, prompt_sources = _prompt_tokens_from_snapshot(dict(run.config_snapshot or {}))
    return {
        "reliability": _round_metric(run.pass_rate),
        "effectiveness": _round_metric(run.pass_rate),
        "avg_total_tokens": raw.get("efficiency", {}).get("avg_total_tokens")
        if isinstance(raw.get("efficiency"), dict)
        else None,
        "tokens_per_passed_attempt": None,
        "avg_tool_calls": raw.get("efficiency", {}).get("avg_tool_calls")
        if isinstance(raw.get("efficiency"), dict)
        else None,
        "avg_turns": raw.get("efficiency", {}).get("avg_turns")
        if isinstance(raw.get("efficiency"), dict)
        else None,
        "prompt_tokens": prompt_tokens,
        "prompt_sources": prompt_sources,
        "failure_count": max(
            0,
            int(run.attempt_count or 0)
            - int(run.infra_failure_count or 0)
            - int(run.passed_attempt_count or 0),
        ),
        "top_failure_detail": None,
        "family_breakdown": [],
    }


async def get_persona_self_honing_job(db: AsyncSession) -> PersonaScheduledJob | None:
    """Return the most relevant Jenny self-honing job, if any."""
    persona = await get_or_create_persona(db)
    jobs = (
        await db.execute(
            select(PersonaScheduledJob)
            .where(
                PersonaScheduledJob.persona_id == persona.id,
                PersonaScheduledJob.payload_type == "self_honing",
            )
            .order_by(
                PersonaScheduledJob.enabled.desc(),
                PersonaScheduledJob.created_at.desc(),
            )
        )
    ).scalars().all()
    return jobs[0] if jobs else None


def serialize_persona_self_honing_schedule(
    job: PersonaScheduledJob | None,
    *,
    fallback_cadence_minutes: int | None = None,
) -> dict[str, Any]:
    """Serialize the Jenny self-honing schedule for the UI/API."""
    cadence_minutes = _parse_cadence_minutes(job) or fallback_cadence_minutes
    return {
        "job_id": job.id if job else None,
        "enabled": bool(job.enabled) if job else False,
        "schedule_type": job.schedule_type if job else "every",
        "schedule_value": job.schedule_value if job else str(
            (cadence_minutes or DEFAULT_SELF_HONING_CADENCE_MINUTES) * 60000
        ),
        "schedule_timezone": job.schedule_timezone if job else "UTC",
        "cadence_minutes": cadence_minutes or DEFAULT_SELF_HONING_CADENCE_MINUTES,
        "cadence_label": _format_cadence_label(
            cadence_minutes or DEFAULT_SELF_HONING_CADENCE_MINUTES
        ),
        "last_run_at": job.last_run_at.isoformat() if job and job.last_run_at else None,
        "next_run_at": job.next_run_at.isoformat() if job and job.next_run_at else None,
        "run_count": int(job.run_count or 0) if job else 0,
    }


async def update_persona_self_honing_schedule(
    db: AsyncSession,
    *,
    enabled: bool,
    cadence_minutes: int | None,
) -> dict[str, Any]:
    """Create or update the single scheduled Jenny improvement loop."""
    minutes = cadence_minutes or DEFAULT_SELF_HONING_CADENCE_MINUTES
    if minutes < MIN_SELF_HONING_CADENCE_MINUTES or minutes > MAX_SELF_HONING_CADENCE_MINUTES:
        raise ValueError(
            "cadence_minutes must be between "
            f"{MIN_SELF_HONING_CADENCE_MINUTES} and {MAX_SELF_HONING_CADENCE_MINUTES}"
        )

    persona = await get_or_create_persona(db)
    jobs = (
        await db.execute(
            select(PersonaScheduledJob)
            .where(
                PersonaScheduledJob.persona_id == persona.id,
                PersonaScheduledJob.payload_type == "self_honing",
            )
            .order_by(
                PersonaScheduledJob.enabled.desc(),
                PersonaScheduledJob.created_at.desc(),
            )
        )
    ).scalars().all()
    primary = jobs[0] if jobs else None
    interval_ms = str(minutes * 60000)

    if primary is None and enabled:
        primary = PersonaScheduledJob(
            persona_id=persona.id,
            name=SELF_HONING_JOB_NAME,
            schedule_type="every",
            schedule_value=interval_ms,
            schedule_timezone="UTC",
            payload_type="self_honing",
            payload_message=SELF_HONING_PAYLOAD_MESSAGE,
            delivery="none",
            enabled=True,
            next_run_at=compute_next_run("every", interval_ms, "UTC"),
            max_runs=None,
        )
        db.add(primary)
    elif primary is not None:
        primary.name = SELF_HONING_JOB_NAME
        primary.schedule_type = "every"
        primary.schedule_value = interval_ms
        primary.schedule_timezone = "UTC"
        primary.payload_type = "self_honing"
        primary.payload_message = SELF_HONING_PAYLOAD_MESSAGE
        primary.delivery = "none"
        primary.max_runs = None
        primary.enabled = enabled
        primary.next_run_at = (
            compute_next_run("every", interval_ms, "UTC", last_run_at=primary.last_run_at)
            if enabled
            else None
        )

    for duplicate in jobs[1:]:
        duplicate.enabled = False
        duplicate.next_run_at = None

    await db.commit()
    if primary is not None:
        await db.refresh(primary)
    return serialize_persona_self_honing_schedule(primary, fallback_cadence_minutes=minutes)


def _mean(values: list[float | None]) -> float | None:
    nums = [float(value) for value in values if value is not None]
    if not nums:
        return None
    return round(sum(nums) / len(nums), 1)


def _heartbeat_has_critical_issues(issue_codes: list[str]) -> bool:
    return any(code in _HEARTBEAT_CRITICAL_ISSUES for code in issue_codes)


def _heartbeat_issue_codes_from_logs(logs: list[AgentPerformanceLog], status: str) -> list[str]:
    issue_codes: set[str] = set()
    if status == "failed":
        issue_codes.add("runtime_error")
    for log in logs:
        content = str(log.content or "").lower()
        if "runtime error:" in content or str(log.outcome or "").lower() == "failure":
            issue_codes.add("runtime_error")
        if "missing heartbeat_ok/heartbeat_action prefix" in content:
            issue_codes.add("missing_prefix")
        if "missing inline [[s:...]] summary tag" in content:
            issue_codes.add("missing_summary")
        if "missing meaningful [[p:...]] progress tags" in content:
            issue_codes.add("missing_progress")
        if "post-run residue detected:" in content:
            if "cleanup_actionable" in content:
                issue_codes.add("cleanup_actionable")
            elif "stale_running_task" in content:
                issue_codes.add("stale_running_task")
            elif "completed_ready_for_closure" in content:
                issue_codes.add("completed_ready_for_closure")
            else:
                issue_codes.add("post_run_residue")
        if "completion review requested continue" in content:
            issue_codes.add("completion_review_continue")
        if "completion review requested escalate" in content:
            issue_codes.add("completion_review_escalate")
    return sorted(issue_codes)


def _heartbeat_issue_summary(issue_codes: list[str]) -> str:
    if not issue_codes:
        return "clean"
    labels = [_HEARTBEAT_ISSUE_LABELS.get(code, code.replace("_", " ")) for code in issue_codes]
    return ", ".join(labels)


def _heartbeat_result_status(final_content: str | None, session_status: str) -> str:
    if session_status == "failed":
        return "failed"
    text = str(final_content or "")
    if "HEARTBEAT_ACTION" in text:
        return "action"
    if "HEARTBEAT_OK" in text:
        return "ok"
    return "unknown"


def _score_heartbeat_session(
    *,
    session_status: str,
    issue_codes: list[str],
    result_status: str,
) -> tuple[float, float, float, bool]:
    reliability = 100.0
    for code in issue_codes:
        reliability -= _HEARTBEAT_RELIABILITY_PENALTIES.get(code, 0)
    if session_status == "failed":
        reliability = min(reliability, 0.0)
    reliability = max(0.0, reliability)

    truth_quality = 100.0
    for code in issue_codes:
        if code in {"missing_prefix", "missing_summary", "missing_progress"}:
            truth_quality -= _HEARTBEAT_RELIABILITY_PENALTIES.get(code, 0)
        elif code in _HEARTBEAT_CRITICAL_ISSUES:
            truth_quality -= 12.0
    truth_quality = max(0.0, truth_quality)

    if session_status == "failed":
        effectiveness = 0.0
    else:
        effectiveness = 100.0
        if _heartbeat_has_critical_issues(issue_codes):
            effectiveness = min(effectiveness, 35.0)
        if result_status == "unknown":
            effectiveness -= 10.0
        if "missing_prefix" in issue_codes:
            effectiveness -= 8.0
        if "missing_summary" in issue_codes:
            effectiveness -= 6.0
        if "missing_progress" in issue_codes:
            effectiveness -= 8.0
        effectiveness = max(0.0, effectiveness)

    healthy = session_status == "completed" and not _heartbeat_has_critical_issues(issue_codes)
    return round(reliability, 1), round(effectiveness, 1), round(truth_quality, 1), healthy


def _heartbeat_exists_clause() -> Any:
    return (
        select(SessionEvent.session_id)
        .where(SessionEvent.session_id == Session.id)
        .correlate(Session)
        .exists()
    )


def _build_heartbeat_session_query(*, cutoff: datetime, limit: int) -> Select[Any]:
    return (
        select(Session)
        .where(
            Session.agent_slug == "persona",
            Session.request_source == "heartbeat",
            Session.status.in_(("completed", "failed")),
            Session.created_at >= cutoff,
            _heartbeat_exists_clause(),
        )
        .order_by(Session.created_at.desc())
        .limit(limit)
    )


async def _fetch_heartbeat_cost_totals(
    db: AsyncSession,
    session_ids: list[str],
) -> dict[str, dict[str, int]]:
    if not session_ids:
        return {}
    rows = (
        await db.execute(
            select(
                CostLog.session_id,
                func.coalesce(func.sum(CostLog.input_tokens), 0).label("input_tokens"),
                func.coalesce(func.sum(CostLog.output_tokens), 0).label("output_tokens"),
            )
            .where(CostLog.session_id.in_(session_ids))
            .group_by(CostLog.session_id)
        )
    ).all()
    return {
        row.session_id: {
            "input_tokens": int(row.input_tokens or 0),
            "output_tokens": int(row.output_tokens or 0),
            "total_tokens": int(row.input_tokens or 0) + int(row.output_tokens or 0),
        }
        for row in rows
    }


async def _fetch_heartbeat_event_metrics(
    db: AsyncSession,
    session_ids: list[str],
) -> tuple[dict[str, dict[str, int]], dict[str, str | None]]:
    if not session_ids:
        return {}, {}
    metric_rows = (
        await db.execute(
            select(
                SessionEvent.session_id,
                func.count(SessionEvent.id)
                .filter(SessionEvent.event_type == SessionEventType.TOOL_USE)
                .label("tool_calls"),
                func.max(SessionEvent.turn).label("turns"),
            )
            .where(SessionEvent.session_id.in_(session_ids))
            .group_by(SessionEvent.session_id)
        )
    ).all()
    metrics = {
        row.session_id: {
            "tool_calls": int(row.tool_calls or 0),
            "turns": int(row.turns or 0),
        }
        for row in metric_rows
    }

    row_num = func.row_number().over(
        partition_by=SessionEvent.session_id,
        order_by=[SessionEvent.turn.desc(), SessionEvent.sequence.desc()],
    ).label("rn")
    latest_assistant_subq = (
        select(
            SessionEvent.session_id.label("session_id"),
            SessionEvent.content.label("content"),
            row_num,
        )
        .where(
            SessionEvent.session_id.in_(session_ids),
            SessionEvent.event_type == SessionEventType.ASSISTANT_MESSAGE,
        )
        .subquery()
    )
    content_rows = (
        await db.execute(
            select(latest_assistant_subq.c.session_id, latest_assistant_subq.c.content).where(
                latest_assistant_subq.c.rn == 1
            )
        )
    ).all()
    final_content = {row.session_id: row.content for row in content_rows}
    return metrics, final_content


async def _fetch_heartbeat_performance_logs(
    db: AsyncSession,
    session_ids: list[str],
) -> dict[str, list[AgentPerformanceLog]]:
    if not session_ids:
        return {}
    rows = (
        await db.execute(
            select(AgentPerformanceLog)
            .where(
                AgentPerformanceLog.agent_slug == "persona",
                AgentPerformanceLog.task_type == "heartbeat",
                AgentPerformanceLog.session_id.in_(session_ids),
            )
            .order_by(AgentPerformanceLog.created_at.desc())
        )
    ).scalars().all()
    grouped: dict[str, list[AgentPerformanceLog]] = defaultdict(list)
    for row in rows:
        if row.session_id:
            grouped[str(row.session_id)].append(row)
    return grouped


async def _collect_heartbeat_field_sessions(
    db: AsyncSession,
    *,
    days: int,
    limit: int,
) -> list[dict[str, Any]]:
    cutoff = datetime.now(UTC) - timedelta(days=days)
    sessions = (
        await db.execute(_build_heartbeat_session_query(cutoff=cutoff, limit=limit))
    ).scalars().all()
    if not sessions:
        return []

    session_ids = [session.id for session in sessions]
    cost_totals = await _fetch_heartbeat_cost_totals(db, session_ids)
    event_metrics, final_content = await _fetch_heartbeat_event_metrics(db, session_ids)
    performance_logs = await _fetch_heartbeat_performance_logs(db, session_ids)

    items: list[dict[str, Any]] = []
    for session in sessions:
        cost = cost_totals.get(session.id, {})
        event = event_metrics.get(session.id, {})
        logs = performance_logs.get(session.id, [])
        issue_codes = _heartbeat_issue_codes_from_logs(logs, session.status)
        result_status = _heartbeat_result_status(final_content.get(session.id), session.status)
        reliability, effectiveness, truth_quality, healthy = _score_heartbeat_session(
            session_status=session.status,
            issue_codes=issue_codes,
            result_status=result_status,
        )
        items.append(
            {
                "session_id": session.id,
                "completed_at": session.updated_at.isoformat() if session.updated_at else session.created_at.isoformat(),
                "created_at": session.created_at.isoformat(),
                "status": session.status,
                "result_status": result_status,
                "summary_oneliner": session.summary_oneliner,
                "reliability": reliability,
                "effectiveness": effectiveness,
                "truth_quality": truth_quality,
                "total_tokens": int(cost.get("total_tokens", 0)),
                "input_tokens": int(cost.get("input_tokens", 0)),
                "output_tokens": int(cost.get("output_tokens", 0)),
                "tool_calls": int(event.get("tool_calls", 0)),
                "turns": int(event.get("turns", 0)),
                "issue_codes": issue_codes,
                "issue_summary": _heartbeat_issue_summary(issue_codes),
                "healthy": healthy,
            }
        )
    return items


def _summarize_heartbeat_field_sessions(
    sessions: list[dict[str, Any]],
) -> dict[str, Any]:
    reliability_values = [float(item["reliability"]) for item in sessions]
    effectiveness_values = [float(item["effectiveness"]) for item in sessions]
    truth_values = [float(item["truth_quality"]) for item in sessions]
    healthy_sessions = [item for item in sessions if item["healthy"]]
    token_values = [float(item["total_tokens"]) for item in healthy_sessions if item["total_tokens"] > 0]
    tool_values = [float(item["tool_calls"]) for item in sessions]
    turn_values = [float(item["turns"]) for item in sessions]
    risky = [item for item in sessions if item["issue_codes"]]
    critical = [item for item in risky if _heartbeat_has_critical_issues(item["issue_codes"])]
    latest = sessions[0] if sessions else None
    return {
        "total_heartbeats": len(sessions),
        "latest_completed_at": latest["completed_at"] if latest else None,
        "reliability": _mean(reliability_values),
        "effectiveness": _mean(effectiveness_values),
        "truth_quality": _mean(truth_values),
        "tokens_per_healthy_heartbeat": _mean(token_values),
        "avg_tool_calls": _mean(tool_values),
        "avg_turns": _mean(turn_values),
        "risky_heartbeats": len(risky),
        "critical_heartbeats": len(critical),
    }


def evaluate_persona_heartbeat_field_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    overview = snapshot.get("overview") if isinstance(snapshot, dict) else None
    recent = snapshot.get("recent_heartbeats") if isinstance(snapshot, dict) else None
    if not isinstance(overview, dict) or not isinstance(recent, list) or not recent:
        return {
            "needs_review": False,
            "reason_codes": [],
            "summary": "no_recent_field_heartbeats",
        }

    reason_codes: list[str] = []
    if int(overview.get("critical_heartbeats") or 0) > 0:
        reason_codes.append("critical_heartbeat_failures")
    reliability = overview.get("reliability")
    if reliability is not None and float(reliability) < FIELD_REVIEW_RELIABILITY_FLOOR:
        reason_codes.append("field_reliability_low")
    truth_quality = overview.get("truth_quality")
    if truth_quality is not None and float(truth_quality) < FIELD_REVIEW_TRUTH_FLOOR:
        reason_codes.append("field_truth_quality_low")

    labels = [_FIELD_REVIEW_REASON_LABELS.get(code, code) for code in reason_codes]
    return {
        "needs_review": bool(reason_codes),
        "reason_codes": reason_codes,
        "summary": ", ".join(labels) if labels else "field_ok",
    }


async def get_persona_heartbeat_field_snapshot(
    db: AsyncSession,
    *,
    days: int = HEARTBEAT_FIELD_LOOKBACK_DAYS,
    limit: int = HEARTBEAT_FIELD_LIMIT,
) -> dict[str, Any]:
    sessions = await _collect_heartbeat_field_sessions(db, days=days, limit=limit)
    overview = _summarize_heartbeat_field_sessions(sessions)
    trend = [
        {
            "session_id": item["session_id"],
            "completed_at": item["completed_at"],
            "reliability": item["reliability"],
            "effectiveness": item["effectiveness"],
            "truth_quality": item["truth_quality"],
            "total_tokens": item["total_tokens"],
            "tool_calls": item["tool_calls"],
            "turns": item["turns"],
            "result_status": item["result_status"],
        }
        for item in reversed(sessions)
    ]
    risks = [
        {
            "session_id": item["session_id"],
            "completed_at": item["completed_at"],
            "reliability": item["reliability"],
            "issue_summary": item["issue_summary"],
            "summary_oneliner": item["summary_oneliner"],
            "critical": _heartbeat_has_critical_issues(item["issue_codes"]),
        }
        for item in sessions
        if item["issue_codes"]
    ][:6]
    snapshot = {
        "overview": overview,
        "trend": trend,
        "recent_heartbeats": sessions,
        "risks": risks,
    }
    snapshot["review_gate"] = evaluate_persona_heartbeat_field_snapshot(snapshot)
    return snapshot


async def build_persona_heartbeat_field_digest(
    *,
    days: int = HEARTBEAT_FIELD_LOOKBACK_DAYS,
    limit: int = HEARTBEAT_FIELD_PROMPT_LIMIT,
) -> str:
    from app.db import async_session

    async with async_session() as db:
        snapshot = await get_persona_heartbeat_field_snapshot(db, days=days, limit=limit)
    overview = snapshot["overview"]
    recent = snapshot["recent_heartbeats"]
    if not recent:
        return "- none"
    lines = [
        (
            f"- {overview['total_heartbeats']} recent real heartbeats; "
            f"avg reliability {overview['reliability'] or 0:.1f}%; "
            f"avg effectiveness {overview['effectiveness'] or 0:.1f}%; "
            f"critical issues {overview['critical_heartbeats']}."
        )
    ]
    for item in recent[:limit]:
        lines.append(
            "- "
            f"{item['completed_at']} | status={item['result_status']} | "
            f"reliability={item['reliability']:.1f}% | issues={item['issue_summary']} | "
            f"summary={str(item['summary_oneliner'] or '(none)')[:120]}"
        )
    return "\n".join(lines)


def _format_trend_point(run: AgentBenchmarkRun) -> dict[str, Any]:
    metrics = _metadata_for_run(run)
    return {
        "run_id": run.id,
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
        "run_kind": run.run_kind,
        "suite_id": run.suite_id,
        "reliability": metrics.get("reliability"),
        "effectiveness": metrics.get("effectiveness"),
        "avg_total_tokens": metrics.get("avg_total_tokens"),
        "tokens_per_passed_attempt": metrics.get("tokens_per_passed_attempt"),
        "avg_tool_calls": metrics.get("avg_tool_calls"),
        "avg_turns": metrics.get("avg_turns"),
        "prompt_tokens": metrics.get("prompt_tokens"),
    }


def _format_recent_run(
    run: AgentBenchmarkRun,
    experiment: AgentBenchmarkExperiment | None = None,
) -> dict[str, Any]:
    metrics = _metadata_for_run(run)
    evidence = dict(experiment.evidence or {}) if experiment is not None else {}
    return {
        "run_id": run.id,
        "benchmark_id": run.benchmark_id,
        "suite_id": run.suite_id,
        "run_kind": run.run_kind,
        "started_at": run.started_at.isoformat(),
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
        "models": list(run.models or []),
        "case_ids": list(run.case_ids or []),
        "attempt_count": int(run.attempt_count or 0),
        "passed_attempt_count": int(run.passed_attempt_count or 0),
        "infra_failure_count": int(run.infra_failure_count or 0),
        "reliability": metrics.get("reliability"),
        "effectiveness": metrics.get("effectiveness"),
        "avg_total_tokens": metrics.get("avg_total_tokens"),
        "tokens_per_passed_attempt": metrics.get("tokens_per_passed_attempt"),
        "avg_tool_calls": metrics.get("avg_tool_calls"),
        "avg_turns": metrics.get("avg_turns"),
        "prompt_tokens": metrics.get("prompt_tokens"),
        "failure_count": metrics.get("failure_count"),
        "top_failure_detail": metrics.get("top_failure_detail"),
        "family_breakdown": metrics.get("family_breakdown") or [],
        "experiment_decision": experiment.decision if experiment is not None else None,
        "experiment_decision_reason": experiment.decision_reason if experiment is not None else None,
        "decision_source": evidence.get("final_decision_source") if evidence else None,
    }


def _select_current_lab_run(
    runs: list[AgentBenchmarkRun],
    experiments_by_id: dict[str, AgentBenchmarkExperiment],
) -> AgentBenchmarkRun | None:
    for run in runs:
        experiment = experiments_by_id.get(run.experiment_id) if run.experiment_id else None
        decision = experiment.decision if experiment is not None else None

        if run.run_kind == "honing_iteration":
            return run

        if run.run_kind == "honing_candidate":
            if decision == "promote":
                return run
            if decision in {"hold", "rollback"} and run.experiment_id:
                baseline = next(
                    (
                        candidate
                        for candidate in runs
                        if candidate.experiment_id == run.experiment_id
                        and candidate.run_kind == "honing_baseline"
                    ),
                    None,
                )
                if baseline is not None:
                    return baseline
                continue

        if run.run_kind == "honing_baseline":
            return run

    return runs[0] if runs else None


async def get_persona_improvement_dashboard(
    db: AsyncSession,
    *,
    days: int = 30,
    limit: int = 8,
) -> dict[str, Any]:
    """Return the focused Jenny improvement dashboard payload."""
    generated_at = datetime.now(UTC)
    cutoff = generated_at - timedelta(days=days)
    runs = (
        await db.execute(
            select(AgentBenchmarkRun)
            .where(
                AgentBenchmarkRun.agent_slug == "persona",
                AgentBenchmarkRun.suite_id == JENNY_IMPROVEMENT_SUITE_ID,
                AgentBenchmarkRun.completed_at.is_not(None),
                AgentBenchmarkRun.completed_at >= cutoff,
                AgentBenchmarkRun.attempt_count > AgentBenchmarkRun.infra_failure_count,
            )
            .order_by(AgentBenchmarkRun.completed_at.desc())
        )
    ).scalars().all()
    job = await get_persona_self_honing_job(db)
    schedule = serialize_persona_self_honing_schedule(job)
    open_clusters = await query_open_regression_clusters(
        db,
        agent_slug="persona",
        cutoff=cutoff,
        suite_id=JENNY_IMPROVEMENT_SUITE_ID,
        limit=6,
    )
    experiment_ids = {
        run.experiment_id
        for run in runs
        if getattr(run, "experiment_id", None)
    }
    experiments_by_id: dict[str, AgentBenchmarkExperiment] = {}
    if experiment_ids:
        experiments = (
            await db.execute(
                select(AgentBenchmarkExperiment).where(AgentBenchmarkExperiment.id.in_(experiment_ids))
            )
        ).scalars().all()
        experiments_by_id = {experiment.id: experiment for experiment in experiments}
    field_snapshot = await get_persona_heartbeat_field_snapshot(
        db,
        days=min(days, HEARTBEAT_FIELD_LOOKBACK_DAYS),
        limit=max(limit, HEARTBEAT_FIELD_LIMIT),
    )

    recent_runs = [
        _format_recent_run(run, experiments_by_id.get(run.experiment_id))
        for run in list(runs)[:limit]
    ]
    trend_source = list(reversed(list(runs)[: max(limit * 2, 12)]))
    trend = [_format_trend_point(run) for run in trend_source]
    reliability_values = [run_data["reliability"] for run_data in recent_runs]
    effectiveness_values = [run_data["effectiveness"] for run_data in recent_runs]
    token_values = [run_data["tokens_per_passed_attempt"] for run_data in recent_runs]
    prompt_values = [run_data["prompt_tokens"] for run_data in recent_runs]

    latest_run = runs[0] if runs else None
    latest_lab_run = _select_current_lab_run(runs, experiments_by_id)

    return {
        "generated_at": generated_at.isoformat(),
        "suite_id": JENNY_IMPROVEMENT_SUITE_ID,
        "days": days,
        "schedule": schedule,
        "overview": {
            "total_runs": len(runs),
            "latest_completed_at": (
                latest_run.completed_at.isoformat()
                if latest_run is not None and latest_run.completed_at is not None
                else None
            ),
            "reliability": _mean(reliability_values),
            "effectiveness": _mean(effectiveness_values),
            "tokens_per_passed_attempt": _mean(token_values),
            "prompt_tokens": _mean(prompt_values),
            "open_regressions": len(open_clusters),
        },
        "latest_lab_run": (
            _format_recent_run(latest_lab_run, experiments_by_id.get(latest_lab_run.experiment_id))
            if latest_lab_run is not None
            else None
        ),
        "field_overview": field_snapshot["overview"],
        "trend": trend,
        "field_trend": field_snapshot["trend"],
        "recent_runs": recent_runs,
        "recent_heartbeats": field_snapshot["recent_heartbeats"][:limit],
        "open_regressions": [
            {
                "case_id": cluster.case_id,
                "failure_detail": cluster.failure_detail,
                "occurrence_count": int(cluster.occurrence_count or 0),
                "last_seen_at": cluster.last_seen_at.isoformat() if cluster.last_seen_at else None,
                "latest_avg_score": _round_metric(cluster.latest_avg_score),
            }
            for cluster in open_clusters
        ],
        "field_risks": field_snapshot["risks"],
    }
