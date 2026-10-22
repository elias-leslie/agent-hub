"""Conservative activity attribution over real hotspot inputs, without providers."""

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace as Row
from unittest.mock import AsyncMock, Mock

import pytest
from sqlalchemy.dialects import postgresql, sqlite

from app.services.admin_activity_cost import build_activity_cost_snapshot, summarize_activity_cost
from app.services.event_storage import _extract_tool_result_content

NOW = datetime(2026, 10, 22, 12, tzinfo=UTC)


def event(kind="tool_use", *, sid="s", turn=1, call="c", seconds=0, at=10, **kw):
    return Row(
        id=f"{kind}:{sid}:{call}:{at}", session_id=sid, turn=turn, sequence=at,
        event_type=kind, call_id=call, tool_name=kw.pop("tool_name", "Bash"),
        tool_input=kw.pop("tool_input", {"command": "st context task-123"}),
        usage=kw.pop("usage", None), duration_ms=kw.pop("duration_ms", seconds * 1000 or None),
        returned_characters=kw.pop("returned_characters", None),
        source_timestamp=NOW - timedelta(seconds=at), created_at=NOW - timedelta(seconds=at),
        native_turn_id=kw.pop("native_turn_id", None), native_status=kw.pop("native_status", None),
        source_event_id=kw.pop("source_event_id", None),
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
    assert "length(session_events.content)" in statements[0]
    assert "returned_characters" in statements[0]
    assert "jsonb_typeof" in statements[0]
    postgres_query = str(db.execute.call_args_list[0].args[0].compile(dialect=postgresql.dialect()))
    assert "jsonb_typeof" in postgres_query
    assert "session_events.tool_output" in postgres_query
    assert "json_typeof" not in postgres_query
    assert "sessions.updated_at >=" in statements[3]
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
        sql.execute("""CREATE TABLE session_events (
            id TEXT, session_id TEXT, turn INT, sequence INT, event_type TEXT, call_id TEXT,
            tool_name TEXT, tool_input JSON, usage JSON, duration_ms INT,
            source_timestamp TEXT, created_at TEXT, content TEXT, tool_output JSON, source_event_id TEXT
        )""")
        def jsonb_typeof(value):
            parsed = json.loads(value) if value is not None else None
            return "string" if isinstance(parsed, str) else "object" if isinstance(parsed, dict) else "null"
        sql.create_function("jsonb_typeof", 1, jsonb_typeof)
        sql.create_function("to_jsonb", 1, lambda value: value)
        timestamp = "2026-10-22 11:59:00.000000"
        long_output = {"output": "x" * 10000}
        clipped_content = _extract_tool_result_content(long_output)
        assert clipped_content is not None and len(clipped_content) == 2000
        for index, (content, output) in enumerate([
            ("same", {"output": "same"}),
            (None, {"output": ""}),
            (None, {"stdout": "é", "stderr": "bad"}),
            (None, {"output": {"image": "opaque"}}),
            (None, {"content": "claude text"}),
            (clipped_content, long_output),
        ]):
            sql.execute("INSERT INTO session_events (id, session_id, turn, sequence, event_type, call_id, tool_name, tool_input, usage, duration_ms, source_timestamp, created_at, content, tool_output) VALUES (?, 's', 1, ?, 'tool_result', ?, NULL, NULL, NULL, 0, ?, ?, ?, ?)",
                        (str(index), index, str(index), timestamp, timestamp, content, json.dumps(output)))
        event_query = db.execute.call_args_list[0].args[0]
        compiled = str(event_query.compile(dialect=sqlite.dialect(), compile_kwargs={"literal_binds": True}))
        cursor = sql.execute(compiled)
        extracted = [dict(zip([column[0] for column in cursor.description], row, strict=True)) for row in cursor.fetchall()]
        assert [row["returned_characters"] for row in extracted] == [4, 0, 4]
        assert "content" not in extracted[0] and "tool_output" not in extracted[0]
        # The query is capped at three by this test. Exercise the remaining shapes separately.
        compiled = str(event_query.limit(10).compile(dialect=sqlite.dialect(), compile_kwargs={"literal_binds": True}))
        cursor = sql.execute(compiled)
        extracted = [dict(zip([column[0] for column in cursor.description], row, strict=True)) for row in cursor.fetchall()]
        assert [row["returned_characters"] for row in extracted] == [4, 0, 4, None, 11, 10000]
        sql.execute("ALTER TABLE cost_logs ADD COLUMN api_equiv_usd REAL")
        sql.execute("ALTER TABLE cost_logs ADD COLUMN cost_usd REAL")
        sql.execute("INSERT INTO cost_logs (session_id,input_tokens,output_tokens,cache_read_tokens,cache_write_tokens,created_at) VALUES (?, 10, 20, 30, 40, ?)", ("cached", timestamp))
        cost_query = db.execute.call_args_list[1].args[0]
        compiled = str(cost_query.compile(dialect=sqlite.dialect(), compile_kwargs={"literal_binds": True}))
        assert sql.execute(compiled).fetchall() == [("cached", 80, 20, 1, None, 0, None, 0, 30, 40)]
        sql.executemany("INSERT INTO sessions VALUES (?, ?, ?)", [
            ("claude-native", "anthropic", "claude_code"),
            ("claude-legacy", "openai", "claude_code"),
            ("codex-child", "codex", "agent"),
            ("unrelated", "openai", "chat"),
        ])
        sql.execute("ALTER TABLE usage_calls ADD COLUMN api_equiv_usd REAL")
        sql.executemany("INSERT INTO usage_calls (session_id,agent_id,provider,input_tokens,cached_input_tokens,cache_write_tokens,output_tokens,occurred_at) VALUES (?, ?, ?, 10, 20, 30, 40, ?)", [
            ("claude-native", "", "claude", timestamp),
            ("claude-legacy", "", "claude", timestamp),
            ("root", "codex-child", "codex", timestamp),
            ("unrelated", "", "claude", timestamp),
        ])
        ledger_query = db.execute.call_args_list[2].args[0]
        compiled = str(ledger_query.compile(dialect=sqlite.dialect(), compile_kwargs={"literal_binds": True}))
        assert set(sql.execute(compiled).fetchall()) == {
            ("claude-legacy", 60, 40, 1, None, 0, 20, 30), ("claude-native", 60, 40, 1, None, 0, 20, 30), ("codex-child", 60, 40, 1, None, 0, 20, 30),
            (None, 60, 40, 1, None, 0, 20, 30),
        }


def test_orphan_result_and_no_call_id_runtime_keep_unknown_time_visible():
    result = snapshot([event("tool_result", call=None, tool_input=None, tool_name="Bash", seconds=5)])
    assert result["tool_time"]["denominator_seconds"] == 5
    assert buckets(result["tool_time"]["breakdown"], "seconds")["unknown"] == 5


def test_repeat_projects_and_task_drills_are_source_backed_bounded_and_counted():
    sessions = [Row(id=sid, project_id=project, provider="codex") for sid, project in (("s", "p1"), ("other", "p2"))]
    result = snapshot([
        event(call="one"), event("tool_result", call="one", seconds=5),
        event(sid="other", call="two"), event("tool_result", sid="other", call="two", seconds=10),
    ], sessions=sessions, bindings=[Row(session_id="s", project_id="p1", task_id="task-real")], limit=1)
    pattern = result["repeat_admin_patterns"][0]
    assert result["repeat_admin_patterns_total"] == 1
    assert pattern["projects_total"] == 2
    assert pattern["projects"] == [{"project_id": "p2", "calls": 1, "sessions": 1,
                                      "sample_session_id": "other", "measured_tool_seconds": 10}]
    assert result["task_rollups"][0]["sample_session_id"] == "s"
    assert result["task_rollups"][0]["project_id"] == "p1"
    assert result["tools_sampled"] == 2
    assert result["tools_missing_duration"] == 0
    assert result["unlinked_sessions"] == 1


def test_recorded_zero_duration_is_known_zero_not_missing():
    result = snapshot([
        event(call="zero"), event("tool_result", call="zero", duration_ms=0, returned_characters=0),
        event(call="missing"), event("tool_result", call="missing"),
        event(call="bad"), event("tool_result", call="bad", duration_ms=-1),
    ])
    assert result["tools_sampled"] == 3
    assert result["tools_missing_duration"] == 2
    assert result["tool_time"]["denominator_seconds"] == 0
    assert result["transcript"]["calls_with_returned_text"] == 1


def test_transcript_estimate_uses_actual_return_lengths_and_deduplicates_wrappers():
    private = "private-returned-text"
    result = snapshot([
        event(call="wrapper", tool_name="exec", tool_input={"raw": private}),
        event("tool_result", call="wrapper", returned_characters=9999),
        event(call="native", tool_input={"command": "st list", "wrapper_candidate_call_id": "wrapper", "wrapper_correlation": "nested_command_digest"}),
        event("tool_result", call="native", returned_characters=100),
        event(call="edit", tool_name="apply_patch", tool_input={"raw": "patch", "format": "opaque"}),
        event("tool_result", call="edit", returned_characters=0),
        event("tool_result", call="orphan", tool_input=None, returned_characters=40),
    ])
    transcript = result["transcript"]
    assert transcript["argument_characters"] == len('{"command":"st list"}') + len('patch')
    assert transcript["returned_characters"] == 140
    assert transcript["characters"] == transcript["argument_characters"] + 140
    assert transcript["calls_with_returned_text"] == 3
    assert buckets(transcript["breakdown"], "characters") == {
        "administration": len('{"command":"st list"}') + 100, "substantive": 5, "unknown": 40,
    }
    assert result["wrappers_excluded"] == 1
    assert private not in str(result)
    assert result["tokens"]["denominator"] == 0


def test_native_partitions_global_unmatched_coverage_and_rankings_reconcile():
    sessions = [Row(id="s", project_id="p1", provider="codex"), Row(id="old", project_id="p2", provider="anthropic")]
    result = snapshot([
        event(), event("tool_result", returned_characters=500),
    ], ledger=[
        Row(session_id="s", input_tokens=Decimal("1000"), output_tokens=20, cache_read_tokens=800, cache_write_tokens=0, calls=1),
        Row(session_id="old", input_tokens=2000, output_tokens=100, cache_read_tokens=1500, cache_write_tokens=200, calls=2),
        Row(session_id=None, input_tokens=100, output_tokens=10, cache_read_tokens=50, cache_write_tokens=0, calls=1),
    ], sessions=sessions, bindings=[Row(session_id="s", project_id="p1", task_id="t")], limit=1)
    assert result["tokens"]["denominator"] == 3230
    assert result["usage"] == {"input_tokens": 3100, "output_tokens": 130, "cache_read_tokens": 2350, "cache_write_tokens": 200, "cache_detail_input_tokens": 3100}
    assert result["unmatched_accounting_tokens"] == 110
    assert result["unmatched_accounting_calls"] == 1
    assert result["session_rankings_total"] == 2
    assert result["session_rankings"][0]["session_id"] == "old"
    assert result["project_rankings_total"] == 2
    assert result["project_rankings"][0]["project_id"] == "p2"
    task = result["task_rollups"][0]
    assert task["tokens"] == 1020
    assert task["usage"]["cache_read_tokens"] == 800
    assert task["transcript"] == result["transcript"]
    assert result["unlinked_tokens"] == 2210


def hunter_session(*, sid="s", project="neri", role="hunting", harness="pi"):
    return Row(id=sid, project_id=project, provider="openai", session_type=harness,
               created_at=NOW - timedelta(minutes=2), provider_metadata={"work_role": {
                   "id": role, "source": "test", "declared_at": NOW.isoformat(),
               }})


def hunter_usage(response, *, at=10, inp=100, out=20, **kw):
    return event("usage", at=at, usage={"scope": "response", "response_id": response,
                                       "input_tokens": inp, "output_tokens": out,
                                       "cached_input_tokens": inp // 2, "cache_write_tokens": 5, **kw})


def test_hunter_response_join_does_not_collapse_pi_user_turns_or_duplicate_usage():
    rows = [
        event(call="support", at=100, source_event_id="message:r1:0"), hunter_usage("r1", at=100, inp=100),
        event(call="read", at=90, tool_name="read", tool_input={"path": "/source/file.php"}, source_event_id="message:r2:0"),
        hunter_usage("r2", at=90, inp=200), hunter_usage("r2", at=90, inp=200),
        event(call="mixed-source", at=80, tool_name="read", tool_input={"path": "app/file.py"}, source_event_id="message:r3:0"),
        event(call="mixed-support", at=80, source_event_id="message:r3:1"), hunter_usage("r3", at=80, inp=300),
        hunter_usage("r4", at=70, inp=400),
    ]
    data = snapshot(rows, sessions=[hunter_session()])["hunter_responses"]
    assert data["responses"] == 4 and data["tokens"] == 1080
    assert data["duplicate_usage_events"] == 1
    assert data["usage"] == {"input_tokens": 1000, "output_tokens": 80, "cache_read_tokens": 500,
                             "cache_write_tokens": 20, "cache_detail_input_tokens": 1000}
    parts = {part["category"]: part for part in data["breakdown"]}
    assert {key: part["responses"] for key, part in parts.items()} == {
        "investigation_only": 1, "mixed": 1, "support_coordination": 1, "unknown": 1,
    }
    assert parts["investigation_only"]["response_share"] == 0.25
    assert parts["investigation_only"]["token_share"] == 220 / 1080
    row = data["rows"][0]
    assert row["first_observed_investigation"] == {
        "action": "source_read", "sample_response_number": 2,
        "seconds_from_first_response": 10, "input_tokens": 200,
    }
    assert row["input_per_response"] == {"first_tokens": 100, "peak_tokens": 400, "peak_sample_response_number": 4}
    fixture = Path(__file__).parents[3] / "frontend/src/__tests__/fixtures/hunter-responses.json"
    assert data == json.loads(fixture.read_text())


def test_hunter_missing_links_and_opaque_purpose_remain_unknown_and_content_free():
    secret = "PRIVATE_SYNTHETIC_BODY"
    rows = [
        event(call="unlinked", at=90, tool_name="read", tool_input={"path": f"src/{secret}.py"}),
        hunter_usage("r1", at=90),
        event(call="opaque", at=80, tool_input={"command": f"python -c '{secret}'"}, source_event_id="message:r2:0"),
        hunter_usage("r2", at=80),
        event(call="docs", at=70, tool_name="read", tool_input={"path": "AGENTS.md"}, source_event_id="message:r3:0"),
        hunter_usage("r3", at=70),
        hunter_usage("bad", at=60, output_tokens=None),
    ]
    data = snapshot(rows, sessions=[hunter_session()])["hunter_responses"]
    assert data["responses"] == 3 and data["tools_without_response"] == 1
    assert data["unusable_usage_events"] == 1
    assert buckets(data["breakdown"], "responses")["unknown"] == 3
    assert data["rows"][0]["first_observed_investigation"]["sample_response_number"] is None
    assert secret not in json.dumps(data)


def test_hunter_source_search_compounds_and_explicit_recon_invocation_are_observations():
    rows = [
        event(call="source", at=90, tool_input={"command": "rg -n symbol src"}, source_event_id="message:r1:0"),
        hunter_usage("r1", at=90),
        event(call="compound", at=80, tool_input={"command": "cat src/file.py && st context synthetic-task"}, source_event_id="message:r2:0"),
        hunter_usage("r2", at=80),
        event(call="lab", at=70, tool_input={"command": "st bugout recon run synthetic-run"}, source_event_id="message:r3:0"),
        hunter_usage("r3", at=70),
    ]
    data = snapshot(rows, sessions=[hunter_session()])["hunter_responses"]
    assert buckets(data["breakdown"], "responses") == {
        "investigation_only": 2, "mixed": 1, "support_coordination": 0, "unknown": 0,
    }
    assert data["rows"][0]["first_observed_investigation"]["action"] == "source_search"


def test_hunter_scope_is_explicit_and_non_pi_tools_are_not_joined_by_user_turn():
    sessions = [hunter_session(), hunter_session(sid="other-project", project="other"),
                hunter_session(sid="coordinator", role="coordinator"), hunter_session(sid="codex", harness="codex")]
    rows = [event(tool_name="read", tool_input={"path": "src/file.py"}, source_event_id="message:r1:0"), hunter_usage("r1")]
    rows += [usage(sid=sid, response="r") for sid in ("other-project", "coordinator", "codex")]
    rows += [event(sid="codex", call="read", tool_name="read", tool_input={"path": "src/file.py"}, source_event_id="message:r:0")]
    data = snapshot(rows, sessions=sessions)["hunter_responses"]
    assert data["sessions_total"] == 2 and data["responses"] == 2
    assert buckets(data["breakdown"], "responses")["unknown"] == 1
    assert data["tools_without_response"] == 1


def test_hunter_cutoff_and_cap_do_not_claim_a_lifetime_first_or_complete_purpose():
    rows = [
        event(at=100, call="old", tool_name="read", tool_input={"path": "old.py"}, source_event_id="message:old:0"),
        hunter_usage("old", at=100, inp=999),
        event(at=10, call="new", tool_name="read", tool_input={"path": "new.py"}, source_event_id="message:new:0"),
        hunter_usage("new", at=10, inp=200),
    ]
    data = summarize_activity_cost(rows, [], [], [hunter_session()], [],
                                   cutoff=NOW - timedelta(seconds=60), now=NOW, limit=5, truncated=True)["hunter_responses"]
    assert data["responses"] == 1 and data["events_truncated"] is True
    assert buckets(data["breakdown"], "responses")["unknown"] == 1
    row = data["rows"][0]
    assert row["window_starts_mid_session"] is True
    assert row["first_observed_investigation"]["sample_response_number"] == 1
    assert row["input_per_response"]["first_tokens"] == 200


@pytest.mark.parametrize("command", [[], "cat AGENTS.md src/file.py", "rg symbol docs src", "python -c 'opaque()'"])
def test_hunter_ambiguous_shell_invocations_stay_unknown(command):
    data = snapshot([
        event(tool_input={"command": command}, source_event_id="message:r1:0"), hunter_usage("r1"),
    ], sessions=[hunter_session()])["hunter_responses"]
    assert buckets(data["breakdown"], "responses")["unknown"] == 1
    assert data["rows"][0]["first_observed_investigation"] is None
