from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

import app.scripts.send_host_guardian_alerts as alerts
from app.scripts.send_host_guardian_alerts import (
    event_severity,
    format_event,
    load_events,
    pending_events,
    should_suppress_cooldown,
    update_notification_state,
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


def test_alert_cooldown_suppresses_repeated_warnings() -> None:
    event = {
        "status": "warning",
        "issues": [{"code": "root_disk_warning", "message": "root disk 86% used"}],
    }
    state = {}
    now = 100000.0

    assert not should_suppress_cooldown(event, state, now)

    update_notification_state(event, state, now)
    assert state["last_notifications"]["warning:root_disk_warning"] == now

    # Within cooldown (e.g. 15 minutes later)
    assert should_suppress_cooldown(event, state, now + 900)

    # After cooldown (13 hours later)
    assert not should_suppress_cooldown(event, state, now + 46800)



def test_first_run_reports_only_current_state() -> None:
    events = [{"event_id": "one"}, {"event_id": "two"}]

    assert pending_events(events, None) == [{"event_id": "two"}]


def test_event_severity_mapping() -> None:
    assert event_severity({"status": "critical"}) == "critical"
    assert event_severity({"status": "warning"}) == "error"
    assert event_severity({"status": "healthy"}) == "info"


def _write_events(path: Path, events: list[dict]) -> None:
    path.write_text("".join(json.dumps(event) + "\n" for event in events), encoding="utf-8")


async def test_run_alerts_sends_state_changes_to_summitflow(tmp_path: Path) -> None:
    events_path = tmp_path / "events.jsonl"
    state_path = tmp_path / "state.json"
    warning = {
        "event_id": "two",
        "status": "warning",
        "previous_status": "healthy",
        "issues": [{"code": "root_disk_warning", "message": "root disk 86% used"}],
    }
    _write_events(events_path, [{"event_id": "one", "status": "healthy"}, warning])
    state_path.write_text(json.dumps({"last_event_id": "one"}), encoding="utf-8")

    with patch.object(alerts, "create_summitflow_notification", AsyncMock(return_value=True)) as sink:
        sent = await alerts.run_alerts(events_path=events_path, state_path=state_path, dry_run=False)
        # Re-running with no new events sends nothing.
        again = await alerts.run_alerts(events_path=events_path, state_path=state_path, dry_run=False)

    assert sent == 1
    assert again == 0
    sink.assert_awaited_once()
    assert sink.await_args is not None
    kwargs = sink.await_args.kwargs
    assert kwargs["severity"] == "error"
    assert kwargs["title"] == "Host maintenance warning"
    assert "root disk 86% used" in kwargs["message"]
    assert kwargs["metadata"]["source"] == "host-guardian"
    assert kwargs["metadata"]["event_id"] == "two"
    assert json.loads(state_path.read_text())["last_event_id"] == "two"


async def test_run_alerts_keeps_state_when_delivery_fails(tmp_path: Path) -> None:
    events_path = tmp_path / "events.jsonl"
    state_path = tmp_path / "state.json"
    _write_events(
        events_path,
        [{"event_id": "one", "status": "healthy"}, {"event_id": "two", "status": "critical", "previous_status": "healthy"}],
    )
    state_path.write_text(json.dumps({"last_event_id": "one"}), encoding="utf-8")

    with (
        patch.object(alerts, "create_summitflow_notification", AsyncMock(return_value=False)),
        pytest.raises(RuntimeError),
    ):
        await alerts.run_alerts(events_path=events_path, state_path=state_path, dry_run=False)

    assert json.loads(state_path.read_text())["last_event_id"] == "one"


async def test_replay_latest_alert_does_not_touch_state(tmp_path: Path) -> None:
    events_path = tmp_path / "events.jsonl"
    state_path = tmp_path / "state.json"
    _write_events(
        events_path,
        [
            {"event_id": "one", "status": "critical", "previous_status": "healthy"},
            {"event_id": "two", "status": "healthy", "previous_status": "critical"},
        ],
    )

    with patch.object(alerts, "create_summitflow_notification", AsyncMock(return_value=True)) as sink:
        sent = await alerts.replay_latest_alert(events_path=events_path, dry_run=False)

    assert sent == 1
    assert sink.await_args is not None
    assert sink.await_args.kwargs["severity"] == "critical"
    assert sink.await_args.kwargs["metadata"]["event_id"] == "one"
    assert not state_path.exists()
