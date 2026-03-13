"""Memory utilization analytics derived from session and injection events."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import Text, func, or_, select

from app.db import async_session
from app.models import MemoryInjectionMetric, Session, SessionEvent, SessionEventType

from .analytics_models import MemoryUtilizationMetrics


@dataclass(frozen=True)
class _LookupEvent:
    """Memory lookup command observed in session events."""

    session_id: str
    created_at: datetime
    command_kind: str


def _rate(numerator: int, denominator: int) -> float:
    """Return a stable rounded ratio."""
    if denominator <= 0:
        return 0.0
    return round(numerator / denominator, 3)


def _has_memory_debug(tool_input: dict[str, Any] | None) -> bool:
    """Treat non-empty memory_debug payloads as usable observability."""
    if not isinstance(tool_input, dict):
        return False
    memory_debug = tool_input.get("memory_debug")
    return isinstance(memory_debug, dict) and bool(memory_debug)


def _extract_memory_command_kind(tool_input: dict[str, Any] | None) -> str | None:
    """Classify supported memory lookup commands from tool input payloads."""
    if not isinstance(tool_input, dict):
        return None
    command = tool_input.get("cmd") or tool_input.get("command")
    if not isinstance(command, str):
        return None
    if command.startswith("st memory search"):
        return "search"
    if command.startswith("st memory get"):
        return "get"
    return None


def _build_memory_utilization_metrics(
    *,
    injection_session_ids: set[str],
    citation_session_ids: set[str],
    lookup_events: list[_LookupEvent],
    first_injection_at: dict[str, datetime],
    assistant_message_count: int,
    assistant_messages_with_memory_citations: int,
    selected_reference_count: int,
    selected_reference_cited_count: int,
    sessions_with_selected_references: int,
    sessions_with_cited_selected_references: int,
    memory_inject_event_count: int,
    memory_inject_events_with_debug: int,
) -> MemoryUtilizationMetrics:
    """Build the memory utilization summary from normalized event aggregates."""
    lookup_session_ids = {event.session_id for event in lookup_events}
    lookup_in_injected_sessions = lookup_session_ids & injection_session_ids
    lookup_after_injection_sessions = {
        event.session_id
        for event in lookup_events
        if (injected_at := first_injection_at.get(event.session_id)) is not None
        and event.created_at >= injected_at
    }
    memory_search_calls = sum(1 for event in lookup_events if event.command_kind == "search")
    memory_get_calls = sum(1 for event in lookup_events if event.command_kind == "get")

    injection_sessions = len(injection_session_ids)
    citation_sessions = len(citation_session_ids & injection_session_ids)

    return MemoryUtilizationMetrics(
        injection_sessions=injection_sessions,
        citation_sessions=citation_sessions,
        lookup_sessions=len(lookup_session_ids),
        lookup_after_injection_sessions=len(lookup_after_injection_sessions),
        memory_search_calls=memory_search_calls,
        memory_get_calls=memory_get_calls,
        assistant_message_count=assistant_message_count,
        assistant_messages_with_memory_citations=assistant_messages_with_memory_citations,
        citation_session_rate=_rate(citation_sessions, injection_sessions),
        lookup_session_rate=_rate(len(lookup_in_injected_sessions), injection_sessions),
        expansion_session_rate=_rate(len(lookup_after_injection_sessions), injection_sessions),
        assistant_citation_rate=_rate(
            assistant_messages_with_memory_citations,
            assistant_message_count,
        ),
        sessions_with_selected_references=sessions_with_selected_references,
        sessions_with_cited_selected_references=sessions_with_cited_selected_references,
        selected_reference_count=selected_reference_count,
        selected_reference_cited_count=selected_reference_cited_count,
        selected_reference_citation_rate=_rate(
            selected_reference_cited_count,
            selected_reference_count,
        ),
        selected_reference_session_rate=_rate(
            sessions_with_cited_selected_references,
            sessions_with_selected_references,
        ),
        memory_inject_event_count=memory_inject_event_count,
        memory_inject_events_with_debug=memory_inject_events_with_debug,
        memory_debug_coverage_rate=_rate(
            memory_inject_events_with_debug,
            memory_inject_event_count,
        ),
    )


async def get_memory_utilization_summary(
    lookback_delta: timedelta,
    *,
    project_id_filter: str | None = None,
) -> MemoryUtilizationMetrics:
    """Return recent evidence that agents are expanding and citing injected memory."""
    cutoff = datetime.now(UTC) - lookback_delta
    tool_input_text = SessionEvent.tool_input.cast(Text)
    tool_use_filters = or_(
        tool_input_text.like("%st memory search%"),
        tool_input_text.like("%st memory get%"),
    )

    injection_stmt = (
        select(SessionEvent.session_id, SessionEvent.created_at, SessionEvent.tool_input)
        .where(
            SessionEvent.event_type == SessionEventType.MEMORY_INJECT,
            SessionEvent.created_at >= cutoff,
        )
        .order_by(SessionEvent.session_id, SessionEvent.created_at)
    )
    citation_stmt = select(SessionEvent.session_id).where(
        SessionEvent.event_type == SessionEventType.MEMORY_CITE,
        SessionEvent.created_at >= cutoff,
    )
    lookup_stmt = (
        select(SessionEvent.session_id, SessionEvent.created_at, SessionEvent.tool_input)
        .where(
            SessionEvent.event_type == SessionEventType.TOOL_USE,
            SessionEvent.created_at >= cutoff,
            tool_use_filters,
        )
        .order_by(SessionEvent.session_id, SessionEvent.created_at)
    )
    assistant_stmt = select(
        func.count().label("assistant_total"),
        func.count()
        .filter(
            or_(
                SessionEvent.content.like("%[M:%"),
                SessionEvent.content.like("%[G:%"),
                SessionEvent.content.like("%[R:%"),
            )
        )
        .label("assistant_with_citations"),
    ).where(
        SessionEvent.event_type == SessionEventType.ASSISTANT_MESSAGE,
        SessionEvent.created_at >= cutoff,
    )
    reference_stmt = select(
        func.coalesce(func.sum(MemoryInjectionMetric.reference_selected_count), 0),
        func.coalesce(func.sum(MemoryInjectionMetric.reference_cited_count), 0),
        func.count(func.distinct(MemoryInjectionMetric.session_id)).filter(
            MemoryInjectionMetric.reference_selected_count > 0
        ),
        func.count(func.distinct(MemoryInjectionMetric.session_id)).filter(
            MemoryInjectionMetric.reference_cited_count > 0
        ),
    ).where(MemoryInjectionMetric.created_at >= cutoff)

    if project_id_filter:
        injection_stmt = injection_stmt.join(Session, Session.id == SessionEvent.session_id).where(
            Session.project_id == project_id_filter
        )
        citation_stmt = citation_stmt.join(Session, Session.id == SessionEvent.session_id).where(
            Session.project_id == project_id_filter
        )
        lookup_stmt = lookup_stmt.join(Session, Session.id == SessionEvent.session_id).where(
            Session.project_id == project_id_filter
        )
        assistant_stmt = assistant_stmt.join(Session, Session.id == SessionEvent.session_id).where(
            Session.project_id == project_id_filter
        )
        reference_stmt = reference_stmt.where(MemoryInjectionMetric.project_id == project_id_filter)

    async with async_session() as session:
        injection_rows = (await session.execute(injection_stmt)).all()
        citation_rows = (await session.execute(citation_stmt)).all()
        lookup_rows = (await session.execute(lookup_stmt)).all()
        assistant_counts = (await session.execute(assistant_stmt)).one()
        reference_counts = (await session.execute(reference_stmt)).one()

    injection_session_ids: set[str] = set()
    first_injection_at: dict[str, datetime] = {}
    memory_inject_events_with_debug = 0
    for session_id, created_at, tool_input in injection_rows:
        injection_session_ids.add(session_id)
        first_seen = first_injection_at.get(session_id)
        if first_seen is None or created_at < first_seen:
            first_injection_at[session_id] = created_at
        if _has_memory_debug(tool_input):
            memory_inject_events_with_debug += 1

    citation_session_ids = {session_id for (session_id,) in citation_rows}
    lookup_events = [
        _LookupEvent(session_id=session_id, created_at=created_at, command_kind=command_kind)
        for session_id, created_at, tool_input in lookup_rows
        if (command_kind := _extract_memory_command_kind(tool_input)) is not None
    ]

    assistant_total = int(assistant_counts.assistant_total or 0)
    assistant_with_citations = int(assistant_counts.assistant_with_citations or 0)
    selected_reference_count = int(reference_counts[0] or 0)
    selected_reference_cited_count = int(reference_counts[1] or 0)
    sessions_with_selected_references = int(reference_counts[2] or 0)
    sessions_with_cited_selected_references = int(reference_counts[3] or 0)

    return _build_memory_utilization_metrics(
        injection_session_ids=injection_session_ids,
        citation_session_ids=citation_session_ids,
        lookup_events=lookup_events,
        first_injection_at=first_injection_at,
        assistant_message_count=assistant_total,
        assistant_messages_with_memory_citations=assistant_with_citations,
        selected_reference_count=selected_reference_count,
        selected_reference_cited_count=selected_reference_cited_count,
        sessions_with_selected_references=sessions_with_selected_references,
        sessions_with_cited_selected_references=sessions_with_cited_selected_references,
        memory_inject_event_count=len(injection_rows),
        memory_inject_events_with_debug=memory_inject_events_with_debug,
    )
