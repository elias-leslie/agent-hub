"""Search parsing and in-memory entry matching helpers for the persona stream."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .schemas import PersonaStreamEntry, PersonaStreamMatch

_STRUCTURED_PREFIXES = {"task", "file", "agent", "status", "project", "topic"}


@dataclass(slots=True)
class ParsedSearch:
    general_terms: list[str] = field(default_factory=list)
    task_terms: list[str] = field(default_factory=list)
    file_terms: list[str] = field(default_factory=list)
    agent_terms: list[str] = field(default_factory=list)
    status_terms: list[str] = field(default_factory=list)
    project_terms: list[str] = field(default_factory=list)
    topic_terms: list[str] = field(default_factory=list)

    def has_terms(self) -> bool:
        return any(
            [
                self.general_terms,
                self.task_terms,
                self.file_terms,
                self.agent_terms,
                self.status_terms,
                self.project_terms,
                self.topic_terms,
            ]
        )


def _parse_search(search: str | None) -> ParsedSearch:
    parsed = ParsedSearch()
    if not search:
        return parsed
    for raw_token in search.split():
        token = raw_token.strip()
        if not token:
            continue
        prefix, separator, value = token.partition(":")
        normalized_prefix = prefix.lower()
        normalized_value = value.strip().lower()
        if separator and normalized_prefix in _STRUCTURED_PREFIXES and normalized_value:
            getattr(parsed, f"{normalized_prefix}_terms").append(normalized_value)
            continue
        parsed.general_terms.append(token.lower())
    return parsed


def _matches_terms(text: str, terms: list[str]) -> bool:
    return all(term in text for term in terms)


def _str_join(*values: Any) -> str:
    """Join non-empty string values as lowercase, ignoring None and non-strings."""
    return " ".join(v.lower() for v in values if isinstance(v, str) and v)


def _entry_match_text(entry: PersonaStreamEntry) -> str:
    return " ".join(
        value
        for value in [
            entry.content,
            entry.display_summary,
            entry.summary_oneliner,
            entry.live_summary,
            entry.live_topic,
            entry.agent_slug,
            entry.project_id,
            entry.external_id,
            entry.current_branch,
            entry.model,
            *[
                preview_value
                for preview in entry.event_previews
                for preview_value in [
                    preview.tool_name,
                    preview.content_preview,
                    preview.tool_input_preview,
                    preview.tool_output_preview,
                    preview.model_used,
                    preview.event_type,
                ]
                if isinstance(preview_value, str)
            ],
            *[
                marker_value
                for marker in entry.issue_markers
                for marker_value in [
                    marker.title,
                    marker.summary,
                    marker.tool_name,
                    marker.primary_tag,
                    marker.primary_root_cause,
                ]
                if isinstance(marker_value, str)
            ],
        ]
        if isinstance(value, str) and value
    ).lower()


def _entry_matches_search(entry: PersonaStreamEntry, parsed_search: ParsedSearch) -> bool:
    if not parsed_search.has_terms():
        return False
    entry_text = _entry_match_text(entry)
    if parsed_search.general_terms and not _matches_terms(entry_text, parsed_search.general_terms):
        return False
    if parsed_search.task_terms:
        task_text = _str_join(entry.external_id, entry.display_summary, entry.summary_oneliner, entry.live_summary, entry.content)
        if not _matches_terms(task_text, parsed_search.task_terms):
            return False
    if parsed_search.file_terms and not _matches_terms(entry_text, parsed_search.file_terms):
        return False
    if parsed_search.agent_terms:
        agent_text = _str_join(entry.agent_slug, entry.display_summary, entry.summary_oneliner, entry.live_summary)
        if not _matches_terms(agent_text, parsed_search.agent_terms):
            return False
    if parsed_search.status_terms:
        status_text = _str_join(entry.status, entry.live_status, entry.display_summary, entry.summary_oneliner, entry.live_summary)
        if not _matches_terms(status_text, parsed_search.status_terms):
            return False
    if parsed_search.project_terms:
        project_text = _str_join(entry.project_id, entry.current_branch, entry.display_summary, entry.summary_oneliner)
        if not _matches_terms(project_text, parsed_search.project_terms):
            return False
    if parsed_search.topic_terms:
        topic_text = _str_join(entry.live_topic, entry.display_summary, entry.summary_oneliner, entry.live_summary)
        if not _matches_terms(topic_text, parsed_search.topic_terms):
            return False
    return True


def _entry_match_snippet(entry: PersonaStreamEntry) -> str:
    for value in [
        entry.content,
        entry.display_summary,
        entry.summary_oneliner,
        entry.live_summary,
        *[preview.content_preview for preview in entry.event_previews],
        *[preview.tool_name for preview in entry.event_previews],
    ]:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return f"{entry.entry_type} in {entry.project_id}"


def _build_search_matches(
    entries: list[PersonaStreamEntry],
    *,
    parsed_search: ParsedSearch,
    limit: int = 150,
) -> tuple[list[PersonaStreamMatch], int]:
    if not parsed_search.has_terms():
        return [], 0
    matches: list[PersonaStreamMatch] = []
    total_matches = 0
    for entry in entries:
        if not _entry_matches_search(entry, parsed_search):
            continue
        total_matches += 1
        if len(matches) < limit:
            matches.append(
                PersonaStreamMatch(
                    entry_id=entry.id,
                    session_id=entry.session_id,
                    entry_type=entry.entry_type,
                    timestamp=entry.timestamp,
                    snippet=_entry_match_snippet(entry),
                )
            )
    return matches, total_matches


def _center_window(entries: list[PersonaStreamEntry], idx: int, page_size: int) -> list[PersonaStreamEntry]:
    start = max(idx - (page_size // 2), 0)
    end = min(start + page_size, len(entries))
    start = max(end - page_size, 0)
    return entries[start:end]


def _slice_entries(
    entries: list[PersonaStreamEntry],
    *,
    page: int,
    page_size: int,
    focus_session_id: str | None,
    anchor_entry_id: str | None,
) -> list[PersonaStreamEntry]:
    if anchor_entry_id:
        anchor_indexes = [idx for idx, entry in enumerate(entries) if entry.id == anchor_entry_id]
        if anchor_indexes:
            return _center_window(entries, anchor_indexes[0], page_size)
    if focus_session_id:
        focus_indexes = [idx for idx, entry in enumerate(entries) if entry.session_id == focus_session_id]
        if focus_indexes:
            return _center_window(entries, focus_indexes[0], page_size)
    offset = (page - 1) * page_size
    return entries[offset : offset + page_size]
