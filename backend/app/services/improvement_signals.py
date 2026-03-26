"""Combined evidence digest for autonomous agent improvement decisions."""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select

from app.db import async_session
from app.models import Session, SessionEvent
from app.models.agent_performance_log import AgentPerformanceLog
from app.models.session import SessionEventType
from app.services.agent_benchmark_service import get_benchmark_experiment_summary_by_key
from app.services.benchmark_failure_classification import (
    categorize_benchmark_failure_detail,
)
from app.services.memory._analytics_utilization import get_memory_utilization_summary
from app.services.memory.episode_operations import batch_get_episodes
from app.services.memory.governance import collect_memory_governance_snapshot

from ._benchmark_dashboard import query_open_regression_clusters, query_signal_experiments
from ._improvement_digest_formatter import (
    _build_benchmark_section,
    _build_memory_governance_section,
    _build_memory_section,
    _build_performance_section,
    _build_reference_yield_section,
)


def _select_agent_order(
    counts_by_agent: dict[str, dict[str, int]],
    *,
    primary_agent_slug: str,
    include_team: bool,
    max_agents: int,
) -> list[str]:
    if not counts_by_agent:
        return []
    if not include_team:
        return [primary_agent_slug] if primary_agent_slug in counts_by_agent else []

    ranked = sorted(
        counts_by_agent,
        key=lambda agent_slug: (
            agent_slug != primary_agent_slug,
            -counts_by_agent[agent_slug].get("friction", 0),
            -sum(counts_by_agent[agent_slug].values()),
            agent_slug,
        ),
    )
    return ranked[:max_agents]


def _canonicalize_agent_slug(agent_slug: str, *, primary_agent_slug: str) -> str:
    normalized = agent_slug.strip().lower()
    if primary_agent_slug == "persona" and normalized == "jenny":
        return primary_agent_slug
    return normalized


def _accumulate_performance_logs(
    logs: list[Any],
    *,
    primary_agent_slug: str,
) -> tuple[dict, dict, dict]:
    counts_by_agent: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    system_counts: dict[str, int] = defaultdict(int)
    repeated_issues: dict[tuple[str, str], dict[str, Any]] = {}
    for log in logs:
        agent_slug = _canonicalize_agent_slug(
            str(log.agent_slug or "unknown"),
            primary_agent_slug=primary_agent_slug,
        )
        feedback_type = str(log.feedback_type or "unknown")
        counts_by_agent[agent_slug][feedback_type] += 1
        if str(getattr(log, "logged_by", "")) == "system":
            system_counts[agent_slug] += 1
        if feedback_type != "friction":
            continue
        content = str(log.content or "").strip()
        if not content:
            continue
        key = (agent_slug, content)
        current = repeated_issues.get(key)
        created_at = getattr(log, "created_at", None)
        if current is None:
            repeated_issues[key] = {"count": 1, "latest": created_at}
            continue
        current["count"] += 1
        if created_at and (current["latest"] is None or created_at > current["latest"]):
            current["latest"] = created_at
    return counts_by_agent, system_counts, repeated_issues


def _top_repeated_issues(
    raw_issues: dict[tuple[str, str], dict[str, Any]],
    *,
    ordered_agents: list[str],
    primary_agent_slug: str,
    limit: int,
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for (agent_slug, content), info in sorted(
        raw_issues.items(),
        key=lambda item: (
            item[0][0] != primary_agent_slug,
            -int(item[1]["count"]),
            -int(item[1]["latest"].timestamp()) if item[1]["latest"] else 0,
        ),
    ):
        if agent_slug not in ordered_agents:
            continue
        items.append({
            "agent_slug": agent_slug,
            "feedback_type": "friction",
            "content": content,
            "count": int(info["count"]),
            "latest_at": info["latest"].isoformat() if info["latest"] else None,
        })
        if len(items) >= limit:
            break
    return items


def _build_performance_snapshot(
    performance_logs: list[Any],
    *,
    primary_agent_slug: str,
    include_team: bool,
    max_agents: int,
) -> dict[str, Any]:
    counts_by_agent, system_counts, repeated_issues_raw = _accumulate_performance_logs(
        performance_logs, primary_agent_slug=primary_agent_slug,
    )
    ordered_agents = _select_agent_order(
        counts_by_agent,
        primary_agent_slug=primary_agent_slug,
        include_team=include_team,
        max_agents=max_agents,
    )
    repeated_issue_items = _top_repeated_issues(
        repeated_issues_raw,
        ordered_agents=ordered_agents,
        primary_agent_slug=primary_agent_slug,
        limit=max(1, max_agents * 2),
    )
    return {
        "agent_signal_volume": [
            {
                "agent_slug": agent_slug,
                "friction": counts_by_agent[agent_slug].get("friction", 0),
                "improvement": counts_by_agent[agent_slug].get("improvement", 0),
                "idea": counts_by_agent[agent_slug].get("idea", 0),
                "praise": counts_by_agent[agent_slug].get("praise", 0),
                "system": system_counts.get(agent_slug, 0),
            }
            for agent_slug in ordered_agents
        ],
        "repeated_issues": repeated_issue_items,
    }


def _build_benchmark_snapshot(
    experiment_summaries: list[dict[str, Any]],
    open_clusters: list[Any],
) -> dict[str, Any]:
    return {
        "recent_benchmark_experiments": experiment_summaries,
        "open_regression_clusters": [
            {
                "case_id": str(cluster.case_id),
                "occurrence_count": int(cluster.occurrence_count or 0),
                "failure_detail": str(cluster.failure_detail or ""),
                "failure_kind": "model",
                "failure_category": cat,
                "last_seen_at": cluster.last_seen_at.isoformat() if cluster.last_seen_at else None,
            }
            for cluster in open_clusters
            if (cat := categorize_benchmark_failure_detail(str(cluster.failure_detail or ""))) != "infra"
        ],
    }


def _build_memory_snapshot(memory_utilization: Any) -> dict[str, Any]:
    return {
        "injection_sessions": int(memory_utilization.injection_sessions),
        "citation_sessions": int(memory_utilization.citation_sessions),
        "lookup_after_injection_sessions": int(memory_utilization.lookup_after_injection_sessions),
        "citation_session_rate": float(memory_utilization.citation_session_rate),
        "assistant_citation_rate": float(memory_utilization.assistant_citation_rate),
        "selected_reference_citation_rate": float(memory_utilization.selected_reference_citation_rate),
        "memory_search_calls": int(memory_utilization.memory_search_calls),
        "memory_get_calls": int(memory_utilization.memory_get_calls),
        "memory_debug_coverage_rate": float(memory_utilization.memory_debug_coverage_rate),
    }


async def _collect_reference_yield_snapshot(
    memory_events: list[tuple[str, Any]],
    *,
    max_reference_items: int,
) -> list[dict[str, Any]]:
    selected_counts: dict[str, int] = defaultdict(int)
    cited_counts: dict[str, int] = defaultdict(int)

    for event_type, tool_input in memory_events:
        payload = tool_input if isinstance(tool_input, dict) else {}
        if event_type == SessionEventType.MEMORY_INJECT:
            for uuid in payload.get("reference_selected_uuids") or []:
                selected_counts[str(uuid)] += 1
            continue
        if event_type == SessionEventType.MEMORY_CITE:
            for uuid in payload.get("uuids") or []:
                cited_counts[str(uuid)] += 1

    if not selected_counts:
        return []

    episode_details = await batch_get_episodes(None, list(selected_counts))
    ranked = sorted(
        selected_counts,
        key=lambda uuid: (
            selected_counts[uuid] < 2,
            cited_counts.get(uuid, 0) / selected_counts[uuid],
            -selected_counts[uuid],
            uuid,
        ),
    )

    low_yield_references: list[dict[str, Any]] = []
    for uuid in ranked:
        selected = selected_counts[uuid]
        if selected < 2:
            continue
        detail = episode_details.get(uuid) or {}
        rate = cited_counts.get(uuid, 0) / selected
        label = str(detail.get("name") or detail.get("content") or uuid[:8]).strip().splitlines()[0]
        low_yield_references.append({
            "uuid": uuid, "label": label, "selected": selected,
            "cited": cited_counts.get(uuid, 0), "citation_rate": rate,
            "tags": list(detail.get("tags") or []),
        })
        if len(low_yield_references) >= max_reference_items:
            break
    return low_yield_references


async def _collect_experiment_summaries(
    db: Any,
    experiments: list[Any],
) -> list[dict[str, Any]]:
    summaries: list[dict[str, Any]] = []
    for experiment in experiments:
        summary = await get_benchmark_experiment_summary_by_key(db, experiment.experiment_key)
        if summary is None:
            continue
        summaries.append({
            "suite_id": str(experiment.suite_id),
            "decision": str(summary.get("decision") or "hold"),
            "decision_reason": summary.get("decision_reason"),
            "score_delta": float((summary.get("score_delta") or {}).get("mean_delta") or 0.0),
            "pass_rate_delta": float(
                (summary.get("pass_rate_delta") or {}).get("mean_delta") or 0.0
            ),
        })
    return summaries


async def _fetch_db_data(
    db: Any,
    *,
    cutoff: datetime,
    primary_agent_slug: str,
    project_id: str | None,
    include_team: bool,
    max_experiments: int,
    max_clusters: int,
) -> tuple[list, list, list, list, Any]:
    performance_stmt = select(AgentPerformanceLog).where(
        AgentPerformanceLog.created_at >= cutoff,
    )
    if project_id:
        performance_stmt = performance_stmt.where(AgentPerformanceLog.project_id == project_id)
    if not include_team:
        performance_stmt = performance_stmt.where(
            AgentPerformanceLog.agent_slug == primary_agent_slug
        )
    performance_stmt = performance_stmt.order_by(AgentPerformanceLog.created_at.desc())
    performance_logs = list((await db.execute(performance_stmt)).scalars().all())
    experiments = await query_signal_experiments(
        db, agent_slug=primary_agent_slug, cutoff=cutoff, project_id=project_id, limit=max_experiments,
    )
    open_clusters = await query_open_regression_clusters(
        db, agent_slug=primary_agent_slug, cutoff=cutoff, project_id=project_id, limit=max_clusters,
    )
    memory_event_stmt = select(SessionEvent.event_type, SessionEvent.tool_input).where(
        SessionEvent.created_at >= cutoff,
        SessionEvent.event_type.in_([
            SessionEventType.MEMORY_INJECT,
            SessionEventType.MEMORY_CITE,
        ]),
    )
    if project_id:
        memory_event_stmt = memory_event_stmt.join(
            Session, Session.id == SessionEvent.session_id,
        ).where(Session.project_id == project_id)
    memory_events = list((await db.execute(memory_event_stmt)).all())
    experiment_summaries = await _collect_experiment_summaries(db, experiments)
    memory_governance = await collect_memory_governance_snapshot(db)
    return performance_logs, open_clusters, memory_events, experiment_summaries, memory_governance


async def collect_improvement_signal_snapshot(
    *,
    project_id: str | None,
    primary_agent_slug: str = "persona",
    days_back: int = 7,
    include_team: bool = True,
    max_agents: int = 4,
    max_experiments: int = 3,
    max_clusters: int = 5,
    max_reference_items: int = 6,
) -> dict[str, Any]:
    """Return structured evidence for Jenny's self-improvement loops."""
    cutoff = datetime.now(UTC) - timedelta(days=days_back)
    async with async_session() as db:
        performance_logs, open_clusters, memory_events, experiment_summaries, memory_governance = (
            await _fetch_db_data(
                db,
                cutoff=cutoff,
                primary_agent_slug=primary_agent_slug,
                project_id=project_id,
                include_team=include_team,
                max_experiments=max_experiments,
                max_clusters=max_clusters,
            )
        )
    memory_utilization = await get_memory_utilization_summary(
        timedelta(days=days_back),
        project_id_filter=project_id,
    )
    performance_snapshot = _build_performance_snapshot(
        performance_logs,
        primary_agent_slug=primary_agent_slug,
        include_team=include_team,
        max_agents=max_agents,
    )
    low_yield_references = await _collect_reference_yield_snapshot(
        memory_events,
        max_reference_items=max_reference_items,
    )
    return {
        "days_back": days_back,
        **performance_snapshot,
        **_build_benchmark_snapshot(experiment_summaries, open_clusters),
        "memory_utilization": _build_memory_snapshot(memory_utilization),
        "memory_governance": memory_governance,
        "low_yield_references": low_yield_references,
    }


async def build_improvement_signal_digest(
    *,
    project_id: str | None,
    primary_agent_slug: str = "persona",
    days_back: int = 7,
    include_team: bool = True,
    max_agents: int = 4,
    max_experiments: int = 3,
    max_clusters: int = 5,
    max_reference_items: int = 6,
) -> str:
    """Return a compact evidence digest for Jenny's self-improvement loops."""
    snapshot = await collect_improvement_signal_snapshot(
        project_id=project_id,
        primary_agent_slug=primary_agent_slug,
        days_back=days_back,
        include_team=include_team,
        max_agents=max_agents,
        max_experiments=max_experiments,
        max_clusters=max_clusters,
        max_reference_items=max_reference_items,
    )

    return "\n\n".join([
        f"# Improvement Signals ({days_back}d)",
        _build_performance_section(snapshot),
        _build_benchmark_section(snapshot),
        _build_memory_section(snapshot["memory_utilization"]),
        _build_memory_governance_section(snapshot["memory_governance"]),
        _build_reference_yield_section(snapshot["low_yield_references"]),
    ])
