"""Session lifetime declarations and weighted comparable accounting contracts."""

from datetime import datetime, timedelta
from types import SimpleNamespace as Row

import pytest
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.dialects import postgresql

from app.models import Session
from app.services.admin_activity_cost import summarize_activity_cost
from app.services.session_accounting import (
    accounting_cursor,
    accounting_window,
    summarize_session_duration,
)
from app.services.session_branching import create_forked_session
from app.services.session_harnesses import harness_predicate, session_harness
from app.services.session_ingestion._service_helpers import _merge_metadata
from app.services.session_roles import WorkRoleConflict, role_predicate, session_work_role
from tests.services.test_admin_activity_cost import NOW, event


def test_declare_once_idempotent_conflict_and_omitted_or_null_resume():
    metadata = _merge_metadata({"external_identity": {"display_identity": "worker"}}, {
        "work_role": {"id": "implementation", "source": "explicit-launch", "display_name": "Backend"},
    })
    original = metadata["work_role"].copy()
    assert original["declared_at"]
    for incoming in ({}, {"work_role": None}, {"work_role": {"id": "implementation", "source": "retry", "display_name": "Renamed"}}):
        metadata = _merge_metadata(metadata, incoming)
        assert metadata["work_role"] == original
    assert metadata["external_identity"] == {"display_identity": "worker"}
    role = session_work_role(Row(provider_metadata=metadata))
    assert role is not None and role["label"] == "Implementation"
    with pytest.raises(WorkRoleConflict, match="fixed"):
        _merge_metadata(metadata, {"work_role": {"id": "review", "source": "resume"}})
    for invalid in ({"id": "unknown", "source": "launcher"}, {"id": "other", "source": " "}):
        with pytest.raises(ValidationError):
            _merge_metadata({}, {"work_role": invalid})
    assert session_work_role(Row(provider_metadata={"role": "review", "name": "Implementation"})) is None


def test_child_session_never_inherits_parent_declaration():
    parent = Session(id="parent", project_id="agent-hub", provider="codex", model="fixture", session_type="agent",
                     provider_metadata=_merge_metadata({}, {"work_role": {"id": "coordinator", "source": "initial-coordinator"}, "cwd": "/fixture"}))
    child = create_forked_session(parent, "child", 1)
    assert session_work_role(child) is None
    assert child.provider_metadata == {"cwd": "/fixture"}
    role = session_work_role(parent)
    assert role is not None and role["id"] == "coordinator"


def test_harness_requires_explicit_provenance_and_matches_filter_registry():
    assert session_harness(Row(provider="codex", model="codex/model", session_type="claude_code")) == "unknown"
    assert session_harness(Row(provider_metadata={"harness": "pi"})) == "pi"
    assert session_harness(Row(request_source="codex-transcript-sync")) == "codex_cli"
    assert session_harness(Row(provider_metadata={"harness": "pi", "external_identity": {"harness": "antigravity"}})) == "antigravity"
    assert session_harness(Row(provider_metadata={"harness": "unregistered"}, request_source="codex-transcript-sync")) == "unknown"
    for predicate in (role_predicate("unknown"), harness_predicate("codex_cli")):
        sql = str(select(Session.id).where(predicate).compile(dialect=postgresql.dialect()))
        assert "provider_metadata" in sql
        assert "sessions.model" not in sql and "sessions.provider =" not in sql


def test_duration_coverage_keeps_missing_zero_overlap_wait_and_unknown_distinct():
    calls = [event(call="admin", seconds=10), event(call="edit", seconds=10, tool_name="apply_patch", tool_input={}, at=15),
             event(call="zero", duration_ms=0), event(call="missing", duration_ms=None),
             event(call="wait", seconds=40, tool_name="sleep", tool_input={}, at=60)]
    measured = summarize_session_duration(calls, start=NOW - timedelta(hours=1), end=NOW)
    assert measured["denominator_seconds"] == 15  # union; five seconds mixed
    assert measured["admin_seconds"] == 5 and measured["other_seconds"] == 10
    assert measured["unknown_seconds"] == 5
    assert measured["tools_sampled"] == 5 and measured["tools_missing_duration"] == 1
    assert measured["duration_coverage"] == 0.8
    zero = summarize_session_duration([event(duration_ms=0)], start=NOW - timedelta(hours=1), end=NOW)
    missing = summarize_session_duration([event(duration_ms=None)], start=NOW - timedelta(hours=1), end=NOW)
    assert zero["admin_share"] is missing["admin_share"] is None
    assert zero["duration_coverage"] == 1 and missing["duration_coverage"] == 0
    assert summarize_session_duration([], start=NOW - timedelta(hours=1), end=NOW)["duration_coverage"] is None


def comparison_sample():
    sessions = [Row(id=sid, project_id=project, provider="fixture", model="fixture",
                    provider_metadata=_merge_metadata({}, {"work_role": {"id": role, "source": "fixture"}, "harness": harness}) if role else {"harness": harness})
                for sid, project, role, harness in (("a", "p1", "implementation", "codex"), ("b", "p1", "implementation", "pi"), ("c", "p2", None, "antigravity"), ("empty", "p2", None, "unknown"))]
    events = [event(sid="a", seconds=10), event(sid="b", seconds=90, tool_name="apply_patch", tool_input={}),
              event(sid="c", seconds=20, tool_name="unknown", tool_input={}), event(sid="c", call="missing", duration_ms=None)]
    costs = [Row(session_id="a", input_tokens=100, output_tokens=10, calls=2, api_equiv_usd=0.1, api_equiv_known_calls=1, cash_usd=0, cash_known_calls=2)]
    ledger = [Row(session_id="a", input_tokens=999, output_tokens=999, calls=1, api_equiv_usd=99),
              Row(session_id="b", input_tokens=300, output_tokens=30, calls=1, api_equiv_usd=0.2, api_equiv_known_calls=1)]
    return events, costs, ledger, sessions


def test_weighted_groups_share_identical_ledger_not_average_session_percentages():
    events, costs, ledger, sessions = comparison_sample()
    data = summarize_activity_cost(events, costs, ledger, sessions, [], cutoff=NOW - timedelta(hours=1), now=NOW, limit=1, truncated=False)
    assert data["duration_split"]["admin_share"] == pytest.approx(10 / 120)
    assert len(data["by_project"]) == 2 and len(data["by_harness"]) == 4  # no output row cap
    p1 = next(row for row in data["by_project"] if row["project_id"] == "p1")
    impl = next(row for row in data["by_work_role"] if row["work_role_id"] == "implementation")
    assert p1["duration_split"] == impl["duration_split"]
    assert impl["duration_split"]["admin_share"] == 0.1  # not mean(1, 0)
    assert impl["usage"]["input_tokens"] == 400 and impl["usage"]["output_tokens"] == 40
    assert impl["cost"] == {"recorded_calls": 3, "api_equiv_known_calls": 2, "cash_known_calls": 2, "api_equiv_usd": pytest.approx(0.3), "cash_usd": 0}
    assert impl["coverage"] == {"usage_sessions": 2, "missing_usage_sessions": 0}
    assert data["overlapping_sources_excluded"] == 1
    unknown = next(row for row in data["by_work_role"] if row["work_role_id"] == "unknown")
    assert unknown["sessions"] == 2 and unknown["duration_split"]["other_share"] == 1
    assert unknown["duration_split"]["unknown_seconds"] == 20
    assert unknown["cost"]["api_equiv_usd"] is None
    assert unknown["cost"]["cash_usd"] is None
    assert sum(row["duration_split"]["denominator_seconds"] for row in data["by_harness"]) == data["duration_split"]["denominator_seconds"]


@pytest.mark.parametrize("hours", [1, 24, 168])
def test_accounting_window_survives_cursors_for_all_presets(hours):
    start, end = NOW - timedelta(hours=hours), NOW
    cursor = accounting_cursor("inner", start, end)
    assert accounting_window(None, None, cursor) == (start, end, "inner")
    with pytest.raises(ValueError, match="window"):
        accounting_window(start - timedelta(seconds=1), end, cursor)
    with pytest.raises(ValueError, match="both"):
        accounting_window(start, None, None)
    with pytest.raises(ValueError, match="timezone"):
        accounting_window(datetime(2026, 10, 1), end, None)
