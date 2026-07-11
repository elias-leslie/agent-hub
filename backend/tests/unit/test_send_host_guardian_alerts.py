from __future__ import annotations

import json
from pathlib import Path

from app.scripts.send_host_guardian_alerts import (
    format_event,
    load_events,
    pending_events,
)


def test_load_events_ignores_malformed_lines(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    path.write_text(
        "not-json\n" + json.dumps({"event_id": "one", "status": "healthy"}) + "\n",
        encoding="utf-8",
    )

    assert load_events(path) == [{"event_id": "one", "status": "healthy"}]


def test_pending_events_resume_after_last_delivery() -> None:
    events = [{"event_id": "one"}, {"event_id": "two"}, {"event_id": "three"}]

    assert pending_events(events, "two") == [{"event_id": "three"}]


def test_initial_healthy_event_is_suppressed() -> None:
    assert format_event({"status": "healthy", "previous_status": None}) is None


def test_critical_event_requests_intervention() -> None:
    rendered = format_event(
        {
            "status": "critical",
            "previous_status": "healthy",
            "occurred_at": "2026-07-11T12:00:00+00:00",
            "issues": [{"message": "PostgreSQL is unavailable"}],
            "actions": ["restarted Docker"],
        }
    )

    assert rendered is not None
    title, body = rendered
    assert title == "Host intervention required"
    assert "PostgreSQL is unavailable" in body
    assert "restarted Docker" in body


def test_recovery_event_is_reported() -> None:
    rendered = format_event({"status": "healthy", "previous_status": "critical"})

    assert rendered is not None
    assert rendered[0] == "Host recovered"
