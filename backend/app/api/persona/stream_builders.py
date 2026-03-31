"""Entry and preview builders for the persona stream."""

from __future__ import annotations

import json
from typing import Any

from app.models.session import Session, SessionEvent

from .schemas import PersonaStreamEntry, PersonaStreamEventPreview

_ISSUE_SIGNAL_TERMS = (
    "error",
    "failed",
    "failure",
    "warning",
    "blocked",
    "stalled",
    "waiting",
    "retry",
    "retried",
    "permission denied",
    "timed out",
    "timeout",
    "not found",
    "missing",
    "interrupted",
)


def _stringify_preview(value: Any, *, limit: int | None = 280) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        text = value
    else:
        try:
            text = json.dumps(value, ensure_ascii=True, sort_keys=True)
        except TypeError:
            text = str(value)
    if limit is None or len(text) <= limit:
        return text
    return f"{text[: limit - 1]}…"


def _live_activity_summary(session: Session) -> tuple[str | None, str | None, str | None]:
    metadata = session.provider_metadata if isinstance(session.provider_metadata, dict) else {}
    live_activity = metadata.get("live_activity")
    if not isinstance(live_activity, dict):
        return None, None, None
    summary = live_activity.get("summary")
    status = live_activity.get("status")
    topic = live_activity.get("current_topic") or live_activity.get("last_topic")
    return (
        summary if isinstance(summary, str) else None,
        status if isinstance(status, str) else None,
        topic if isinstance(topic, str) else None,
    )


def _event_has_issue_signal(event: SessionEvent) -> bool:
    if event.event_type == "error":
        return True
    combined = " ".join(
        part
        for part in [
            _stringify_preview(event.content, limit=None),
            _stringify_preview(event.tool_input, limit=None),
            _stringify_preview(event.tool_output, limit=None),
            event.tool_name,
            event.role,
        ]
        if isinstance(part, str) and part
    ).lower()
    return any(term in combined for term in _ISSUE_SIGNAL_TERMS)


def _pulse_fields(pulse: Any) -> dict[str, Any]:
    """Return pulse-related kwargs for PersonaStreamEntry (empty defaults when pulse is None)."""
    return {
        "issue_markers": pulse.issue_markers if pulse else [],
        "pulse_tags": pulse.tags if pulse else [],
        "primary_pulse_tag": pulse.primary_tag if pulse else None,
        "root_causes": pulse.root_causes if pulse else [],
        "primary_root_cause": pulse.primary_root_cause if pulse else None,
        "pulse_summary": pulse.summary if pulse else None,
    }


def _make_session_entry(
    entry_id: str,
    entry_type: str,
    session: Session,
    *,
    message_counts: dict[str, int],
    tool_counts: dict[str, int],
    event_previews: dict[str, list[PersonaStreamEventPreview]],
    session_pulses: dict[str, Any],
    display_summaries: dict[str, str | None] | None = None,
    session_type_override: str | None = None,
) -> PersonaStreamEntry:
    live_summary, live_status, live_topic = _live_activity_summary(session)
    pulse = session_pulses.get(session.id)
    display_summaries = display_summaries or {}
    return PersonaStreamEntry(
        id=entry_id,
        entry_type=entry_type,
        timestamp=session.created_at,
        session_id=session.id,
        parent_session_id=session.parent_session_id,
        project_id=session.project_id,
        agent_slug=session.agent_slug,
        session_type=session_type_override or session.session_type,
        status=session.status,
        summary_oneliner=session.summary_oneliner,
        display_summary=display_summaries.get(session.id),
        current_branch=session.current_branch,
        external_id=session.external_id,
        model=session.model,
        live_summary=live_summary,
        live_status=live_status,
        live_topic=live_topic,
        message_count=message_counts.get(session.id, 0),
        tool_count=tool_counts.get(session.id, 0),
        event_previews=event_previews.get(session.id, []),
        **_pulse_fields(pulse),
    )


def _make_message_entry(
    event: SessionEvent,
    session: Session,
    message_counts: dict[str, int],
    tool_counts: dict[str, int],
) -> PersonaStreamEntry:
    return PersonaStreamEntry(
        id=event.id,
        entry_type="message",
        timestamp=event.created_at,
        session_id=session.id,
        parent_session_id=session.parent_session_id,
        project_id=session.project_id,
        agent_slug=session.agent_slug,
        session_type=session.session_type,
        status=session.status,
        role=event.role,
        content=event.content,
        current_branch=session.current_branch,
        external_id=session.external_id,
        model=event.model_used or session.model,
        message_count=message_counts.get(session.id, 0),
        tool_count=tool_counts.get(session.id, 0),
    )


def _build_stream_entries(
    persona_sessions: list[Session],
    child_sessions: list[Session],
    message_events: list[SessionEvent],
    message_counts: dict[str, int],
    tool_counts: dict[str, int],
    event_previews: dict[str, list[PersonaStreamEventPreview]],
    session_pulses: dict[str, Any] | None = None,
    display_summaries: dict[str, str | None] | None = None,
) -> list[PersonaStreamEntry]:
    persona_by_id = {session.id: session for session in persona_sessions}
    session_pulses = session_pulses or {}
    display_summaries = display_summaries or {}
    entries: list[PersonaStreamEntry] = []

    for event in message_events:
        session = persona_by_id.get(event.session_id)
        if session is not None:
            entries.append(_make_message_entry(event, session, message_counts, tool_counts))

    session_entry_kwargs = dict(
        message_counts=message_counts,
        tool_counts=tool_counts,
        event_previews=event_previews,
        session_pulses=session_pulses,
        display_summaries=display_summaries,
    )
    for session in persona_sessions:
        if session.session_type == "chat":
            continue
        session_type = "heartbeat" if session.project_id == "persona-sandbox" else session.session_type
        entries.append(_make_session_entry(f"session-{session.id}", "heartbeat", session, session_type_override=session_type, **session_entry_kwargs))

    for session in child_sessions:
        entries.append(_make_session_entry(f"child-{session.id}", "child_run", session, **session_entry_kwargs))

    entries.sort(key=lambda entry: entry.timestamp, reverse=True)
    return entries
