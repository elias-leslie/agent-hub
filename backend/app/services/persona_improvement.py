"""Persona benchmark improvement metrics and heartbeat field-evidence digests."""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    AgentPerformanceLog,
    CostLog,
    Session,
    SessionEvent,
    SessionEventType,
)
from app.services.benchmark_aggregation import aggregate_attempts, attempt_is_infra
from app.services.memory.citation_parser import parse_summary_tags
from scripts.persona_benchmark_cases import get_case_by_id

PRODUCTIVE_ACTIONS = frozenset({"dispatch", "monitor", "reconcile"})
HEARTBEAT_FIELD_LOOKBACK_DAYS = 7
HEARTBEAT_FIELD_LIMIT = 8
HEARTBEAT_FIELD_PROMPT_LIMIT = 4
HEARTBEAT_FIELD_PROMPT_LOOKBACK_DAYS = 1
FIELD_REVIEW_RELIABILITY_FLOOR = 88.0
FIELD_REVIEW_TRUTH_FLOOR = 85.0
FIELD_REVIEW_PARTIAL_RATE_CEILING = 50.0
FIELD_REVIEW_PARTIAL_COUNT_FLOOR = 3
FIELD_REVIEW_REPEATED_ISSUE_THRESHOLD = 3

_HEARTBEAT_CRITICAL_ISSUES = frozenset(
    {
        "runtime_error",
        "post_run_residue",
        "cleanup_actionable",
        "stale_running_task",
        "completed_ready_for_closure",
        "completion_review_continue",
        "completion_review_escalate",
        "cli_usage_error",
        "dispatch_not_ready",
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
    "cli_usage_error": "CLI usage error left unrecovered",
    "dispatch_not_ready": "attempted dispatch on a non-ready task",
}
_HEARTBEAT_RELIABILITY_PENALTIES = {
    "runtime_error": 60,
    "post_run_residue": 35,
    "cleanup_actionable": 35,
    "stale_running_task": 35,
    "completed_ready_for_closure": 35,
    "completion_review_continue": 30,
    "completion_review_escalate": 35,
    "cli_usage_error": 25,
    "dispatch_not_ready": 25,
    "missing_prefix": 15,
    "missing_summary": 10,
    "missing_progress": 12,
}
_FIELD_REVIEW_REASON_LABELS = {
    "critical_heartbeat_failures": "recent critical heartbeat failures",
    "field_reliability_low": "field reliability below review floor",
    "field_truth_quality_low": "field truth quality below review floor",
    "field_partial_churn": "partial heartbeat rate above review ceiling",
    "field_repeated_issue": "repeated field issue needs a source fix",
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
    """Derive persona-focused quality and efficiency metrics for one benchmark run."""
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


def _session_event_text(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    return str(content)


def _is_cli_usage_error_result(text: str) -> bool:
    lowered = text.lower()
    return (
        "no such option:" in lowered
        or ("try 'st " in lowered and "--help' for help" in lowered)
        or lowered.startswith("usage: st ")
    )


def _heartbeat_issue_codes_from_events(
    events: list[tuple[SessionEventType, str]],
) -> list[str]:
    issue_codes: set[str] = set()
    unrecovered_cli_usage_error = False
    help_request_active = False

    for event_type, raw_text in events:
        text = _session_event_text(raw_text)
        lowered = text.lower()

        if event_type == SessionEventType.TOOL_USE:
            if unrecovered_cli_usage_error and "--help" in lowered:
                unrecovered_cli_usage_error = False
                help_request_active = True
            else:
                help_request_active = False
        elif event_type == SessionEventType.TOOL_RESULT:
            if help_request_active:
                help_request_active = False
                continue
            if _is_cli_usage_error_result(text):
                unrecovered_cli_usage_error = True
                continue
            if "not execution-ready for autocode" in lowered:
                issue_codes.add("dispatch_not_ready")

    if unrecovered_cli_usage_error:
        issue_codes.add("cli_usage_error")

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
    summary_tags = parse_summary_tags(text).tags
    if summary_tags:
        outcome = summary_tags[-1].outcome
        if outcome in {"partial", "failed"}:
            return outcome
    if "HEARTBEAT_ACTION" in text:
        return "action"
    if "HEARTBEAT_OK" in text:
        return "ok"
    if summary_tags and summary_tags[-1].outcome == "completed":
        return "completed"
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
        if result_status == "partial":
            effectiveness = min(effectiveness, 65.0)
        if result_status == "completed":
            effectiveness = min(effectiveness, 90.0)
        if result_status == "unknown":
            effectiveness -= 10.0
        if "missing_prefix" in issue_codes:
            effectiveness -= 8.0
        if "missing_summary" in issue_codes:
            effectiveness -= 6.0
        if "missing_progress" in issue_codes:
            effectiveness -= 8.0
        effectiveness = max(0.0, effectiveness)

    healthy = (
        session_status == "completed"
        and result_status in {"action", "ok"}
        and not _heartbeat_has_critical_issues(issue_codes)
    )
    return round(reliability, 1), round(effectiveness, 1), round(truth_quality, 1), healthy


def _heartbeat_exists_clause() -> Any:
    return (
        select(SessionEvent.session_id)
        .where(SessionEvent.session_id == Session.id)
        .correlate(Session)
        .exists()
    )


def _build_heartbeat_session_query(*, cutoff: datetime, limit: int | None) -> Select[Any]:
    query = (
        select(Session)
        .where(
            Session.agent_slug == "persona",
            Session.request_source == "heartbeat",
            Session.status.in_(("completed", "failed")),
            Session.created_at >= cutoff,
            _heartbeat_exists_clause(),
        )
        .order_by(Session.created_at.desc())
    )
    if limit is not None:
        query = query.limit(limit)
    return query


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
) -> tuple[
    dict[str, dict[str, int]],
    dict[str, str | None],
    dict[str, list[tuple[SessionEventType, str]]],
]:
    if not session_ids:
        return {}, {}, {}
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
    tool_event_rows = (
        await db.execute(
            select(
                SessionEvent.session_id,
                SessionEvent.event_type,
                SessionEvent.content,
            )
            .where(
                SessionEvent.session_id.in_(session_ids),
                SessionEvent.event_type.in_(
                    (
                        SessionEventType.TOOL_USE,
                        SessionEventType.TOOL_RESULT,
                    )
                ),
            )
            .order_by(
                SessionEvent.session_id.asc(),
                SessionEvent.turn.asc(),
                SessionEvent.sequence.asc(),
            )
        )
    ).all()
    tool_events: dict[str, list[tuple[SessionEventType, str]]] = defaultdict(list)
    for row in tool_event_rows:
        tool_events[str(row.session_id)].append(
            (
                row.event_type,
                _session_event_text(row.content),
            )
        )
    return metrics, final_content, tool_events


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
    limit: int | None,
) -> list[dict[str, Any]]:
    cutoff = datetime.now(UTC) - timedelta(days=days)
    sessions = (
        await db.execute(_build_heartbeat_session_query(cutoff=cutoff, limit=limit))
    ).scalars().all()
    if not sessions:
        return []

    session_ids = [session.id for session in sessions]
    cost_totals = await _fetch_heartbeat_cost_totals(db, session_ids)
    event_metrics, final_content, tool_events = await _fetch_heartbeat_event_metrics(db, session_ids)
    performance_logs = await _fetch_heartbeat_performance_logs(db, session_ids)

    items: list[dict[str, Any]] = []
    for session in sessions:
        cost = cost_totals.get(session.id, {})
        event = event_metrics.get(session.id, {})
        logs = performance_logs.get(session.id, [])
        issue_codes = sorted(
            set(_heartbeat_issue_codes_from_logs(logs, session.status))
            | set(_heartbeat_issue_codes_from_events(tool_events.get(str(session.id), [])))
        )
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
    total_heartbeats = len(sessions)
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
    result_counts = Counter(str(item.get("result_status") or "unknown") for item in sessions)
    healthy_count = len(healthy_sessions)
    action_count = int(result_counts.get("action", 0))
    ok_count = int(result_counts.get("ok", 0))
    partial_count = int(result_counts.get("partial", 0))
    completed_count = int(result_counts.get("completed", 0))
    failed_count = int(result_counts.get("failed", 0))
    unknown_count = int(result_counts.get("unknown", 0))
    issue_counts = Counter(
        issue_code
        for item in sessions
        for issue_code in list(item.get("issue_codes") or [])
    )
    top_issue_code, top_issue_count = issue_counts.most_common(1)[0] if issue_counts else (None, 0)
    return {
        "total_heartbeats": total_heartbeats,
        "latest_completed_at": latest["completed_at"] if latest else None,
        "reliability": _mean(reliability_values),
        "effectiveness": _mean(effectiveness_values),
        "truth_quality": _mean(truth_values),
        "tokens_per_healthy_heartbeat": _mean(token_values),
        "avg_tool_calls": _mean(tool_values),
        "avg_turns": _mean(turn_values),
        "healthy_heartbeats": healthy_count,
        "healthy_rate": _round_metric((healthy_count / total_heartbeats) * 100 if total_heartbeats else None),
        "risky_heartbeats": len(risky),
        "critical_heartbeats": len(critical),
        "action_heartbeats": action_count,
        "action_rate": _round_metric((action_count / total_heartbeats) * 100 if total_heartbeats else None),
        "ok_heartbeats": ok_count,
        "ok_rate": _round_metric((ok_count / total_heartbeats) * 100 if total_heartbeats else None),
        "partial_heartbeats": partial_count,
        "partial_rate": _round_metric((partial_count / total_heartbeats) * 100 if total_heartbeats else None),
        "completed_heartbeats": completed_count,
        "failed_heartbeats": failed_count,
        "unknown_heartbeats": unknown_count,
        "top_issue_code": top_issue_code,
        "top_issue_label": _HEARTBEAT_ISSUE_LABELS.get(top_issue_code, top_issue_code) if top_issue_code else None,
        "top_issue_count": int(top_issue_count),
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
    partial_rate = overview.get("partial_rate")
    partial_count = int(overview.get("partial_heartbeats") or 0)
    if (
        partial_rate is not None
        and float(partial_rate) >= FIELD_REVIEW_PARTIAL_RATE_CEILING
        and partial_count >= FIELD_REVIEW_PARTIAL_COUNT_FLOOR
    ):
        reason_codes.append("field_partial_churn")
    top_issue_count = int(overview.get("top_issue_count") or 0)
    if top_issue_count >= FIELD_REVIEW_REPEATED_ISSUE_THRESHOLD:
        reason_codes.append("field_repeated_issue")

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
    sessions = await _collect_heartbeat_field_sessions(db, days=days, limit=None)
    overview = _summarize_heartbeat_field_sessions(sessions)
    recent_sessions = sessions[:limit]
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
        for item in reversed(recent_sessions)
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
        for item in recent_sessions
        if item["issue_codes"]
    ][:6]
    snapshot = {
        "overview": overview,
        "trend": trend,
        "recent_heartbeats": recent_sessions,
        "risks": risks,
    }
    snapshot["review_gate"] = evaluate_persona_heartbeat_field_snapshot(snapshot)
    return snapshot


async def build_persona_heartbeat_field_digest(
    *,
    days: int = HEARTBEAT_FIELD_PROMPT_LOOKBACK_DAYS,
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
            f"- last {days * 24}h field lookback: {overview['total_heartbeats']} real heartbeats; "
            f"action {overview.get('action_heartbeats') or 0} ({overview.get('action_rate') or 0:.1f}%); "
            f"clean-ok {overview.get('ok_heartbeats') or 0} ({overview.get('ok_rate') or 0:.1f}%); "
            f"partial {overview.get('partial_heartbeats') or 0} ({overview.get('partial_rate') or 0:.1f}%); "
            f"healthy {overview.get('healthy_heartbeats') or 0} ({overview.get('healthy_rate') or 0:.1f}%); "
            f"avg reliability {overview['reliability'] or 0:.1f}%; "
            f"avg effectiveness {overview['effectiveness'] or 0:.1f}%; "
            f"critical issues {overview['critical_heartbeats']}."
        )
    ]
    if int(overview.get("top_issue_count") or 0) > 1 and overview.get("top_issue_label"):
        lines.append(
            f"- repeated field issue: {overview['top_issue_label']} x{overview['top_issue_count']} in the last {days * 24}h."
        )
    for item in recent[:limit]:
        lines.append(
            "- "
            f"{item['completed_at']} | status={item['result_status']} | "
            f"reliability={item['reliability']:.1f}% | issues={item['issue_summary']} | "
            f"summary={str(item['summary_oneliner'] or '(none)')[:120]}"
        )
    return "\n".join(lines)
