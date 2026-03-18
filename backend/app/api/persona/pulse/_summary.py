"""Pulse summary and scorecard aggregation."""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import UTC, datetime
from statistics import median

from app.api.persona.schemas import (
    PersonaAgentScorecard,
    PersonaIssueGroup,
    PersonaIssueMarker,
    PersonaPulseMetric,
    PersonaPulseSummary,
    PersonaStreamEntry,
)
from app.models.session import Session

from ._classify import SessionPulse
from ._constants import FILTERABLE_TAGS

_METRIC_DEFINITIONS: tuple[tuple[str, str, str], ...] = (
    ("friction", "Friction", "Runs with issue markers worth reviewing in the current history window."),
    ("error", "Errors", "Runs with explicit failures, crashes, or non-zero tool outcomes."),
    ("warning", "Warnings", "Runs that completed but still reported warnings or blockers."),
    ("stalled", "Stalled", "Runs that waited on missing context, follow-up, or recent activity."),
    ("instruction_drift", "Instruction Drift", "Runs that bypassed the intended workflow or used the wrong command path."),
    ("tool_friction", "Tool Friction", "Runs where tool use itself caused avoidable drag or failure."),
    ("retries", "Retries", "Runs that had to repeat the same step before they could continue."),
    ("recovered", "Recovered", "Runs that hit trouble but still completed after the issue was resolved."),
    ("escalation", "Escalations", "Runs that needed a human review, approval, or manual follow-up."),
)


def _build_metrics(metric_counts: Counter[str]) -> list[PersonaPulseMetric]:
    return [
        PersonaPulseMetric(key=key, label=label, count=metric_counts[key], description=description)
        for key, label, description in _METRIC_DEFINITIONS
    ]


def _build_issue_groups(
    issue_groups: dict[str, list[tuple[Session, PersonaIssueMarker, PersonaStreamEntry]]],
) -> list[PersonaIssueGroup]:
    grouped: list[PersonaIssueGroup] = []
    for fingerprint, group in issue_groups.items():
        latest_session, latest_marker, latest_entry = max(group, key=lambda item: item[1].created_at)
        grouped.append(
            PersonaIssueGroup(
                fingerprint=fingerprint,
                title=latest_marker.title,
                summary=latest_marker.summary,
                count=len(group),
                primary_tag=latest_marker.primary_tag,
                root_cause=latest_marker.primary_root_cause,
                agent_slugs=sorted({item[0].agent_slug or "persona" for item in group}),
                latest_entry_id=latest_entry.id,
                latest_session_id=latest_session.id,
                latest_timestamp=latest_marker.created_at,
            )
        )
    return sorted(
        grouped,
        key=lambda issue: (issue.count, issue.latest_timestamp or datetime.min.replace(tzinfo=UTC)),
        reverse=True,
    )[:8]


def _build_scorecard(
    agent_slug: str,
    agent_sessions: list[tuple[Session, SessionPulse]],
) -> PersonaAgentScorecard:
    durations = [
        int((session.updated_at - session.created_at).total_seconds())
        for session, _pulse in agent_sessions
        if session.updated_at and session.created_at
    ]
    issue_titles = Counter(
        marker.title
        for _session, pulse in agent_sessions
        for marker in pulse.issue_markers
        if marker.title
    )
    root_cause_counts = Counter(
        marker.primary_root_cause
        for _session, pulse in agent_sessions
        for marker in pulse.issue_markers
        if marker.primary_root_cause
    )
    return PersonaAgentScorecard(
        agent_slug=agent_slug,
        label=agent_slug.replace("-", " "),
        session_count=len(agent_sessions),
        success_count=sum(1 for session, _pulse in agent_sessions if session.status == "completed"),
        friction_count=sum(1 for _session, pulse in agent_sessions if "friction" in pulse.tags),
        error_count=sum(1 for _session, pulse in agent_sessions if "error" in pulse.tags),
        recovered_count=sum(1 for _session, pulse in agent_sessions if "recovered" in pulse.tags),
        stalled_count=sum(1 for _session, pulse in agent_sessions if "stalled" in pulse.tags),
        instruction_drift_count=sum(1 for _session, pulse in agent_sessions if "instruction_drift" in pulse.tags),
        tool_friction_count=sum(1 for _session, pulse in agent_sessions if "tool_friction" in pulse.tags),
        median_runtime_seconds=int(median(durations)) if durations else None,
        top_issue=issue_titles.most_common(1)[0][0] if issue_titles else None,
        top_root_cause=root_cause_counts.most_common(1)[0][0] if root_cause_counts else None,
    )


def build_pulse_summary(
    entries: list[PersonaStreamEntry],
    sessions: list[Session],
    session_pulses: dict[str, SessionPulse],
) -> PersonaPulseSummary:
    session_entries = [entry for entry in entries if entry.entry_type != "message"]
    entry_by_session_id = {entry.session_id: entry for entry in session_entries}
    sessions_by_agent: dict[str, list[tuple[Session, SessionPulse]]] = defaultdict(list)
    issue_groups: dict[str, list[tuple[Session, PersonaIssueMarker, PersonaStreamEntry]]] = defaultdict(list)
    metric_counts: Counter[str] = Counter()

    for session in sessions:
        pulse = session_pulses.get(session.id)
        if pulse is None:
            continue
        for tag in pulse.tags:
            if tag in FILTERABLE_TAGS:
                metric_counts[tag] += 1
        agent_label = session.agent_slug or "persona"
        sessions_by_agent[agent_label].append((session, pulse))
        entry = entry_by_session_id.get(session.id)
        if entry is None:
            continue
        for marker in pulse.issue_markers:
            if marker.fingerprint:
                issue_groups[marker.fingerprint].append((session, marker, entry))

    scorecards = sorted(
        [_build_scorecard(slug, agent_sessions) for slug, agent_sessions in sorted(sessions_by_agent.items())],
        key=lambda item: (item.friction_count, item.error_count, item.session_count),
        reverse=True,
    )[:6]

    return PersonaPulseSummary(
        metrics=_build_metrics(metric_counts),
        issue_groups=_build_issue_groups(issue_groups),
        agent_scorecards=scorecards,
    )
