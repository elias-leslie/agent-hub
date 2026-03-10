"""Pulse classification and trend aggregation for Jenny's unified stream."""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from statistics import median
from typing import Any

from app.models.session import Session, SessionEvent

from .schemas import (
    PersonaAgentScorecard,
    PersonaIssueGroup,
    PersonaPulseMetric,
    PersonaPulseSummary,
    PersonaStreamEntry,
)

_FILTERABLE_TAGS = (
    "friction",
    "error",
    "warning",
    "stalled",
    "retries",
    "instruction_drift",
    "tool_friction",
    "recovered",
    "escalation",
)
_ROOT_CAUSE_PRIORITY = ("workflow", "tool", "context", "infra", "prompt", "unknown")
_TAG_PRIORITY = (
    "instruction_drift",
    "error",
    "stalled",
    "tool_friction",
    "warning",
    "retries",
    "escalation",
    "recovered",
)
_SUCCESS_TERMS = ("passed", "completed", "succeeded", "verified", "published", "merged", "fixed", "resolved")
_ERROR_TERMS = (
    "error",
    "failed",
    "failure",
    "traceback",
    "exception",
    "enoent",
    "non-zero exit",
    "exit code 1",
    "exit code 2",
    "command failed",
)
_WARNING_TERMS = ("warning", "blocked", "interrupted", "manual prerequisite", "manual prerequisites", "needs revision")
_STALLED_TERMS = ("waiting", "stalled", "stuck", "hung", "awaiting", "blocked on", "pending approval", "manual prerequisite")
_CONTEXT_TERMS = ("missing context", "need context", "insufficient context", "unclear context", "no task context", "lacked context")
_INFRA_TERMS = (
    "redis",
    "postgres",
    "socket",
    "connection refused",
    "service unavailable",
    "network",
    "gateway timeout",
    "daemon",
)
_PROMPT_TERMS = ("instruction", "instructions", "prompt", "mandate", "guardrail", "ignored")
_ESCALATION_TERMS = ("escalate", "human", "manual intervention", "needs review", "approval", "user intervention")
_TOOL_FRICTION_TERMS = (
    "not found",
    "missing",
    "invalid",
    "blank dom",
    "fetch failed",
    "timed out",
    "timeout",
    "unsupported",
)
_RAW_COMMAND_RULES: tuple[tuple[str, str, str], ...] = (
    ("pytest", "workflow", "Used raw pytest instead of dt"),
    ("ruff", "workflow", "Used raw ruff instead of dt"),
    ("mypy", "workflow", "Used raw mypy instead of dt"),
    ("tsc", "workflow", "Used raw tsc instead of dt"),
    ("biome", "workflow", "Used raw biome instead of dt"),
    ("git commit", "workflow", "Used raw git commit instead of commit.sh"),
    ("systemctl", "workflow", "Used systemctl instead of restart.sh/rebuild.sh"),
    ("psql", "workflow", "Used raw psql instead of db"),
)
_ALLOWED_COMMAND_PREFIXES = (
    "dt ",
    "st ",
    "db ",
    "bash ~/agent-hub/scripts/rebuild.sh",
    "bash ~/agent-hub/scripts/restart.sh",
    "bash ~/summitflow/scripts/commit.sh",
    "/commit_it",
)


@dataclass(slots=True)
class SessionPulse:
    tags: list[str] = field(default_factory=list)
    primary_tag: str | None = None
    root_causes: list[str] = field(default_factory=list)
    primary_root_cause: str | None = None
    summary: str | None = None
    fingerprint: str | None = None
    issue_title: str | None = None


def _stringify(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=True, sort_keys=True)
    except TypeError:
        return str(value)


def _event_text(event: SessionEvent) -> str:
    return " ".join(
        part
        for part in [
            _stringify(event.content),
            _stringify(event.tool_input),
            _stringify(event.tool_output),
            _stringify(event.tool_name),
            _stringify(event.role),
        ]
        if part
    ).lower()


def _contains_term(text: str, term: str) -> bool:
    return re.search(rf"\b{re.escape(term)}\b", text) is not None


def _contains_any(text: str, terms: tuple[str, ...]) -> bool:
    return any(_contains_term(text, term) for term in terms)


def _is_prompt_like_text(text: str) -> bool:
    return (
        "# persona safety boundaries" in text
        or "<persona_context>" in text
        or "<heartbeat_instructions>" in text
        or (len(text) > 900 and text.count("\n") > 20)
    )


def _should_ignore_event(event: SessionEvent, event_text: str) -> bool:
    return (
        event.event_type in {"system_message", "memory_inject", "memory_cite"}
        or _is_prompt_like_text(event_text)
    )


def _event_has_error(event: SessionEvent, event_text: str) -> bool:
    if event.event_type == "error":
        return True
    if _contains_any(event_text, _ERROR_TERMS):
        return True
    if isinstance(event.tool_output, dict):
        status = str(event.tool_output.get("status", "")).lower()
        exit_code = event.tool_output.get("exit_code")
        is_error = event.tool_output.get("is_error")
        if status in {"error", "failed", "blocked"}:
            return True
        if exit_code not in (None, 0, "0"):
            return True
        if is_error is True:
            return True
    return False


def _event_has_success(event: SessionEvent, event_text: str) -> bool:
    if event.event_type == "assistant_message" and "session interrupted" in event_text:
        return False
    if _contains_any(event_text, _SUCCESS_TERMS):
        return True
    if isinstance(event.tool_output, dict):
        status = str(event.tool_output.get("status", "")).lower()
        exit_code = event.tool_output.get("exit_code")
        if status in {"ok", "success", "completed", "passed"}:
            return True
        if exit_code in (0, "0"):
            return True
    return False


def _extract_command(event: SessionEvent) -> str | None:
    if isinstance(event.tool_input, dict):
        for key in ("command", "cmd", "invocation"):
            value = event.tool_input.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    if event.tool_name:
        return event.tool_name.strip()
    return None


def _normalize_issue_key(value: str) -> str:
    normalized = value.lower()
    normalized = re.sub(r"task-[a-z0-9]+", "task-id", normalized)
    normalized = re.sub(r"\b[0-9]+\b", "#", normalized)
    normalized = re.sub(r"\s+", "-", normalized)
    return normalized[:80]


def _primary_value(values: set[str], order: tuple[str, ...]) -> str | None:
    for value in order:
        if value in values:
            return value
    return next(iter(values), None)


def _first_matching_rule(command: str) -> tuple[str, str, str] | None:
    normalized = command.lower().strip()
    if normalized.startswith(_ALLOWED_COMMAND_PREFIXES):
        return None
    for pattern, root_cause, title in _RAW_COMMAND_RULES:
        if normalized.startswith(pattern):
            return pattern, root_cause, title
    return None


def classify_session_pulse(session: Session, events: list[SessionEvent]) -> SessionPulse:
    tags: set[str] = set()
    root_causes: set[str] = set()
    tool_use_counts: Counter[str] = Counter()
    tool_failure_counts: Counter[str] = Counter()
    raw_command_rule: tuple[str, str, str] | None = None
    had_error = session.status == "failed"
    saw_success_after_error = False
    explicit_retry_signal = False

    for event in events:
        event_text = _event_text(event)
        if _should_ignore_event(event, event_text):
            continue
        command = _extract_command(event)
        if event.event_type == "tool_use" and event.tool_name:
            tool_use_counts[event.tool_name] += 1
        if command and raw_command_rule is None:
            raw_command_rule = _first_matching_rule(command)
        if raw_command_rule:
            tags.add("instruction_drift")
            root_causes.add(raw_command_rule[1])
        if _contains_any(event_text, _PROMPT_TERMS) and "instruction_drift" in tags:
            root_causes.add("prompt")
        if _contains_any(event_text, _CONTEXT_TERMS):
            root_causes.add("context")
        if _contains_any(event_text, _INFRA_TERMS):
            root_causes.add("infra")
        if _contains_any(event_text, _WARNING_TERMS):
            tags.add("warning")
        if _contains_any(event_text, _STALLED_TERMS):
            tags.add("stalled")
        if _contains_any(event_text, _ESCALATION_TERMS):
            tags.add("escalation")
        if _event_has_error(event, event_text):
            had_error = True
            tags.add("error")
            tags.add("tool_friction")
            if event.tool_name:
                tool_failure_counts[event.tool_name] += 1
            if _contains_any(event_text, _TOOL_FRICTION_TERMS):
                root_causes.add("tool")
        if _event_has_success(event, event_text) and had_error:
            saw_success_after_error = True
        if _contains_any(event_text, _TOOL_FRICTION_TERMS):
            tags.add("tool_friction")
            root_causes.add("tool")
        if _contains_any(event_text, ("retry", "retried", "retrying")):
            explicit_retry_signal = True

    if session.status == "active" and session.updated_at and datetime.now(UTC) - session.updated_at > timedelta(minutes=20):
        tags.add("stalled")
    if explicit_retry_signal or any(count > 1 for count in tool_failure_counts.values()):
        tags.add("retries")
    if saw_success_after_error and session.status == "completed":
        tags.add("recovered")
    if tags.intersection({"error", "warning", "stalled", "retries", "instruction_drift", "tool_friction", "escalation"}):
        tags.add("friction")
    if tags and not root_causes:
        if "instruction_drift" in tags:
            root_causes.add("workflow")
        elif "tool_friction" in tags or "error" in tags:
            root_causes.add("tool")
        elif "stalled" in tags:
            root_causes.add("context")
        else:
            root_causes.add("unknown")

    primary_tag = _primary_value(tags, _TAG_PRIORITY)
    primary_root_cause = _primary_value(root_causes, _ROOT_CAUSE_PRIORITY)

    top_failed_tool = tool_failure_counts.most_common(1)[0][0] if tool_failure_counts else None
    issue_title: str | None = None
    fingerprint: str | None = None
    summary_parts: list[str] = []

    if raw_command_rule:
        issue_title = raw_command_rule[2]
        fingerprint = f"instruction-drift:{raw_command_rule[0]}"
        summary_parts.append(raw_command_rule[2])
    if top_failed_tool:
        issue_title = issue_title or f"{top_failed_tool} kept failing or wasting turns"
        fingerprint = fingerprint or f"tool-friction:{_normalize_issue_key(top_failed_tool)}"
        summary_parts.append(f"{top_failed_tool} hit repeated tool friction")
    if "stalled" in tags:
        issue_title = issue_title or "Work stalled waiting on context or follow-up"
        fingerprint = fingerprint or f"stalled:{primary_root_cause or 'unknown'}"
        summary_parts.append("work stalled waiting on follow-up")
    if "escalation" in tags:
        issue_title = issue_title or "Needed manual follow-up"
        fingerprint = fingerprint or f"escalation:{primary_root_cause or 'unknown'}"
        summary_parts.append("needed manual follow-up")
    if "warning" in tags and issue_title is None:
        issue_title = "Completed with warnings"
        fingerprint = f"warning:{primary_root_cause or 'unknown'}"
        summary_parts.append("completed with warnings")
    if "retries" in tags:
        summary_parts.append("retried repeated steps")
    if "recovered" in tags:
        summary_parts.append("recovered before completion")
    if session.status == "completed" and not tags.intersection({"error", "warning", "stalled", "instruction_drift", "tool_friction", "escalation"}):
        summary_parts.append("completed cleanly")

    return SessionPulse(
        tags=sorted(tags, key=lambda item: _FILTERABLE_TAGS.index(item) if item in _FILTERABLE_TAGS else 99),
        primary_tag=primary_tag,
        root_causes=sorted(root_causes, key=lambda item: _ROOT_CAUSE_PRIORITY.index(item) if item in _ROOT_CAUSE_PRIORITY else 99),
        primary_root_cause=primary_root_cause,
        summary="; ".join(dict.fromkeys(summary_parts)) or None,
        fingerprint=fingerprint,
        issue_title=issue_title,
    )


def build_session_pulses(
    sessions: list[Session],
    events_by_session_id: dict[str, list[SessionEvent]],
) -> dict[str, SessionPulse]:
    return {
        session.id: classify_session_pulse(session, events_by_session_id.get(session.id, []))
        for session in sessions
    }


def build_pulse_summary(
    entries: list[PersonaStreamEntry],
    sessions: list[Session],
    session_pulses: dict[str, SessionPulse],
) -> PersonaPulseSummary:
    session_entries = [entry for entry in entries if entry.entry_type != "message"]
    entry_by_session_id = {entry.session_id: entry for entry in session_entries}
    sessions_by_agent: dict[str, list[tuple[Session, SessionPulse]]] = defaultdict(list)
    issue_groups: dict[str, list[tuple[Session, SessionPulse, PersonaStreamEntry]]] = defaultdict(list)
    metric_counts: Counter[str] = Counter()

    for session in sessions:
        pulse = session_pulses.get(session.id)
        if pulse is None:
            continue
        for tag in pulse.tags:
            if tag in _FILTERABLE_TAGS:
                metric_counts[tag] += 1
        agent_label = session.agent_slug or "persona"
        sessions_by_agent[agent_label].append((session, pulse))
        if pulse.fingerprint and pulse.issue_title:
            entry = entry_by_session_id.get(session.id)
            if entry is not None:
                issue_groups[pulse.fingerprint].append((session, pulse, entry))

    metrics = [
        PersonaPulseMetric(
            key="friction",
            label="Friction",
            count=metric_counts["friction"],
            description="Sessions that showed warnings, failures, stalls, or other operational drag.",
        ),
        PersonaPulseMetric(
            key="error",
            label="Errors",
            count=metric_counts["error"],
            description="Sessions with explicit failures, crashes, or error events.",
        ),
        PersonaPulseMetric(
            key="warning",
            label="Warnings",
            count=metric_counts["warning"],
            description="Runs that completed but still reported warnings or blockers.",
        ),
        PersonaPulseMetric(
            key="stalled",
            label="Stalled",
            count=metric_counts["stalled"],
            description="Work that waited on follow-up, context, or stayed active too long.",
        ),
        PersonaPulseMetric(
            key="instruction_drift",
            label="Instruction Drift",
            count=metric_counts["instruction_drift"],
            description="Runs that bypassed guarded workflows or ignored the intended tool path.",
        ),
        PersonaPulseMetric(
            key="tool_friction",
            label="Tool Friction",
            count=metric_counts["tool_friction"],
            description="Runs where tools failed, were missing, or wasted turns before progress resumed.",
        ),
        PersonaPulseMetric(
            key="retries",
            label="Retries",
            count=metric_counts["retries"],
            description="Runs that repeated the same tool or step multiple times.",
        ),
        PersonaPulseMetric(
            key="recovered",
            label="Recovered",
            count=metric_counts["recovered"],
            description="Runs that hit trouble but still recovered before finishing.",
        ),
        PersonaPulseMetric(
            key="escalation",
            label="Escalations",
            count=metric_counts["escalation"],
            description="Runs that needed human review, approval, or manual follow-up.",
        ),
    ]

    grouped_issues: list[PersonaIssueGroup] = []
    for fingerprint, group in issue_groups.items():
        latest_session, _latest_pulse, latest_entry = max(group, key=lambda item: item[2].timestamp)
        grouped_issues.append(
            PersonaIssueGroup(
                fingerprint=fingerprint,
                title=group[0][1].issue_title or "Repeated issue",
                summary=group[0][1].summary or "Repeated issue observed",
                count=len(group),
                primary_tag=group[0][1].primary_tag or "friction",
                root_cause=group[0][1].primary_root_cause,
                agent_slugs=sorted({item[0].agent_slug or "persona" for item in group}),
                latest_entry_id=latest_entry.id,
                latest_session_id=latest_session.id,
                latest_timestamp=latest_entry.timestamp,
            )
        )

    grouped_issues = sorted(
        grouped_issues,
        key=lambda issue: (issue.count, issue.latest_timestamp or datetime.min.replace(tzinfo=UTC)),
        reverse=True,
    )[:8]

    scorecards: list[PersonaAgentScorecard] = []
    for agent_slug, agent_sessions in sorted(sessions_by_agent.items()):
        durations = [
            int((session.updated_at - session.created_at).total_seconds())
            for session, _pulse in agent_sessions
            if session.updated_at and session.created_at
        ]
        issue_titles = Counter(pulse.issue_title for _session, pulse in agent_sessions if pulse.issue_title)
        root_cause_counts = Counter(
            pulse.primary_root_cause for _session, pulse in agent_sessions if pulse.primary_root_cause
        )
        scorecards.append(
            PersonaAgentScorecard(
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
        )

    scorecards.sort(key=lambda item: (item.friction_count, item.error_count, item.session_count), reverse=True)

    return PersonaPulseSummary(
        metrics=metrics,
        issue_groups=grouped_issues,
        agent_scorecards=scorecards[:6],
    )
