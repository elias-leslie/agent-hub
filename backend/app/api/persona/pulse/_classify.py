"""Core session-pulse classification logic."""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from app.api.persona.schemas import PersonaIssueMarker, PersonaStreamEventPreview
from app.models.session import Session

from ._constants import (
    CONTEXT_TERMS,
    ERROR_TERMS,
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


def _append_stalled_marker(
    session: Session,
    markers: list[PersonaIssueMarker],
    seen_fingerprints: set[str],
) -> bool:
    """Add a stalled marker if the active session hasn't updated recently. Returns True if added."""
    if session.status != "active" or not session.updated_at:
        return False
    if datetime.now(UTC) - session.updated_at <= timedelta(minutes=20):
        return False

    fp = "stalled:context"
    if fp in seen_fingerprints:
        return False
    seen_fingerprints.add(fp)
    markers.append(
        make_issue_marker(
            event_id=f"stalled-{session.id}",
            event_type="stalled",
            created_at=session.updated_at,
            tool_name=None,
            tags={"stalled"},
            root_causes={"context"},
            title="Work stalled waiting on context or follow-up",
            summary="The run has remained active without a recent update.",
            detail="The run has remained active without a recent update.",
            fingerprint=fp,
        )
    )
    return True


def _append_retry_marker(
    session: Session,
    markers: list[PersonaIssueMarker],
    seen_fingerprints: set[str],
    tool_failure_counts: Counter[str],
    tool_failure_labels: dict[str, str],
    explicit_retry_signal: bool,
) -> bool:
    """Add a retry marker if retries were detected. Returns True if added."""
    if not explicit_retry_signal and not any(count > 1 for count in tool_failure_counts.values()):
        return False

    top_failure_key = tool_failure_counts.most_common(1)[0][0] if tool_failure_counts else None
    top_failed_tool = (
        tool_failure_labels.get(top_failure_key, top_failure_key)
        if top_failure_key
        else None
    )
    fp = f"retries:{normalize_issue_key(top_failure_key or top_failed_tool or session.agent_slug or session.id)}"
    if fp in seen_fingerprints:
        return False
    seen_fingerprints.add(fp)

    retry_tags: set[str] = {"retries"}
    retry_root_causes: set[str] = {"tool" if top_failed_tool else "workflow"}
    if top_failed_tool:
        retry_tags.add("tool_friction")

    markers.append(
        make_issue_marker(
            event_id=f"retries-{session.id}",
            event_type="retries",
            created_at=session.updated_at or session.created_at,
            tool_name=top_failed_tool,
            tags=retry_tags,
            root_causes=retry_root_causes,
            title=f"{top_failed_tool or 'The workflow'} kept repeating the same step",
            summary="The run had to retry the same step before it could continue.",
            detail="The run had to retry the same step before it could continue.",
            fingerprint=fp,
        )
    )
    return True


def _tool_failure_key(preview_item: PersonaStreamEventPreview, command: str | None) -> str | None:
    """Return a retry-fingerprint key that distinguishes distinct tool steps."""
    def _normalize_retry_detail(value: str) -> str:
        lowered = value.lower()
        lowered = re.sub(r"\b[0-9]+\b", "#", lowered)
        lowered = re.sub(r"[^a-z0-9]+", "-", lowered)
        return lowered.strip("-")[:160]

    tool_name = preview_item.tool_name
    if not tool_name:
        return None

    detail = command or preview_item.tool_input_preview
    normalized_tool = normalize_issue_key(tool_name)
    normalized_detail = _normalize_retry_detail(detail) if detail else ""
    if normalized_detail:
        return f"{normalized_tool}:{normalized_detail}"
    return normalized_tool


def _append_summary_marker_if_needed(
    session: Session,
    markers: list[PersonaIssueMarker],
    seen_fingerprints: set[str],
) -> None:
    if markers:
        return
    summary_text = (session.summary_oneliner or "").strip()
    if not summary_text:
        return

    lowered = summary_text.lower()
    tags: set[str] = set()
    root_causes: set[str] = set()

    if contains_any(lowered, ERROR_TERMS):
        tags.update({"error", "tool_friction"})
        root_causes.add("tool")
    if contains_any(lowered, WARNING_TERMS):
        tags.add("warning")
    if contains_any(lowered, STALLED_TERMS):
        tags.add("stalled")
        root_causes.add("context")
    if contains_any(lowered, ESCALATION_TERMS):
        tags.add("escalation")
    if not tags:
        return

    root_causes.add(fallback_root_cause(tags) or "unknown")
    dummy_preview = PersonaStreamEventPreview(
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
    )
    title = build_marker_title(dummy_preview, tags, None)
    fingerprint = build_fingerprint(
        dummy_preview, tags, primary_value(root_causes, ROOT_CAUSE_PRIORITY), None,
    )
    dedupe_key = fingerprint or f"summary-{session.id}"
    if dedupe_key in seen_fingerprints:
        return
    seen_fingerprints.add(dedupe_key)

    markers.append(
        make_issue_marker(
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
    all_root_causes: set[str] = set()
    all_tags: set[str] = set()
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

        # Track tool failures for retry detection
        if "error" in marker_tags and preview_item.tool_name:
            failure_key = _tool_failure_key(preview_item, command) or preview_item.tool_name
            tool_failure_counts[failure_key] += 1
            tool_failure_labels.setdefault(failure_key, preview_item.tool_name)
        if "retries" in marker_tags:
            explicit_retry_signal = True

        if marker_tags:
            had_issue = True
            if "error" in marker_tags:
                had_error = True

        if preview_has_success(preview_item, text) and (had_error or had_issue):
            saw_success_after_issue = True

        if not marker_tags:
            continue

        marker_root_causes.add(fallback_root_cause(marker_tags) or "unknown")
        primary_rc = primary_value(marker_root_causes, ROOT_CAUSE_PRIORITY)
        title = build_marker_title(preview_item, marker_tags, raw_rule)
        summary = build_marker_summary(preview_item, marker_tags, title, excerpt)
        detail = build_marker_detail(preview_item, excerpt, command) or summary
        fingerprint = build_fingerprint(preview_item, marker_tags, primary_rc, raw_rule)
        dedupe_key = fingerprint or f"{preview_item.id}:{primary_value(marker_tags, TAG_PRIORITY)}"
        if dedupe_key in seen_fingerprints:
            continue
        seen_fingerprints.add(dedupe_key)
        markers.append(
            make_issue_marker(
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
        )

    if _append_stalled_marker(session, markers, seen_fingerprints):
        had_issue = True
    if _append_retry_marker(
        session,
        markers,
        seen_fingerprints,
        tool_failure_counts,
        tool_failure_labels,
        explicit_retry_signal,
    ):
        had_issue = True

    _append_summary_marker_if_needed(session, markers, seen_fingerprints)

    for marker in markers:
        all_tags.update(marker.tags)
        all_root_causes.update(marker.root_causes)

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


def build_session_pulses(
    sessions: list[Session],
    previews_by_session_id: dict[str, list[PersonaStreamEventPreview]],
) -> dict[str, SessionPulse]:
    return {
        session.id: classify_session_pulse(session, previews_by_session_id.get(session.id, []))
        for session in sessions
    }
