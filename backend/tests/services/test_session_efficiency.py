"""Session goal/coverage and read-side window filters, without provider calls."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace as Row
from unittest.mock import AsyncMock, Mock

import pytest
from sqlalchemy.dialects import postgresql

from app.services.admin_activity_cost import build_activity_cost_snapshot, summarize_activity_cost
from app.services.session_efficiency import efficiency_status
from app.services.st_activity import POLICY

NOW = datetime(2026, 10, 22, 12, tzinfo=UTC)


def sample(*, truncated=False, limit=5):
    events = []
    for sid, calls in (("admin", [("st context example", 5), ("st context example", 5), ("edit", 10)]),
                       ("tokens", [("edit", 10)]), ("unknown", [("unknown", 1)])):
        for index, (command, duration) in enumerate(calls):
            for kind in ("tool_use", "tool_result"):
                events.append(Row(id=f"{sid}-{index}-{kind}", session_id=sid, turn=1,
                    sequence=index * 2 + (kind == "tool_result"), event_type=kind, call_id=f"c{index}",
                    tool_name="apply_patch" if command == "edit" else "exec_command",
                    tool_input={"cmd": command}, duration_ms=duration * 1000 if kind == "tool_result" else None,
                    source_timestamp=NOW - timedelta(seconds=60 - index * 20), created_at=NOW,
                    returned_characters=100 if kind == "tool_result" else None, usage=None))
    return summarize_activity_cost(events, [], [Row(session_id="tokens", input_tokens=1000, output_tokens=10, calls=1)],
        [Row(id=sid, project_id="project", provider="codex", model="fixture-model",
             provider_metadata={"request_errors": {"count": 2, "last_category": "request_timeout", "last_message": "Request timed out."}}
             if sid == "admin" else {}) for sid in ("admin", "tokens", "unknown", "empty")],
        [], cutoff=NOW - timedelta(hours=1), now=NOW, limit=limit, truncated=truncated)


def test_sessions_rank_by_admin_time_without_tasks_or_provider_usage():
    result = sample(limit=1)
    assert result["session_rankings"][0]["session_id"] == "tokens"
    data = result["session_efficiency"]
    assert data["sessions_total"] == 4
    assert sum(data["status_counts"].values()) == 4
    row = data["rows"][0]
    assert row["session_id"] == "admin"
    assert row["usage_source"] == "missing"
    assert row["tools_sampled"] == 3 and row["tools_missing_duration"] == 0
    assert row["tool_time"]["denominator_seconds"] == 20
    assert row["tool_time"]["breakdown"][1]["share"] == 0.5
    assert row["sampled_event_span_seconds"] == 40
    assert row["repeat_admin_patterns"] == [{"family": "st.context", "calls": 2, "measured_tool_seconds": 10}]
    assert result["task_rollups"] == []


def test_pi_pair_timestamps_measure_tool_time_without_native_duration():
    events = [Row(id=f"pi-{kind}", session_id="pi", turn=1, sequence=index + 1,
                  event_type=kind, call_id="call", tool_name="exec_command",
                  tool_input={"cmd": "st context fixture"}, duration_ms=None,
                  source_timestamp=NOW - timedelta(seconds=50 - index * 30), created_at=NOW,
                  returned_characters=None, usage=None)
              for index, kind in enumerate(("tool_use", "tool_result"))]
    sessions = [Row(id="pi", project_id="project", provider="pi", model="fixture",
                    session_type="pi", provider_metadata={"harness": "pi"})]
    measured = summarize_activity_cost(events, [], [], sessions, [],
                                       cutoff=NOW - timedelta(hours=1), now=NOW, limit=5, truncated=False)
    assert measured["duration_split"]["admin_seconds"] == 30
    assert measured["duration_split"]["duration_coverage"] == 1
    assert measured["by_harness"][0]["harness_id"] == "pi"
    assert measured["by_harness"][0]["duration_split"]["admin_share"] == 1


def test_goal_keeps_unknown_caps_missing_duration_zero_and_unselected_distinct(monkeypatch):
    monkeypatch.setitem(POLICY, "session_efficiency", {
        "admin_share_target": 0.5, "minimum_duration_coverage": 0.8, "maximum_unknown_share": 0.2,
    })
    measured = sample()["session_efficiency"]
    assert measured["status_counts"] == {"within_goal": 2, "above_goal": 0, "insufficient_coverage": 1, "unmeasured": 1, "goal_not_selected": 0}
    tool_time = measured["rows"][0]["tool_time"]
    assert efficiency_status(tool_time, calls=10, missing=3, truncated=False) == "insufficient_coverage"
    assert efficiency_status(tool_time, calls=10, missing=0, truncated=True) == "insufficient_coverage"
    POLICY["session_efficiency"]["admin_share_target"] = 0.4
    assert efficiency_status(tool_time, calls=10, missing=0, truncated=False) == "above_goal"
    POLICY["session_efficiency"]["admin_share_target"] = None
    assert efficiency_status(tool_time, calls=10, missing=0, truncated=False) == "goal_not_selected"


@pytest.mark.asyncio
async def test_filters_apply_before_event_cap_and_to_all_accounting_sources():
    db = AsyncMock()
    db.execute.side_effect = [Mock(all=Mock(return_value=[])) for _ in range(4)]
    result = await build_activity_cost_snapshot(db, cutoff=NOW - timedelta(hours=1), now=NOW, limit=5,
        project_id="project", provider="codex", model="fixture-model", session_id="admin")
    assert result["sessions"] == 0
    queries = [call.args[0].compile(dialect=postgresql.dialect()) for call in db.execute.call_args_list]
    for query in queries:
        assert "sessions.project_id =" in str(query) and "sessions.provider =" in str(query)
        assert "admin" in query.params.values()
        assert "fixture-model" in query.params.values()
    assert "LIMIT" in str(queries[0])
    for query in queries[:3]:
        assert " < " in str(query)  # adjacent windows have exclusive end
    assert "tool_output AS" not in str(queries[0])


def test_backend_fixture_matches_frontend_boundary():
    path = Path(__file__).parents[3] / "frontend/src/__tests__/fixtures/session-efficiency-snapshot.json"
    assert sample() == json.loads(path.read_text())
