"""Tests for Jenny improvement service field scoring."""

from __future__ import annotations

from app.services.persona_improvement import evaluate_persona_heartbeat_field_snapshot


def test_evaluate_persona_heartbeat_field_snapshot_allows_clean_recent_field_data() -> None:
    snapshot = {
        "overview": {
            "reliability": 94.0,
            "truth_quality": 96.0,
            "critical_heartbeats": 0,
        },
        "recent_heartbeats": [{"session_id": "sess-1"}],
    }

    result = evaluate_persona_heartbeat_field_snapshot(snapshot)

    assert result == {
        "needs_review": False,
        "reason_codes": [],
        "summary": "field_ok",
    }


def test_evaluate_persona_heartbeat_field_snapshot_flags_critical_or_low_quality_field_data() -> None:
    snapshot = {
        "overview": {
            "reliability": 82.0,
            "truth_quality": 80.0,
            "critical_heartbeats": 1,
        },
        "recent_heartbeats": [{"session_id": "sess-1"}],
    }

    result = evaluate_persona_heartbeat_field_snapshot(snapshot)

    assert result["needs_review"] is True
    assert result["reason_codes"] == [
        "critical_heartbeat_failures",
        "field_reliability_low",
        "field_truth_quality_low",
    ]
    assert "recent critical heartbeat failures" in result["summary"]
