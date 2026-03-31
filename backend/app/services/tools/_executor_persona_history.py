"""Persona history recall helpers for bounded self-reflection searches."""

from __future__ import annotations

import logging

from app.api.persona.pulse import build_session_pulses
from app.api.persona.stream import (
    _fetch_display_summaries,
    _fetch_event_counts,
    _fetch_event_previews,
    _fetch_persona_chat_events,
    _fetch_sessions,
)
from app.api.persona.stream_builders import _build_stream_entries
from app.api.persona.stream_search import _build_search_matches, _parse_search

logger = logging.getLogger(__name__)

_CHAT_MESSAGE_TYPES = ("user_message", "assistant_message")


def _match_line(entry, match) -> str:
    live_parts = []
    if entry.live_status:
        live_parts.append(f"live={entry.live_status}")
    if entry.live_topic:
        live_parts.append(f"topic={entry.live_topic}")
    if entry.external_id:
        live_parts.append(f"task={entry.external_id}")
    if entry.current_branch:
        live_parts.append(f"branch={entry.current_branch}")
    live_suffix = f" | {' | '.join(live_parts)}" if live_parts else ""
    snippet = " ".join(str(match.snippet or "").split())
    if len(snippet) > 160:
        snippet = snippet[:159] + "…"
    return (
        f"- {entry.timestamp:%Y-%m-%d %H:%M} | {entry.entry_type} | {entry.project_id} | "
        f"{entry.agent_slug or '?'} | status={entry.status}{live_suffix} | "
        f"session={entry.session_id} | {snippet}"
    )


async def search_persona_history(
    query: str,
    hours_back: int = 168,
    limit: int = 8,
    project_id: str | None = None,
) -> str:
    """Search persona and child-session history using the stream's search semantics."""
    search_term = (query or "").strip()
    if not search_term:
        return "Error: query is required"
    if project_id and f"project:{project_id}".lower() not in search_term.lower():
        search_term = f"{search_term} project:{project_id}"

    parsed_search = _parse_search(search_term)
    if not parsed_search.has_terms():
        return "Error: query did not contain searchable terms"

    try:
        from app.db import async_session

        async with async_session() as db:
            persona_sessions, child_sessions = await _fetch_sessions(db, hours_back, parsed_search)
            all_session_ids = [s.id for s in persona_sessions] + [s.id for s in child_sessions]
            if not all_session_ids:
                return f"(No persona history matches in last {hours_back}h for '{search_term}')"

            message_counts = await _fetch_event_counts(db, all_session_ids, _CHAT_MESSAGE_TYPES)
            tool_counts = await _fetch_event_counts(db, all_session_ids, ("tool_use",))
            event_previews = await _fetch_event_previews(db, all_session_ids)
            persona_chat_ids = [s.id for s in persona_sessions if s.session_type == "chat"]
            message_events = await _fetch_persona_chat_events(db, persona_chat_ids)
            all_sessions = [*persona_sessions, *child_sessions]
            session_pulses = build_session_pulses(all_sessions, event_previews)
            display_summaries = await _fetch_display_summaries(db, all_sessions)

        entries = _build_stream_entries(
            persona_sessions,
            child_sessions,
            message_events,
            message_counts,
            tool_counts,
            event_previews,
            session_pulses,
            display_summaries,
        )
        matches, match_count = _build_search_matches(entries, parsed_search=parsed_search, limit=limit)
        if not matches:
            return f"(No persona history matches in last {hours_back}h for '{search_term}')"

        entry_by_id = {entry.id: entry for entry in entries}
        lines = [f"Persona history matches ({len(matches)}/{match_count}) for '{search_term}':"]
        for match in matches:
            entry = entry_by_id.get(match.entry_id)
            if entry is None:
                continue
            lines.append(_match_line(entry, match))
        lines.append(f'Next: inspect_session(session_id="{matches[0].session_id}") for the top match.')
        return "\n".join(lines)
    except Exception as e:
        logger.exception("search_persona_history failed")
        return f"Error searching persona history: {e}"


__all__ = ["search_persona_history"]
