"""Text-rendering helpers for improvement signal digests."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any


def _format_timestamp(value: datetime | None) -> str:
    if value is None:
        return "?"
    return value.astimezone(UTC).strftime("%Y-%m-%d %H:%M")


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _append_sample_block(
    lines: list[str],
    header: str,
    items: list[dict[str, Any]],
    fmt_fn: Any,
) -> None:
    if not items:
        return
    lines.append(header)
    for item in items:
        lines.append(fmt_fn(item))


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


def _build_memory_governance_section(snapshot: dict[str, Any]) -> str:
    startup_count = int(snapshot.get("startup_profile_agent_target_count", 0))
    lines = [
        "## Memory governance",
        (
            f"- health_status={snapshot.get('health_status', 'healthy')} "
            f"hard_issue_count={snapshot.get('hard_issue_count', 0)} "
            f"soft_issue_count={snapshot.get('soft_issue_count', 0)} "
            f"soft_limit_breach_count={snapshot.get('soft_limit_breach_count', 0)} "
            f"issue_count={snapshot['issue_count']}"
        ),
        (
            f"- active_count={snapshot['active_count']} "
            f"active_agent_count={snapshot.get('active_agent_count', 0)} "
            f"targeted_count={snapshot['targeted_count']} "
            f"explicit_exclusion_count={snapshot['explicit_exclusion_count']} "
            f"untargeted_reference_count={snapshot['untargeted_reference_count']}"
        ),
        (
            f"- policy_with_targeting_count={snapshot['policy_with_targeting_count']} "
            f"missing_reference_summary_count={snapshot['missing_reference_summary_count']} "
            f"oversized_policy_count={snapshot['oversized_policy_count']}"
        ),
        (
            f"- alias_trigger_task_type_count={snapshot['alias_trigger_task_type_count']} "
            f"startup_profile_agent_target_count={startup_count} "
            f"invalid_trigger_task_type_count={snapshot['invalid_trigger_task_type_count']}"
        ),
        (
            f"- custom_memory_config_agent_count={snapshot.get('custom_memory_config_agent_count', 0)} "
            f"tool_capabilities_disabled_agent_count={snapshot.get('tool_capabilities_disabled_agent_count', 0)} "
            f"project_index_disabled_agent_count={snapshot.get('project_index_disabled_agent_count', 0)} "
            f"reference_index_disabled_agent_count={snapshot.get('reference_index_disabled_agent_count', 0)} "
            f"memory_exclusion_agent_count={snapshot.get('memory_exclusion_agent_count', 0)} "
            f"excluded_memory_uuid_count={snapshot.get('excluded_memory_uuid_count', 0)}"
        ),
    ]
    _append_sample_block(
        lines, "- top untargeted references:", snapshot.get("untargeted_reference_samples") or [],
        lambda i: f"  - {i['label']} ({i['uuid'][:8]}): {i.get('details') or 'untargeted reference'}",
    )
    _append_sample_block(
        lines, "- top oversized policies:", snapshot.get("oversized_policy_samples") or [],
        lambda i: f"  - {i['label']} ({i['uuid'][:8]}): {i.get('details') or 'oversized policy'}",
    )
    _append_sample_block(
        lines, "- startup profile + agent target samples:", snapshot.get("startup_profile_agent_target_samples") or [],
        lambda i: f"  - {i['label']} ({i['uuid'][:8]})",
    )
    _append_sample_block(
        lines, "- invalid trigger samples:", snapshot.get("invalid_trigger_task_type_samples") or [],
        lambda i: f"  - {i['label']} ({i['uuid'][:8]}): {', '.join(i['invalid_types'])}",
    )
    return "\n".join(lines)


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
