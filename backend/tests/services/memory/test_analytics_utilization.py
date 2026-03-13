"""Tests for memory utilization analytics helpers."""

from __future__ import annotations

from datetime import UTC, datetime

from app.services.memory._analytics_utilization import (
    _build_memory_utilization_metrics,
    _extract_memory_command_kind,
    _LookupEvent,
)


def test_extract_memory_command_kind_handles_supported_commands() -> None:
    assert _extract_memory_command_kind({"cmd": "st memory search prompt structure"}) == "search"
    assert _extract_memory_command_kind({"command": "st memory get 115b32e3"}) == "get"
    assert _extract_memory_command_kind({"cmd": "st search anything"}) is None


def test_build_memory_utilization_metrics_tracks_lookup_and_reference_followthrough() -> None:
    injected_at = datetime(2026, 3, 13, 12, 0, tzinfo=UTC)

    metrics = _build_memory_utilization_metrics(
        injection_session_ids={"s1", "s2"},
        citation_session_ids={"s1"},
        lookup_events=[
            _LookupEvent(session_id="s1", created_at=injected_at, command_kind="search"),
            _LookupEvent(session_id="s1", created_at=injected_at, command_kind="get"),
            _LookupEvent(session_id="s3", created_at=injected_at, command_kind="search"),
        ],
        first_injection_at={"s1": injected_at, "s2": injected_at},
        assistant_message_count=5,
        assistant_messages_with_memory_citations=2,
        selected_reference_count=6,
        selected_reference_cited_count=3,
        sessions_with_selected_references=2,
        sessions_with_cited_selected_references=1,
        memory_inject_event_count=4,
        memory_inject_events_with_debug=3,
    )

    assert metrics.injection_sessions == 2
    assert metrics.citation_sessions == 1
    assert metrics.lookup_sessions == 2
    assert metrics.lookup_after_injection_sessions == 1
    assert metrics.memory_search_calls == 2
    assert metrics.memory_get_calls == 1
    assert metrics.citation_session_rate == 0.5
    assert metrics.lookup_session_rate == 0.5
    assert metrics.expansion_session_rate == 0.5
    assert metrics.assistant_citation_rate == 0.4
    assert metrics.selected_reference_citation_rate == 0.5
    assert metrics.selected_reference_session_rate == 0.5
    assert metrics.memory_debug_coverage_rate == 0.75
