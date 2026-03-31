"""ORM query builders for the persona stream endpoint."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import Select, String, and_, cast, or_, select

from app.models.session import Session, SessionEvent

from .stream_search import ParsedSearch

_SEARCHABLE_EVENT_TYPES = (
    "user_message",
    "assistant_message",
    "thinking",
    "tool_use",
    "tool_result",
    "error",
)

# Each entry: (term_list, [Session columns to ilike-match])
# File terms only match via events; all others also match additional columns.
_SEARCH_TERM_COLUMNS: list[tuple[str, list[Any]]] = [
    ("general_terms", [Session.summary_oneliner, Session.project_id, Session.agent_slug, Session.external_id, Session.current_branch]),
    ("task_terms", [Session.external_id, Session.summary_oneliner]),
    ("file_terms", []),
    ("agent_terms", [Session.agent_slug, Session.summary_oneliner]),
    ("status_terms", [cast(Session.status, String), Session.summary_oneliner]),
    ("project_terms", [Session.project_id, Session.current_branch, Session.summary_oneliner]),
    ("topic_terms", [cast(Session.provider_metadata, String), Session.external_id, Session.summary_oneliner]),
]


def _apply_since(query: Select, hours: int) -> Select:
    if hours <= 0:
        return query
    since = datetime.now(UTC) - timedelta(hours=hours)
    return query.where(Session.created_at >= since)


def _event_match_predicate(term: str) -> Any:
    wildcard = f"%{term}%"
    return (
        select(SessionEvent.id)
        .where(
            SessionEvent.session_id == Session.id,
            SessionEvent.event_type.in_(_SEARCHABLE_EVENT_TYPES),
            or_(
                SessionEvent.content.ilike(wildcard),
                SessionEvent.tool_name.ilike(wildcard),
                cast(SessionEvent.tool_input, String).ilike(wildcard),
                cast(SessionEvent.tool_output, String).ilike(wildcard),
            ),
        )
        .correlate(Session)
        .exists()
    )


def _session_search_predicates(parsed_search: ParsedSearch) -> list[Any]:
    predicates: list[Any] = []
    for attr, columns in _SEARCH_TERM_COLUMNS:
        for term in getattr(parsed_search, attr):
            wildcard = f"%{term}%"
            col_clauses = [col.ilike(wildcard) for col in columns]
            predicates.append(or_(*col_clauses, _event_match_predicate(term)))
    return predicates


def _persona_session_query(hours: int, parsed_search: ParsedSearch | None) -> Select:
    has_events = (
        select(SessionEvent.session_id)
        .where(SessionEvent.session_id == Session.id)
        .correlate(Session)
        .exists()
    )
    query = select(Session).where(Session.agent_slug == "persona", has_events)
    query = _apply_since(query, hours)
    if parsed_search and parsed_search.has_terms():
        query = query.where(and_(*_session_search_predicates(parsed_search)))
    return query


def _child_session_query(persona_session_ids: Iterable[str], hours: int, parsed_search: ParsedSearch | None) -> Select:
    ids = list(persona_session_ids)
    query = select(Session).where(
        Session.parent_session_id.in_(ids),
        Session.agent_slug.isnot(None),
        Session.agent_slug != "persona",
    )
    query = _apply_since(query, hours)
    if parsed_search and parsed_search.has_terms():
        query = query.where(and_(*_session_search_predicates(parsed_search)))
    return query
