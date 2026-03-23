"""Combined evidence digest for autonomous agent improvement decisions."""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select

from app.db import async_session
from app.models import AgentBenchmarkExperiment, AgentRegressionCluster, Session, SessionEvent
from app.models.agent_performance_log import AgentPerformanceLog
from app.models.session import SessionEventType
from app.services.agent_benchmark_service import get_benchmark_experiment_summary_by_key
from app.services.benchmark_failure_classification import (
    categorize_benchmark_failure_detail,
)
from app.services.memory._analytics_utilization import get_memory_utilization_summary
from app.services.memory.episode_operations import batch_get_episodes


def _format_timestamp(value: datetime | None) -> str:
    if value is None:
        return "?"
    return value.astimezone(UTC).strftime("%Y-%m-%d %H:%M")


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


def _build_performance_snapshot(
    performance_logs: list[Any],
    *,
    primary_agent_slug: str,
    include_team: bool,
    max_agents: int,
) -> dict[str, Any]:
    counts_by_agent: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    system_counts: dict[str, int] = defaultdict(int)
    repeated_issues: dict[tuple[str, str], dict[str, Any]] = {}

    for log in performance_logs:
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

    ordered_agents = _select_agent_order(
        counts_by_agent,
        primary_agent_slug=primary_agent_slug,
        include_team=include_team,
        max_agents=max_agents,
    )

    repeated_issue_limit = max(1, max_agents * 2)
    repeated_issue_items: list[dict[str, Any]] = []
    for (agent_slug, content), info in sorted(
        repeated_issues.items(),
        key=lambda item: (
            item[0][0] != primary_agent_slug,
            -int(item[1]["count"]),
            -int(item[1]["latest"].timestamp()) if item[1]["latest"] else 0,
        ),
    ):
        if agent_slug not in ordered_agents:
            continue
        repeated_issue_items.append({
            "agent_slug": agent_slug,
            "feedback_type": "friction",
            "content": content,
            "count": int(info["count"]),
            "latest_at": info["latest"].isoformat() if info["latest"] else None,
        })
        if len(repeated_issue_items) >= repeated_issue_limit:
            break

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
    visible_clusters = []
    for cluster in open_clusters:
        failure_category = categorize_benchmark_failure_detail(str(cluster.failure_detail or ""))
        if failure_category == "infra":
            continue
        visible_clusters.append((cluster, failure_category))
    return {
        "recent_benchmark_experiments": experiment_summaries,
        "open_regression_clusters": [
            {
                "case_id": str(cluster.case_id),
                "occurrence_count": int(cluster.occurrence_count or 0),
                "failure_detail": str(cluster.failure_detail or ""),
                "failure_kind": "model",
                "failure_category": failure_category,
                "last_seen_at": cluster.last_seen_at.isoformat() if cluster.last_seen_at else None,
            }
            for cluster, failure_category in visible_clusters
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
        cited = cited_counts.get(uuid, 0)
        rate = cited / selected if selected else 0.0
        detail = episode_details.get(uuid) or {}
        label = str(
            detail.get("name") or detail.get("content") or uuid[:8]
        ).strip().splitlines()[0]
        low_yield_references.append({
            "uuid": uuid,
            "label": label,
            "selected": selected,
            "cited": cited,
            "citation_rate": rate,
            "tags": list(detail.get("tags") or []),
        })
        if len(low_yield_references) >= max_reference_items:
            break
    return low_yield_references


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

        experiment_stmt = select(AgentBenchmarkExperiment).where(
            AgentBenchmarkExperiment.agent_slug == primary_agent_slug,
            AgentBenchmarkExperiment.updated_at >= cutoff,
        )
        if project_id:
            experiment_stmt = experiment_stmt.where(AgentBenchmarkExperiment.project_id == project_id)
        experiment_stmt = experiment_stmt.order_by(
            AgentBenchmarkExperiment.updated_at.desc()
        ).limit(max_experiments)
        experiments = list((await db.execute(experiment_stmt)).scalars().all())

        cluster_stmt = (
            select(AgentRegressionCluster)
            .where(
                AgentRegressionCluster.agent_slug == primary_agent_slug,
                AgentRegressionCluster.status == "open",
            )
            .order_by(AgentRegressionCluster.last_seen_at.desc())
            .limit(max_clusters)
        )
        open_clusters = list((await db.execute(cluster_stmt)).scalars().all())

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

        experiment_summaries: list[dict[str, Any]] = []
        for experiment in experiments:
            summary = await get_benchmark_experiment_summary_by_key(db, experiment.experiment_key)
            if summary is None:
                continue
            experiment_summaries.append({
                "suite_id": str(experiment.suite_id),
                "decision": str(summary.get("decision") or "hold"),
                "decision_reason": summary.get("decision_reason"),
                "score_delta": float((summary.get("score_delta") or {}).get("mean") or 0.0),
                "pass_rate_delta": float(
                    (summary.get("pass_rate_delta") or {}).get("mean") or 0.0
                ),
            })

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
    benchmark_snapshot = _build_benchmark_snapshot(experiment_summaries, open_clusters)
    low_yield_references = await _collect_reference_yield_snapshot(
        memory_events,
        max_reference_items=max_reference_items,
    )

    return {
        "days_back": days_back,
        **performance_snapshot,
        **benchmark_snapshot,
        "memory_utilization": _build_memory_snapshot(memory_utilization),
        "low_yield_references": low_yield_references,
    }


def _build_performance_section(snapshot: dict[str, Any]) -> str:
    volume_lines = ["## Agent signal volume"]
    if snapshot["agent_signal_volume"]:
        for item in snapshot["agent_signal_volume"]:
            volume_lines.append(
                f"- {item['agent_slug']}: friction={item['friction']} "
                f"improvement={item['improvement']} "
                f"idea={item['idea']} praise={item['praise']} "
                f"system={item['system']}"
            )
    else:
        volume_lines.append("- none")

    issue_lines = ["## Repeated issues"]
    if snapshot["repeated_issues"]:
        for item in snapshot["repeated_issues"]:
            issue_lines.append(
                f"- {item['agent_slug']} [{item['count']}x, latest {_format_timestamp(_parse_iso(item['latest_at']))}]: "
                f"{item['content']}"
            )
    else:
        issue_lines.append("- none")

    return "\n".join([*volume_lines, "", *issue_lines])


def _build_benchmark_section(snapshot: dict[str, Any]) -> str:
    experiment_lines = ["## Recent benchmark experiments"]
    if snapshot["recent_benchmark_experiments"]:
        for summary in snapshot["recent_benchmark_experiments"]:
            experiment_lines.append(
                f"- suite={summary['suite_id']} decision={summary['decision']} "
                f"score_delta={summary['score_delta']:.3f} "
                f"pass_rate_delta={summary['pass_rate_delta']:.3f} "
                f"reason={summary['decision_reason'] or 'n/a'}"
            )
    else:
        experiment_lines.append("- none")

    cluster_lines = ["## Open regression clusters"]
    if snapshot["open_regression_clusters"]:
        for cluster in snapshot["open_regression_clusters"]:
            cluster_lines.append(
                f"- {cluster['case_id']} [{cluster['occurrence_count']}x, "
                f"{cluster['failure_category'] or 'unknown'}, "
                f"last {_format_timestamp(_parse_iso(cluster['last_seen_at']))}]: "
                f"{cluster['failure_detail']}"
            )
    else:
        cluster_lines.append("- none")

    return "\n".join([*experiment_lines, "", *cluster_lines])


def _build_memory_section(memory_snapshot: dict[str, Any]) -> str:
    return "\n".join([
        "## Memory utilization",
        (
            f"- injection_sessions={memory_snapshot['injection_sessions']} "
            f"citation_sessions={memory_snapshot['citation_sessions']} "
            f"lookup_after_injection_sessions={memory_snapshot['lookup_after_injection_sessions']}"
        ),
        (
            f"- citation_session_rate={memory_snapshot['citation_session_rate']:.3f} "
            f"assistant_citation_rate={memory_snapshot['assistant_citation_rate']:.3f} "
            f"selected_reference_citation_rate={memory_snapshot['selected_reference_citation_rate']:.3f}"
        ),
        (
            f"- memory_search_calls={memory_snapshot['memory_search_calls']} "
            f"memory_get_calls={memory_snapshot['memory_get_calls']} "
            f"memory_debug_coverage_rate={memory_snapshot['memory_debug_coverage_rate']:.3f}"
        ),
    ])


def _build_reference_yield_section(reference_items: list[dict[str, Any]]) -> str:
    lines = ["## Low-yield references"]
    if reference_items:
        for item in reference_items:
            tags = ",".join(item["tags"]) or "-"
            lines.append(
                f"- {item['label']} ({item['uuid'][:8]}): selected={item['selected']} "
                f"cited={item['cited']} rate={item['citation_rate']:.3f} tags={tags}"
            )
    else:
        lines.append("- none")
    return "\n".join(lines)


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


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
        _build_reference_yield_section(snapshot["low_yield_references"]),
    ])
