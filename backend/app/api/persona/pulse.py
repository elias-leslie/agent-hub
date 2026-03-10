"""Pulse classification and trend aggregation for Jenny's unified stream."""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from statistics import median
from typing import Any

from app.models.session import Session

from .schemas import (
    PersonaAgentScorecard,
    PersonaIssueGroup,
    PersonaIssueMarker,
    PersonaPulseMetric,
    PersonaPulseSummary,
    PersonaStreamEntry,
    PersonaStreamEventPreview,
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
_HUMAN_TEXT_KEYS = ("summary", "content", "message", "stderr", "stdout", "error", "detail", "result")


@dataclass(slots=True)
class SessionPulse:
    issue_markers: list[PersonaIssueMarker] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    primary_tag: str | None = None
    root_causes: list[str] = field(default_factory=list)
    primary_root_cause: str | None = None
    summary: str | None = None


def _contains_term(text: str, term: str) -> bool:
    return re.search(rf"\b{re.escape(term)}\b", text) is not None


def _contains_any(text: str, terms: tuple[str, ...]) -> bool:
    return any(_contains_term(text, term) for term in terms)


def _normalize_issue_key(value: str) -> str:
    normalized = value.lower()
    normalized = re.sub(r"task-[a-z0-9]+", "task-id", normalized)
    normalized = re.sub(r"\b[0-9]+\b", "#", normalized)
    normalized = re.sub(r"[^a-z0-9]+", "-", normalized)
    return normalized.strip("-")[:80]


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


def _is_prompt_like_text(text: str) -> bool:
    return (
        "# persona safety boundaries" in text
        or "<persona_context>" in text
        or "<heartbeat_instructions>" in text
        or (len(text) > 900 and text.count("\n") > 20)
    )


def _parse_structured_preview(value: str | None) -> Any:
    if not value:
        return None
    stripped = value.strip()
    if not stripped.startswith("{") and not stripped.startswith("["):
        return None
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        return None


def _first_human_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        normalized = value.strip()
        return normalized or None
    if isinstance(value, dict):
        for key in _HUMAN_TEXT_KEYS:
            candidate = _first_human_text(value.get(key))
            if candidate:
                return candidate
        for candidate in value.values():
            resolved = _first_human_text(candidate)
            if resolved:
                return resolved
        return None
    if isinstance(value, list):
        for item in value:
            resolved = _first_human_text(item)
            if resolved:
                return resolved
        return None
    return str(value)


def _human_preview_text(preview: PersonaStreamEventPreview) -> str | None:
    for raw_value in (
        preview.content_preview,
        preview.tool_output_preview,
        preview.tool_input_preview,
    ):
        if not raw_value:
            continue
        structured = _parse_structured_preview(raw_value)
        candidate = _first_human_text(structured if structured is not None else raw_value)
        if candidate:
            return candidate
    return None


def _human_text_from_raw(raw_value: str | None) -> str | None:
    if not raw_value:
        return None
    structured = _parse_structured_preview(raw_value)
    candidate = _first_human_text(structured if structured is not None else raw_value)
    if not candidate:
        return None
    normalized = candidate.strip()
    return normalized or None


def _build_marker_detail(preview: PersonaStreamEventPreview, excerpt: str | None, command: str | None) -> str | None:
    detail_lines: list[str] = []
    seen: set[str] = set()

    def append_unique(value: str | None, *, label: str | None = None) -> None:
        if not value:
            return
        normalized = value.strip()
        if not normalized:
            return
        dedupe_key = normalized.lower()
        if dedupe_key in seen:
            return
        seen.add(dedupe_key)
        detail_lines.append(f"{label}: {normalized}" if label else normalized)

    append_unique(excerpt)
    append_unique(command, label="Command")
    append_unique(_human_text_from_raw(preview.content_preview))
    append_unique(_human_text_from_raw(preview.tool_output_preview))
    input_text = _human_text_from_raw(preview.tool_input_preview)
    if input_text and (command is None or input_text.strip().lower() != command.strip().lower()):
        append_unique(input_text, label="Input")

    if not detail_lines:
        return None
    return "\n".join(detail_lines)


def _preview_text(preview: PersonaStreamEventPreview) -> str:
    return " ".join(
        part
        for part in [
            preview.content_preview,
            preview.tool_input_preview,
            preview.tool_output_preview,
            preview.tool_name,
            preview.role,
            preview.event_type,
        ]
        if isinstance(part, str) and part
    ).lower()


def _should_ignore_preview(preview: PersonaStreamEventPreview, preview_text: str) -> bool:
    return preview.event_type in {"system_message", "memory_inject", "memory_cite"} or _is_prompt_like_text(preview_text)


def _tool_output_flags(preview: PersonaStreamEventPreview) -> tuple[str | None, int | str | None, bool | None]:
    structured = _parse_structured_preview(preview.tool_output_preview)
    if not isinstance(structured, dict):
        return None, None, None
    status = structured.get("status")
    exit_code = structured.get("exit_code")
    is_error = structured.get("is_error")
    return (
        str(status).lower() if status is not None else None,
        exit_code,
        is_error if isinstance(is_error, bool) else None,
    )


def _preview_has_error(preview: PersonaStreamEventPreview, preview_text: str) -> bool:
    if preview.event_type == "error":
        return True
    if _contains_any(preview_text, _ERROR_TERMS):
        return True
    status, exit_code, is_error = _tool_output_flags(preview)
    if status in {"error", "failed", "blocked"}:
        return True
    if exit_code not in (None, 0, "0"):
        return True
    return is_error is True


def _preview_has_success(preview: PersonaStreamEventPreview, preview_text: str) -> bool:
    if preview.event_type == "assistant_message" and "session interrupted" in preview_text:
        return False
    if _contains_any(preview_text, _SUCCESS_TERMS):
        return True
    status, exit_code, _is_error = _tool_output_flags(preview)
    if status in {"ok", "success", "completed", "passed"}:
        return True
    return exit_code in (0, "0")


def _extract_command(preview: PersonaStreamEventPreview) -> str | None:
    tool_input = preview.tool_input_preview or ""
    for key in ("command", "cmd", "invocation"):
        match = re.search(rf'"{key}"\s*:\s*"([^"]+)"', tool_input)
        if match:
            return match.group(1).strip()
    if preview.tool_name and preview.event_type == "tool_use":
        return preview.tool_name.strip()
    return None


def _fallback_root_cause(tags: set[str]) -> str | None:
    if "instruction_drift" in tags:
        return "workflow"
    if "tool_friction" in tags or "error" in tags or "retries" in tags:
        return "tool"
    if "stalled" in tags or "warning" in tags or "escalation" in tags:
        return "context"
    return "unknown" if tags else None


def _build_marker_title(
    preview: PersonaStreamEventPreview,
    tags: set[str],
    raw_command_rule: tuple[str, str, str] | None,
) -> str:
    if raw_command_rule:
        return raw_command_rule[2]
    if "error" in tags and preview.tool_name:
        return f"{preview.tool_name} failed"
    if "tool_friction" in tags and preview.tool_name:
        return f"{preview.tool_name} hit tool friction"
    if "stalled" in tags:
        return "Work stalled waiting on context or follow-up"
    if "escalation" in tags:
        return "Needed manual follow-up"
    if "warning" in tags:
        return "Completed with warnings"
    if preview.tool_name:
        return preview.tool_name
    return preview.event_type.replace("_", " ")


def _build_marker_summary(
    preview: PersonaStreamEventPreview,
    tags: set[str],
    title: str,
    excerpt: str | None,
) -> str:
    parts: list[str] = []
    if excerpt and excerpt.lower() != title.lower():
        parts.append(excerpt)
    if not parts:
        if "error" in tags:
            parts.append("The run recorded an explicit failure.")
        elif "tool_friction" in tags:
            parts.append("The tool path wasted turns before progress resumed.")
        elif "stalled" in tags:
            parts.append("The run waited on follow-up or missing context.")
        elif "escalation" in tags:
            parts.append("The run needed manual review or approval.")
        elif "warning" in tags:
            parts.append("The run completed with warnings or blockers.")
        else:
            parts.append(title)
    if "retries" in tags and not any("retry" in part.lower() for part in parts):
        parts.append("The same step had to be retried.")
    return " ".join(dict.fromkeys(parts))


def _build_fingerprint(
    preview: PersonaStreamEventPreview,
    tags: set[str],
    root_cause: str | None,
    raw_command_rule: tuple[str, str, str] | None,
) -> str | None:
    if raw_command_rule:
        return f"instruction-drift:{_normalize_issue_key(raw_command_rule[0])}"
    if preview.tool_name and ("tool_friction" in tags or "error" in tags or "retries" in tags):
        prefix = "tool-friction" if "tool_friction" in tags else "error"
        return f"{prefix}:{_normalize_issue_key(preview.tool_name)}"
    if "stalled" in tags:
        return f"stalled:{root_cause or 'unknown'}"
    if "escalation" in tags:
        return f"escalation:{root_cause or 'unknown'}"
    if "warning" in tags:
        return f"warning:{root_cause or 'unknown'}"
    return None


def _make_issue_marker(
    *,
    event_id: str,
    event_type: str,
    created_at: datetime,
    tool_name: str | None,
    tags: set[str],
    root_causes: set[str],
    title: str,
    summary: str,
    detail: str | None,
    fingerprint: str | None,
) -> PersonaIssueMarker:
    primary_tag = _primary_value(tags, _TAG_PRIORITY) or "warning"
    primary_root_cause = _primary_value(root_causes, _ROOT_CAUSE_PRIORITY)
    return PersonaIssueMarker(
        event_id=event_id,
        event_type=event_type,
        created_at=created_at,
        tool_name=tool_name,
        tags=sorted(tags, key=lambda item: _FILTERABLE_TAGS.index(item) if item in _FILTERABLE_TAGS else 99),
        primary_tag=primary_tag,
        root_causes=sorted(root_causes, key=lambda item: _ROOT_CAUSE_PRIORITY.index(item) if item in _ROOT_CAUSE_PRIORITY else 99),
        primary_root_cause=primary_root_cause,
        title=title,
        summary=summary,
        detail=detail,
        fingerprint=fingerprint,
    )


def _append_summary_marker_if_needed(
    session: Session,
    markers: list[PersonaIssueMarker],
    seen_fingerprints: set[str],
) -> None:
    summary_text = (session.summary_oneliner or "").strip()
    if not summary_text:
        return
    lowered = summary_text.lower()
    tags: set[str] = set()
    root_causes: set[str] = set()
    if _contains_any(lowered, _ERROR_TERMS):
        tags.update({"error", "tool_friction"})
        root_causes.add("tool")
    if _contains_any(lowered, _WARNING_TERMS):
        tags.add("warning")
    if _contains_any(lowered, _STALLED_TERMS):
        tags.add("stalled")
        root_causes.add("context")
    if _contains_any(lowered, _ESCALATION_TERMS):
        tags.add("escalation")
    if not tags:
        return
    root_causes.add(_fallback_root_cause(tags) or "unknown")
    title = _build_marker_title(
        PersonaStreamEventPreview(
            id=f"summary-{session.id}",
            event_type="session_summary",
            created_at=session.updated_at or session.created_at,
            tool_name=None,
            content_preview=summary_text,
            tool_input_preview=None,
            tool_output_preview=None,
            role=None,
            duration_ms=None,
            model_used=None,
        ),
        tags,
        None,
    )
    fingerprint = _build_fingerprint(
        PersonaStreamEventPreview(
            id=f"summary-{session.id}",
            event_type="session_summary",
            created_at=session.updated_at or session.created_at,
            tool_name=None,
            content_preview=summary_text,
            tool_input_preview=None,
            tool_output_preview=None,
            role=None,
            duration_ms=None,
            model_used=None,
        ),
        tags,
        _primary_value(root_causes, _ROOT_CAUSE_PRIORITY),
        None,
    )
    dedupe_key = fingerprint or f"summary-{session.id}"
    if dedupe_key in seen_fingerprints:
        return
    seen_fingerprints.add(dedupe_key)
    markers.append(
        _make_issue_marker(
            event_id=f"summary-{session.id}",
            event_type="session_summary",
            created_at=session.updated_at or session.created_at,
            tool_name=None,
            tags=tags,
            root_causes=root_causes,
            title=title,
            summary=summary_text,
            detail=summary_text,
            fingerprint=fingerprint,
        )
    )


def classify_session_pulse(session: Session, previews: list[PersonaStreamEventPreview]) -> SessionPulse:
    markers: list[PersonaIssueMarker] = []
    seen_fingerprints: set[str] = set()
    root_causes: set[str] = set()
    tags: set[str] = set()
    tool_failure_counts: Counter[str] = Counter()
    explicit_retry_signal = False
    had_issue = False
    had_error = session.status == "failed"
    saw_success_after_issue = False

    ordered_previews = sorted(previews, key=lambda preview: preview.created_at)

    for preview in ordered_previews:
        preview_text = _preview_text(preview)
        if _should_ignore_preview(preview, preview_text):
            continue

        marker_tags: set[str] = set()
        marker_root_causes: set[str] = set()
        excerpt = _human_preview_text(preview)
        command = _extract_command(preview)
        raw_command_rule = _first_matching_rule(command) if command else None

        if raw_command_rule:
            marker_tags.add("instruction_drift")
            marker_root_causes.add(raw_command_rule[1])
        if _contains_any(preview_text, _CONTEXT_TERMS):
            marker_root_causes.add("context")
        if _contains_any(preview_text, _INFRA_TERMS):
            marker_root_causes.add("infra")
        if _contains_any(preview_text, _PROMPT_TERMS) and "instruction_drift" in marker_tags:
            marker_root_causes.add("prompt")

        if _preview_has_error(preview, preview_text):
            marker_tags.add("error")
            marker_tags.add("tool_friction")
            had_issue = True
            had_error = True
            if preview.tool_name:
                tool_failure_counts[preview.tool_name] += 1
            if _contains_any(preview_text, _TOOL_FRICTION_TERMS):
                marker_root_causes.add("tool")

        if _contains_any(preview_text, _WARNING_TERMS):
            marker_tags.add("warning")
            had_issue = True
        if _contains_any(preview_text, _STALLED_TERMS):
            marker_tags.add("stalled")
            had_issue = True
        if _contains_any(preview_text, _ESCALATION_TERMS):
            marker_tags.add("escalation")
            had_issue = True
        if _contains_any(preview_text, _TOOL_FRICTION_TERMS):
            marker_tags.add("tool_friction")
            marker_root_causes.add("tool")
            had_issue = True
        if _contains_any(preview_text, ("retry", "retried", "retrying")):
            marker_tags.add("retries")
            explicit_retry_signal = True
            had_issue = True

        if _preview_has_success(preview, preview_text) and (had_error or had_issue):
            saw_success_after_issue = True

        if not marker_tags:
            continue

        marker_root_causes.add(_fallback_root_cause(marker_tags) or "unknown")
        primary_root_cause = _primary_value(marker_root_causes, _ROOT_CAUSE_PRIORITY)
        title = _build_marker_title(preview, marker_tags, raw_command_rule)
        summary = _build_marker_summary(preview, marker_tags, title, excerpt)
        detail = _build_marker_detail(preview, excerpt, command) or summary
        fingerprint = _build_fingerprint(preview, marker_tags, primary_root_cause, raw_command_rule)
        dedupe_key = fingerprint or f"{preview.id}:{_primary_value(marker_tags, _TAG_PRIORITY)}"
        if dedupe_key in seen_fingerprints:
            continue
        seen_fingerprints.add(dedupe_key)
        markers.append(
            _make_issue_marker(
                event_id=preview.id,
                event_type=preview.event_type,
                created_at=preview.created_at,
                tool_name=preview.tool_name,
                tags=marker_tags,
                root_causes=marker_root_causes,
                title=title,
                summary=summary,
                detail=detail,
                fingerprint=fingerprint,
            )
        )

    if session.status == "active" and session.updated_at and datetime.now(UTC) - session.updated_at > timedelta(minutes=20):
        stalled_fingerprint = "stalled:context"
        if stalled_fingerprint not in seen_fingerprints:
            seen_fingerprints.add(stalled_fingerprint)
            markers.append(
                _make_issue_marker(
                    event_id=f"stalled-{session.id}",
                    event_type="stalled",
                    created_at=session.updated_at,
                    tool_name=None,
                    tags={"stalled"},
                    root_causes={"context"},
                    title="Work stalled waiting on context or follow-up",
                    summary="The run has remained active without a recent update.",
                    detail="The run has remained active without a recent update.",
                    fingerprint=stalled_fingerprint,
                )
            )
            had_issue = True

    top_failed_tool = tool_failure_counts.most_common(1)[0][0] if tool_failure_counts else None
    if explicit_retry_signal or any(count > 1 for count in tool_failure_counts.values()):
        retry_fingerprint = f"retries:{_normalize_issue_key(top_failed_tool or session.agent_slug or session.id)}"
        if retry_fingerprint not in seen_fingerprints:
            seen_fingerprints.add(retry_fingerprint)
            retry_tags = {"retries"}
            retry_root_causes = {"tool" if top_failed_tool else "workflow"}
            if top_failed_tool:
                retry_tags.add("tool_friction")
            markers.append(
                _make_issue_marker(
                    event_id=f"retries-{session.id}",
                    event_type="retries",
                    created_at=session.updated_at or session.created_at,
                    tool_name=top_failed_tool,
                    tags=retry_tags,
                    root_causes=retry_root_causes,
                    title=f"{top_failed_tool or 'The workflow'} kept repeating the same step",
                    summary="The run had to retry the same step before it could continue.",
                    detail="The run had to retry the same step before it could continue.",
                    fingerprint=retry_fingerprint,
                )
            )
            had_issue = True

    _append_summary_marker_if_needed(session, markers, seen_fingerprints)

    for marker in markers:
        tags.update(marker.tags)
        root_causes.update(marker.root_causes)

    if markers:
        tags.add("friction")
    if saw_success_after_issue and session.status == "completed":
        tags.add("recovered")

    if tags and not root_causes:
        root_causes.add(_fallback_root_cause(tags) or "unknown")

    summary_parts = [marker.summary for marker in markers[:2]]
    if "recovered" in tags:
        summary_parts.append("Recovered before completion.")

    return SessionPulse(
        issue_markers=markers,
        tags=sorted(tags, key=lambda item: _FILTERABLE_TAGS.index(item) if item in _FILTERABLE_TAGS else 99),
        primary_tag=_primary_value(tags, _TAG_PRIORITY),
        root_causes=sorted(root_causes, key=lambda item: _ROOT_CAUSE_PRIORITY.index(item) if item in _ROOT_CAUSE_PRIORITY else 99),
        primary_root_cause=_primary_value(root_causes, _ROOT_CAUSE_PRIORITY),
        summary=" ".join(dict.fromkeys(summary_parts)) or None,
    )


def build_session_pulses(
    sessions: list[Session],
    previews_by_session_id: dict[str, list[PersonaStreamEventPreview]],
) -> dict[str, SessionPulse]:
    return {
        session.id: classify_session_pulse(session, previews_by_session_id.get(session.id, []))
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
    issue_groups: dict[str, list[tuple[Session, PersonaIssueMarker, PersonaStreamEntry]]] = defaultdict(list)
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
        entry = entry_by_session_id.get(session.id)
        if entry is None:
            continue
        for marker in pulse.issue_markers:
            if marker.fingerprint:
                issue_groups[marker.fingerprint].append((session, marker, entry))

    metrics = [
        PersonaPulseMetric(
            key="friction",
            label="Friction",
            count=metric_counts["friction"],
            description="Runs with issue markers worth reviewing in the current history window.",
        ),
        PersonaPulseMetric(
            key="error",
            label="Errors",
            count=metric_counts["error"],
            description="Runs with explicit failures, crashes, or non-zero tool outcomes.",
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
            description="Runs that waited on missing context, follow-up, or recent activity.",
        ),
        PersonaPulseMetric(
            key="instruction_drift",
            label="Instruction Drift",
            count=metric_counts["instruction_drift"],
            description="Runs that bypassed the intended workflow or used the wrong command path.",
        ),
        PersonaPulseMetric(
            key="tool_friction",
            label="Tool Friction",
            count=metric_counts["tool_friction"],
            description="Runs where tool use itself caused avoidable drag or failure.",
        ),
        PersonaPulseMetric(
            key="retries",
            label="Retries",
            count=metric_counts["retries"],
            description="Runs that had to repeat the same step before they could continue.",
        ),
        PersonaPulseMetric(
            key="recovered",
            label="Recovered",
            count=metric_counts["recovered"],
            description="Runs that hit trouble but still completed after the issue was resolved.",
        ),
        PersonaPulseMetric(
            key="escalation",
            label="Escalations",
            count=metric_counts["escalation"],
            description="Runs that needed a human review, approval, or manual follow-up.",
        ),
    ]

    grouped_issues: list[PersonaIssueGroup] = []
    for fingerprint, group in issue_groups.items():
        latest_session, latest_marker, latest_entry = max(group, key=lambda item: item[1].created_at)
        grouped_issues.append(
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
