"""Conservative activity attribution over real hotspot inputs, without providers."""

import sqlite3
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace as Row
from unittest.mock import AsyncMock, Mock

import pytest
from sqlalchemy.dialects import sqlite

from app.services.admin_activity_cost import build_activity_cost_snapshot, summarize_activity_cost

NOW = datetime(2026, 10, 22, 12, tzinfo=UTC)


def event(kind="tool_use", *, sid="s", turn=1, call="c", seconds=0, at=10, **kw):
    return Row(
        id=f"{kind}:{sid}:{call}:{at}", session_id=sid, turn=turn, sequence=at,
        event_type=kind, call_id=call, tool_name=kw.pop("tool_name", "Bash"),
        tool_input=kw.pop("tool_input", {"command": "st context task-123"}),
        usage=kw.pop("usage", None), duration_ms=seconds * 1000 or None,
        source_timestamp=NOW - timedelta(seconds=at), created_at=NOW - timedelta(seconds=at),
        native_turn_id=kw.pop("native_turn_id", None), native_status=kw.pop("native_status", None),
        **kw,
    )


def usage(*, sid="s", turn=1, response="r", inp=100, out=20, **kw):
    return event("usage", sid=sid, turn=turn, tool_input=None, usage={
        "scope": "response", "response_id": response, "turn_id": f"native-{turn}",
        "input_tokens": inp, "cached_input_tokens": inp // 2,
        "output_tokens": out, "reasoning_output_tokens": out // 2, **kw,
    })


def snapshot(events=(), *, costs=(), ledger=(), sessions=None, bindings=(), limit=5):
    return summarize_activity_cost(
        list(events), list(costs), list(ledger),
        sessions or [Row(id="s", project_id="project", provider="codex")], list(bindings),
        cutoff=NOW - timedelta(hours=24), now=NOW, limit=limit, truncated=False,
    )


def buckets(rows, key):
    return {row["category"]: row[key] for row in rows}


def test_response_denominator_excludes_counters_cache_and_duplicate_responses():
    measured = usage()
    counter = usage(response="counter", inp=99999, scope="thread")
    result = snapshot([event(), measured, measured, counter])
    assert result["tokens"]["denominator"] == 120
    assert buckets(result["tokens"]["breakdown"], "tokens")["administration"] == 120
    assert result["response_tokens"]["denominator"] == 120


def test_mixed_turn_and_missing_tool_evidence_stay_mixed_or_unknown():
    result = snapshot([
        event(), event(call="edit", tool_name="apply_patch", tool_input={}), usage(),
        usage(turn=2, response="no-tools", inp=40, out=10),
    ])
    assert buckets(result["tokens"]["breakdown"], "tokens") == {
        "substantive": 0, "administration": 0, "unknown": 170,
    }
    assert result["tokens"]["mixed_tokens"] == 120
    assert result["tokens"]["unclassified_share"] == 1


def test_global_ledger_precedence_does_not_sum_overlapping_sources():
    result = snapshot(
        [event(), usage()],
        costs=[Row(session_id="s", input_tokens=80, output_tokens=20, calls=1)],
        ledger=[Row(session_id="s", input_tokens=100, output_tokens=20, calls=1)],
    )
    assert result["tokens"]["denominator"] == 100
    assert result["tokens"]["unclassified_share"] == 1
    assert result["tokens"]["sources"][0]["source"] == "cost_logs"
    assert result["response_tokens"]["denominator"] == 120
    assert result["overlapping_sources_excluded"] == 2


def test_other_providers_with_ledger_only_are_included_as_unknown():
    result = snapshot(
        [event(), usage()],
        sessions=[Row(id="s", project_id="p", provider="codex"), Row(id="claude", project_id="p", provider="claude")],
        ledger=[Row(session_id="claude", input_tokens=400, output_tokens=50, calls=2)],
    )
    assert result["tokens"]["denominator"] == 570
    assert buckets(result["tokens"]["breakdown"], "tokens")["unknown"] == 450
    assert result["sessions"] == 2


def test_postgres_bigint_sum_keeps_exact_decimal_ledger_tokens():
    result = snapshot(ledger=[Row(session_id="s", input_tokens=Decimal("109178850"),
                                  output_tokens=Decimal("244"), calls=1)])
    assert result["tokens"]["denominator"] == 109179094
    assert result["tokens"]["unclassified_share"] == 1


def test_time_union_excludes_wait_and_retains_overlapping_mixed_activity():
    result = snapshot([
        event(call="a"), event("tool_result", call="a", seconds=10, at=10),
        event(call="b", tool_name="apply_patch"),
        event("tool_result", call="b", seconds=10, at=5),
        event(call="w", tool_name="sleep"),
        event("tool_result", call="w", tool_name="sleep", seconds=8, at=20),
    ])
    time = result["tool_time"]
    assert time["denominator_seconds"] == 15
    assert buckets(time["breakdown"], "seconds")["administration"] == 5
    assert time["mixed_seconds"] == 5
    assert buckets(time["breakdown"], "seconds")["unknown"] == 5
    assert buckets(time["breakdown"], "seconds")["substantive"] == 5
    assert time["explicit_wait_seconds"] == 8
    assert time["thinking_seconds"] is None
    assert time["idle_seconds"] is None


def test_repeat_family_is_observation_not_waste_and_wrappers_are_not_counted_twice():
    secret = "private-command-argument"
    wrapper = event(call="wrapper", tool_name="exec", tool_input={"raw": secret})
    native = event(call="n1", tool_input={
        "command": f"st context {secret}", "wrapper_candidate_call_id": "wrapper",
        "wrapper_correlation": "nested_command_digest",
    })
    result = snapshot([wrapper, native, event(call="n2"), event(call="n2")])
    pattern = result["repeat_admin_patterns"][0]
    assert pattern["family"] == "st.context"
    assert pattern["calls"] == 2
    assert pattern["avoidable"] is None
    assert secret not in str(result)


def test_task_rollup_uses_single_durable_binding_and_exposes_unlinked():
    sessions = [Row(id=s, project_id="p", provider="codex", external_id="task-fake") for s in ("s", "other")]
    bindings = [Row(session_id="s", project_id="p", task_id="task-real")]
    result = snapshot([usage(), usage(sid="other", response="r2")], sessions=sessions, bindings=bindings)
    assert result["task_rollups"][0]["task_id"] == "task-real"
    assert result["task_rollups"][0]["tokens"] == 120
    assert result["unlinked_sessions"] == 1
    ambiguous = snapshot([usage()], bindings=[*bindings, Row(session_id="s", project_id="p", task_id="task-other")])
    assert ambiguous["unlinked_sessions"] == 1
    assert ambiguous["task_rollups"] == []


def test_unknown_commands_and_partial_sampling_do_not_look_like_full_classification():
    result = snapshot([event(tool_input={"command": "st context task-123 && arbitrary_program secret"}), usage()])
    assert result["tokens"]["mixed_tokens"] == 120
    empty = snapshot()
    assert empty["tokens"]["unclassified_share"] is None
    assert empty["tool_time"]["denominator_seconds"] == 0
    assert empty["missing_usage_sessions"] == 1


def test_support_and_coordination_share_the_coarse_admin_category():
    result = snapshot([
        event(call="check", tool_input={"command": "st check --quick"}),
        event("tool_result", call="check", seconds=5),
        event(call="task"), event("tool_result", call="task", seconds=5), usage(),
    ])
    assert buckets(result["tokens"]["breakdown"], "tokens")["administration"] == 120
    assert buckets(result["tool_time"]["breakdown"], "seconds")["administration"] == 5
    assert result["tool_time"]["mixed_seconds"] == 0


def test_conflicting_native_turns_and_invalid_usage_are_not_falsely_classified():
    conflicting = usage(response="second", turn_id="another-native-turn")
    result = snapshot([event(), usage(), conflicting, usage(response="partial", output_tokens=None)])
    assert result["tokens"]["denominator"] == 240
    assert result["tokens"]["mixed_tokens"] == 240


@pytest.mark.asyncio
async def test_query_is_bounded_preserves_ledger_denominator_and_old_active_sessions(monkeypatch):
    monkeypatch.setattr("app.services.admin_activity_cost.EVENT_LIMIT", 2)
    rows = [
        [event(), usage(), event(call="overflow")],
        [Row(session_id="old", input_tokens=200, output_tokens=10, calls=1)],
        [],
        [Row(id="s", project_id="p", provider="codex"), Row(id="old", project_id="p", provider="openai"), Row(id="no-usage", project_id="p", provider="gemini")],
        [],
    ]
    db = AsyncMock()
    db.execute.side_effect = [Mock(all=Mock(return_value=value)) for value in rows]
    result = await build_activity_cost_snapshot(db, cutoff=NOW - timedelta(hours=24), now=NOW, limit=5)
    assert result["events_truncated"] is True
    assert result["events_sampled"] == 2
    assert result["tokens"]["denominator"] == 330
    assert result["tokens"]["unclassified_share"] == 1
    assert result["sessions"] == 3
    assert result["missing_usage_sessions"] == 1
    statements = [str(call.args[0]) for call in db.execute.call_args_list]
    assert "LIMIT" in statements[0]
    assert "session_events.content" not in statements[0]
    assert "session_events.tool_output" not in statements[0]
    assert "sessions.updated_at BETWEEN" in statements[3]
    assert "usage_calls.agent_id" in statements[2]
    # Execute the actual aggregate queries against an isolated in-memory DB:
    # cached partitions and historical provider aliases must survive the seam.
    with sqlite3.connect(":memory:") as sql:
        sql.executescript("""
            CREATE TABLE cost_logs (session_id TEXT, input_tokens INT, output_tokens INT,
                cache_read_tokens INT, cache_write_tokens INT, created_at TEXT);
            CREATE TABLE sessions (id TEXT, provider TEXT, session_type TEXT);
            CREATE TABLE usage_calls (session_id TEXT, agent_id TEXT, provider TEXT,
                input_tokens INT, cached_input_tokens INT, cache_write_tokens INT,
                output_tokens INT, occurred_at TEXT);
        """)
        timestamp = "2026-10-22 11:59:00.000000"
        sql.execute("INSERT INTO cost_logs VALUES (?, 10, 20, 30, 40, ?)", ("cached", timestamp))
        cost_query = db.execute.call_args_list[1].args[0]
        compiled = str(cost_query.compile(dialect=sqlite.dialect(), compile_kwargs={"literal_binds": True}))
        assert sql.execute(compiled).fetchall() == [("cached", 80, 20, 1)]
        sql.executemany("INSERT INTO sessions VALUES (?, ?, ?)", [
            ("claude-native", "anthropic", "claude_code"),
            ("claude-legacy", "openai", "claude_code"),
            ("codex-child", "codex", "agent"),
            ("unrelated", "openai", "chat"),
        ])
        sql.executemany("INSERT INTO usage_calls VALUES (?, ?, ?, 10, 20, 30, 40, ?)", [
            ("claude-native", "", "claude", timestamp),
            ("claude-legacy", "", "claude", timestamp),
            ("root", "codex-child", "codex", timestamp),
            ("unrelated", "", "claude", timestamp),
        ])
        ledger_query = db.execute.call_args_list[2].args[0]
        compiled = str(ledger_query.compile(dialect=sqlite.dialect(), compile_kwargs={"literal_binds": True}))
        assert sorted(sql.execute(compiled).fetchall()) == [
            ("claude-legacy", 60, 40, 1), ("claude-native", 60, 40, 1), ("codex-child", 60, 40, 1),
        ]


def test_orphan_result_and_no_call_id_runtime_keep_unknown_time_visible():
    result = snapshot([event("tool_result", call=None, tool_input=None, tool_name="Bash", seconds=5)])
    assert result["tool_time"]["denominator_seconds"] == 5
    assert buckets(result["tool_time"]["breakdown"], "seconds")["unknown"] == 5
