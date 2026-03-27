"""Functions that build and append specialised issue markers to a pulse."""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime, timedelta

from app.api.persona.schemas import PersonaIssueMarker, PersonaStreamEventPreview
from app.models.session import Session

from ._constants import (
    ERROR_TERMS,
    ESCALATION_TERMS,
    ROOT_CAUSE_PRIORITY,
    STALLED_TERMS,
    WARNING_TERMS,
)
from ._markers import (
    build_fingerprint,
    build_marker_title,
    fallback_root_cause,
    make_issue_marker,
)
from ._text_helpers import (
    contains_any,
    normalize_issue_key,
    primary_value,
)


def append_stalled_marker(
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


def append_retry_marker(
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


def _summary_marker_tags(lowered: str) -> tuple[set[str], set[str]]:
    """Return (tags, root_causes) derived from a session summary string."""
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

    return tags, root_causes


def _make_summary_preview(session: Session, summary_text: str) -> PersonaStreamEventPreview:
    return PersonaStreamEventPreview(
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


def append_summary_marker_if_needed(
    session: Session,
    markers: list[PersonaIssueMarker],
    seen_fingerprints: set[str],
) -> None:
    """If no markers exist yet, try to synthesise one from the session summary."""
    if markers:
        return
    summary_text = (session.summary_oneliner or "").strip()
    if not summary_text:
        return

    tags, root_causes = _summary_marker_tags(summary_text.lower())
    if not tags:
        return

    root_causes.add(fallback_root_cause(tags) or "unknown")
    dummy_preview = _make_summary_preview(session, summary_text)
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
