"""Core session-pulse classification logic."""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

from app.api.persona.schemas import PersonaIssueMarker, PersonaStreamEventPreview
from app.models.session import Session

from ._constants import (
    CONTEXT_TERMS,
    ESCALATION_TERMS,
    FILTERABLE_TAGS,
    INFRA_TERMS,
    PROMPT_TERMS,
    ROOT_CAUSE_PRIORITY,
    STALLED_TERMS,
    TAG_PRIORITY,
    TOOL_FRICTION_TERMS,
    WARNING_TERMS,
)
from ._marker_builders import (
    append_retry_marker,
    append_stalled_marker,
    append_summary_marker_if_needed,
)
from ._markers import (
    build_fingerprint,
    build_marker_detail,
    build_marker_summary,
    build_marker_title,
    fallback_root_cause,
    make_issue_marker,
)
from ._text_helpers import (
    contains_any,
    extract_command,
    first_matching_rule,
    human_preview_text,
    normalize_issue_key,
    preview_has_error,
    preview_has_success,
    preview_text,
    primary_value,
    should_ignore_preview,
)


@dataclass(slots=True)
class SessionPulse:
    issue_markers: list[PersonaIssueMarker] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    primary_tag: str | None = None
    root_causes: list[str] = field(default_factory=list)
    primary_root_cause: str | None = None
    summary: str | None = None


def _tag_sort_key(item: str) -> int:
    return FILTERABLE_TAGS.index(item) if item in FILTERABLE_TAGS else 99


def _root_cause_sort_key(item: str) -> int:
    return ROOT_CAUSE_PRIORITY.index(item) if item in ROOT_CAUSE_PRIORITY else 99


def _classify_preview_tags(
    preview: PersonaStreamEventPreview,
    text: str,
    command: str | None,
    raw_command_rule: tuple[str, str, str] | None,
) -> tuple[set[str], set[str]]:
    """Return (marker_tags, marker_root_causes) for a single preview."""
    tags: set[str] = set()
    root_causes: set[str] = set()

    if raw_command_rule:
        tags.add("instruction_drift")
        root_causes.add(raw_command_rule[1])
    if contains_any(text, CONTEXT_TERMS):
        root_causes.add("context")
    if contains_any(text, INFRA_TERMS):
        root_causes.add("infra")
    if contains_any(text, PROMPT_TERMS) and "instruction_drift" in tags:
        root_causes.add("prompt")
    if preview_has_error(preview, text):
        tags.update({"error", "tool_friction"})
        if contains_any(text, TOOL_FRICTION_TERMS):
            root_causes.add("tool")
    if contains_any(text, WARNING_TERMS):
        tags.add("warning")
    if contains_any(text, STALLED_TERMS):
        tags.add("stalled")
    if contains_any(text, ESCALATION_TERMS):
        tags.add("escalation")
    if contains_any(text, TOOL_FRICTION_TERMS):
        tags.add("tool_friction")
        root_causes.add("tool")
    if contains_any(text, ("retry", "retried", "retrying")):
        tags.add("retries")

    return tags, root_causes


def _tool_failure_key(preview_item: PersonaStreamEventPreview, command: str | None) -> str | None:
    """Return a retry-fingerprint key that distinguishes distinct tool steps."""
    def _normalize(value: str) -> str:
        lowered = re.sub(r"\b[0-9]+\b", "#", value.lower())
        return re.sub(r"[^a-z0-9]+", "-", lowered).strip("-")[:160]

    if not preview_item.tool_name:
        return None
    detail = command or preview_item.tool_input_preview
    normalized_tool = normalize_issue_key(preview_item.tool_name)
    normalized_detail = _normalize(detail) if detail else ""
    return f"{normalized_tool}:{normalized_detail}" if normalized_detail else normalized_tool


def _build_preview_marker(
    preview_item: PersonaStreamEventPreview,
    marker_tags: set[str],
    marker_root_causes: set[str],
    raw_rule: tuple[str, str, str] | None,
    excerpt: str | None,
    command: str | None,
    seen_fingerprints: set[str],
) -> PersonaIssueMarker | None:
    """Build and deduplicate a single issue marker. Returns None if already seen."""
    marker_root_causes.add(fallback_root_cause(marker_tags) or "unknown")
    primary_rc = primary_value(marker_root_causes, ROOT_CAUSE_PRIORITY)
    title = build_marker_title(preview_item, marker_tags, raw_rule)
    summary = build_marker_summary(preview_item, marker_tags, title, excerpt)
    detail = build_marker_detail(preview_item, excerpt, command) or summary
    fingerprint = build_fingerprint(preview_item, marker_tags, primary_rc, raw_rule)
    dedupe_key = fingerprint or f"{preview_item.id}:{primary_value(marker_tags, TAG_PRIORITY)}"
    if dedupe_key in seen_fingerprints:
        return None
    seen_fingerprints.add(dedupe_key)
    return make_issue_marker(
        event_id=preview_item.id,
        event_type=preview_item.event_type,
        created_at=preview_item.created_at,
        tool_name=preview_item.tool_name,
        tags=marker_tags,
        root_causes=marker_root_causes,
        title=title,
        summary=summary,
        detail=detail,
        fingerprint=fingerprint,
    )


def _assemble_pulse(
    session: Session,
    markers: list[PersonaIssueMarker],
    all_tags: set[str],
    all_root_causes: set[str],
    saw_success_after_issue: bool,
) -> SessionPulse:
    """Combine accumulated markers and tags into the final SessionPulse."""
    if markers:
        all_tags.add("friction")
    if saw_success_after_issue and session.status == "completed":
        all_tags.add("recovered")
    if all_tags and not all_root_causes:
        all_root_causes.add(fallback_root_cause(all_tags) or "unknown")

    summary_parts = [marker.summary for marker in markers[:2]]
    if "recovered" in all_tags:
        summary_parts.append("Recovered before completion.")

    return SessionPulse(
        issue_markers=markers,
        tags=sorted(all_tags, key=_tag_sort_key),
        primary_tag=primary_value(all_tags, TAG_PRIORITY),
        root_causes=sorted(all_root_causes, key=_root_cause_sort_key),
        primary_root_cause=primary_value(all_root_causes, ROOT_CAUSE_PRIORITY),
        summary=" ".join(dict.fromkeys(summary_parts)) or None,
    )


def _update_retry_state(
    preview_item: PersonaStreamEventPreview,
    marker_tags: set[str],
    command: str | None,
    tool_failure_counts: Counter[str],
    tool_failure_labels: dict[str, str],
) -> bool:
    """Track tool failures; return True if an explicit retry signal was found."""
    if "error" in marker_tags and preview_item.tool_name:
        failure_key = _tool_failure_key(preview_item, command) or preview_item.tool_name
        tool_failure_counts[failure_key] += 1
        tool_failure_labels.setdefault(failure_key, preview_item.tool_name)
    return "retries" in marker_tags


def _collect_markers(
    session: Session, previews: list[PersonaStreamEventPreview]
) -> tuple[list[PersonaIssueMarker], bool]:
    """Process previews, build markers, append synthetic markers. Returns (markers, saw_success_after_issue)."""
    markers: list[PersonaIssueMarker] = []
    seen_fingerprints: set[str] = set()
    tool_failure_counts: Counter[str] = Counter()
    tool_failure_labels: dict[str, str] = {}
    explicit_retry_signal = False
    had_issue = False
    had_error = session.status == "failed"
    saw_success_after_issue = False

    for preview_item in sorted(previews, key=lambda p: p.created_at):
        text = preview_text(preview_item)
        if should_ignore_preview(preview_item, text):
            continue
        excerpt = human_preview_text(preview_item)
        command = extract_command(preview_item)
        raw_rule = first_matching_rule(command) if command else None
        marker_tags, marker_root_causes = _classify_preview_tags(preview_item, text, command, raw_rule)

        if _update_retry_state(preview_item, marker_tags, command, tool_failure_counts, tool_failure_labels):
            explicit_retry_signal = True
        if marker_tags:
            had_issue = True
            had_error = had_error or "error" in marker_tags
        if preview_has_success(preview_item, text) and (had_error or had_issue):
            saw_success_after_issue = True
        if not marker_tags:
            continue
        marker = _build_preview_marker(
            preview_item, marker_tags, marker_root_causes, raw_rule, excerpt, command, seen_fingerprints,
        )
        if marker:
            markers.append(marker)

    if append_stalled_marker(session, markers, seen_fingerprints):
        had_issue = True
    if append_retry_marker(
        session, markers, seen_fingerprints, tool_failure_counts, tool_failure_labels, explicit_retry_signal,
    ):
        had_issue = True
    append_summary_marker_if_needed(session, markers, seen_fingerprints)
    return markers, saw_success_after_issue


def classify_session_pulse(session: Session, previews: list[PersonaStreamEventPreview]) -> SessionPulse:
    markers, saw_success_after_issue = _collect_markers(session, previews)
    all_tags: set[str] = set()
    all_root_causes: set[str] = set()
    for marker in markers:
        all_tags.update(marker.tags)
        all_root_causes.update(marker.root_causes)
    return _assemble_pulse(session, markers, all_tags, all_root_causes, saw_success_after_issue)


def build_session_pulses(
    sessions: list[Session],
    previews_by_session_id: dict[str, list[PersonaStreamEventPreview]],
) -> dict[str, SessionPulse]:
    return {
        session.id: classify_session_pulse(session, previews_by_session_id.get(session.id, []))
        for session in sessions
    }
