"""Tests for transcript-to-normalized-event parsing."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.services.session_ingestion.adapters.transcript_parsers import (
    parse_transcript_events,
    read_incremental_transcript_events,
    read_jsonl_lines,
)


@pytest.mark.unit
class TestParseTranscriptEvents:
    """Tests for parsing Claude and Codex JSONL transcripts."""

    def test_parses_claude_transcript_into_stable_turns(self) -> None:
        lines = [
            '{"type":"user","message":{"role":"user","content":"Inspect hooks"}}',
            '{"type":"assistant","message":{"role":"assistant","content":[{"type":"text","text":"Tracing now"},{"type":"tool_use","name":"Read","input":{"file_path":"/tmp/x.py"}}]}}',
            '{"type":"user","message":{"role":"user","content":"Patch it"}}',
            '{"type":"assistant","message":{"role":"assistant","content":[{"type":"text","text":"Done"}]}}',
        ]

        events = parse_transcript_events(lines)

        assert [(event.event_type, event.turn, event.sequence) for event in events] == [
            ("user_message", 1, 1),
            ("assistant_message", 1, 2),
            ("tool_use", 1, 3),
            ("user_message", 2, 1),
            ("assistant_message", 2, 2),
        ]

    def test_parses_codex_transcript_into_normalized_events(self) -> None:
        lines = [
            '{"type":"response_item","payload":{"type":"message","role":"user","content":[{"type":"input_text","text":"Review parser"}]}}',
            '{"type":"response_item","payload":{"type":"message","role":"assistant","content":[{"type":"output_text","text":"Tracing now"}]}}',
            '{"type":"response_item","payload":{"type":"function_call","name":"exec_command","arguments":"{\\"cmd\\":\\"git status\\"}"}}',
            '{"type":"response_item","payload":{"type":"function_call_output","output":"M backend/app.py"}}',
        ]

        events = parse_transcript_events(lines)

        assert [(event.event_type, event.turn, event.sequence) for event in events] == [
            ("user_message", 1, 1),
            ("assistant_message", 1, 2),
            ("tool_use", 1, 3),
            ("tool_result", 1, 4),
        ]
        assert events[2].tool_name == "exec_command"
        assert events[3].content == "M backend/app.py"

    def test_native_web_and_browser_calls_get_informational_hints(self) -> None:
        calls = [
            {"type": "custom_tool_call", "name": "exec", "call_id": "web-1",
             "input": "const result = await tools.web__run({search_query: [{q: 'docs'}]});"},
            {"type": "function_call", "name": "js", "call_id": "browser-1",
             "arguments": json.dumps({"code": "let state = await cua.getState();", "title": "Inspect tab"})},
            {"type": "function_call", "name": "js", "call_id": "browser-2",
             "arguments": json.dumps({"code": "let state = await tab.playwright.domSnapshot();", "title": "Inspect DOM"})},
            {"type": "custom_tool_call", "name": "exec", "call_id": "other-1",
             "input": "The user mentioned web__run in prose."},
        ]
        events = parse_transcript_events([
            json.dumps({"type": "response_item", "payload": call}) for call in calls
        ])

        assert [event.tool_name for event in events] == ["exec", "js", "js", "exec"]
        assert events[0].tool_input == {
            "raw": calls[0]["input"], "format": "opaque", "call_id": "web-1",
            "native_tool_hints": ["web__run"],
        }
        assert events[1].tool_input == {
            "code": "let state = await cua.getState();", "title": "Inspect tab",
            "call_id": "browser-1", "native_tool_hints": ["mcp__cua_repl.js"],
        }
        assert events[2].tool_input == {
            "code": "let state = await tab.playwright.domSnapshot();", "title": "Inspect DOM",
            "call_id": "browser-2", "native_tool_hints": ["mcp__cua_repl.js"],
        }
        assert events[3].tool_input == {
            "raw": calls[3]["input"], "format": "opaque", "call_id": "other-1",
        }

    def test_native_command_execution_keeps_exact_span_and_wrapper(self) -> None:
        lines = [
            json.dumps({
                "type": "response_item", "timestamp": "2026-09-28T16:48:15Z",
                "payload": {"type": "custom_tool_call", "id": "outer-start",
                            "name": "exec", "call_id": "call-outer", "input": "run"},
            }),
            json.dumps({
                "type": "event_msg", "timestamp": "2026-09-28T16:48:17Z",
                "payload": {
                    "type": "item_completed", "started_at_ms": 1_790_614_095_812,
                    "completed_at_ms": 1_790_614_096_886,
                    "item": {
                        "type": "CommandExecution", "id": "exec-native", "status": "completed",
                        "command": ["/bin/bash", "-lc", "printf done"],
                        "cwd": "file:///workspace", "source": "unified_exec_startup",
                        "stdout": "done", "stderr": "", "exit_code": 0,
                    },
                },
            }),
            json.dumps({
                "type": "response_item", "timestamp": "2026-09-28T16:48:19Z",
                "payload": {"type": "custom_tool_call_output", "id": "outer-result",
                            "call_id": "call-outer", "output": "done"},
            }),
        ]

        events = parse_transcript_events(lines)

        assert [event.event_type for event in events] == [
            "tool_use", "tool_use", "tool_result", "tool_result"
        ]
        native_start, native_result = events[1:3]
        assert native_start.call_id == native_result.call_id == "exec-native"
        assert native_start.tool_name == "Bash"
        assert native_start.tool_input == {
            "command": ["/bin/bash", "-lc", "printf done"],
            "cwd": "file:///workspace",
            "source": "unified_exec_startup",
            "wrapper_candidate_call_id": "call-outer",
            "wrapper_correlation": "single_open_exec",
        }
        assert native_result.tool_output == {
            "stdout": "done", "stderr": "", "status": "completed",
            "exit_code": 0, "is_error": False,
        }
        assert native_result.duration_ms == 1074
        assert native_start.source_timestamp is not None
        assert native_result.source_timestamp is not None
        assert native_start.source_timestamp.isoformat() == "2026-09-28T16:48:15.812000+00:00"
        assert native_result.source_timestamp.isoformat() == "2026-09-28T16:48:16.886000+00:00"
        assert native_start.source_event_id is not None
        assert native_result.source_event_id is not None
        assert native_start.source_event_id.startswith("event_msg:exec-native:")
        assert native_start.source_event_id.endswith(":1")
        assert native_result.source_event_id.endswith(":2")

    def test_native_command_conflict_and_incomplete_record_remain_visible(self) -> None:
        def command(stdout: str) -> str:
            return json.dumps({
                "type": "event_msg", "timestamp": "2026-09-28T16:48:17Z",
                "payload": {
                    "type": "item_completed", "started_at_ms": 1_790_614_095_812,
                    "completed_at_ms": 1_790_614_096_886,
                    "item": {
                        "type": "CommandExecution", "id": "exec-conflict",
                        "command": "true", "status": "completed", "exit_code": 0,
                        "stdout": stdout, "stderr": "",
                    },
                },
            })
        malformed = json.dumps({
            "type": "event_msg", "timestamp": "2026-09-28T16:48:20Z",
            "payload": {"type": "item_completed", "item": {
                "type": "CommandExecution", "id": "exec-incomplete",
                "command": "true", "status": "completed", "exit_code": 0,
            }},
        })
        null_output = json.dumps({
            "type": "event_msg", "timestamp": "2026-09-28T16:48:21Z",
            "payload": {"type": "item_completed", "started_at_ms": 1_790_614_095_812,
                        "completed_at_ms": 1_790_614_096_886, "item": {
                "type": "CommandExecution", "id": "exec-null-output",
                "command": "true", "status": "completed", "exit_code": 0,
                "stdout": None, "stderr": None,
            }},
        })
        non_finite_time = json.dumps({
            "type": "event_msg", "timestamp": "2026-09-28T16:48:22Z",
            "payload": {"type": "item_completed", "started_at_ms": float("inf"),
                        "completed_at_ms": float("inf"), "item": {
                "type": "CommandExecution", "id": "exec-bad-time",
                "command": "true", "status": "completed", "exit_code": 0,
                "stdout": "", "stderr": "",
            }},
        })

        events = parse_transcript_events([
            command("one"), command("two"), malformed, null_output, non_finite_time
        ])

        conflict_starts = [event for event in events if event.call_id == "exec-conflict"
                           and event.event_type == "tool_use"]
        assert len(conflict_starts) == 2
        assert conflict_starts[0].source_event_id != conflict_starts[1].source_event_id
        errors = [event.content for event in events if event.event_type == "error"]
        assert errors == [
            "Native command execution exec-incomplete has invalid timestamps.",
            "Native command execution exec-incomplete is missing its output.",
            "Native command execution exec-null-output is missing its output.",
            "Native command execution exec-bad-time has invalid timestamps.",
        ]

    def test_parses_claude_progress_subagent_events_with_models_and_tool_results(self) -> None:
        lines = [
            '{"type":"user","message":{"role":"user","content":"Inspect adapters"}}',
            '{"type":"assistant","message":{"model":"claude-sonnet-4-6","role":"assistant","content":[{"type":"tool_use","name":"Agent","input":{"description":"delegate"}}]}}',
            '{"type":"progress","slug":"sparkling-dancing-peach","data":{"type":"agent_progress","agentId":"agent-1","message":{"type":"user","message":{"role":"user","content":[{"type":"text","text":"Read the file"},{"type":"tool_result","tool_use_id":"toolu_1","content":"read ok"}]}}}}',
            '{"type":"progress","slug":"sparkling-dancing-peach","data":{"type":"agent_progress","agentId":"agent-1","message":{"type":"assistant","message":{"model":"claude-opus-4-6","role":"assistant","content":[{"type":"thinking","thinking":"Checking file"},{"type":"tool_use","name":"Read","input":{"file_path":"/tmp/x.py"}},{"type":"text","text":"Done"}]}}}}',
            '{"type":"assistant","message":{"model":"claude-sonnet-4-6","role":"assistant","content":[{"type":"text","text":"Finished"}]}}',
        ]

        events = parse_transcript_events(lines)

        assert [(event.event_type, event.turn, event.sequence) for event in events] == [
            ("user_message", 1, 1),
            ("tool_use", 1, 2),
            ("tool_result", 1, 3),
            ("thinking", 1, 4),
            ("tool_use", 1, 5),
            ("assistant_message", 1, 6),
            ("assistant_message", 1, 7),
        ]
        assert events[1].tool_name == "Agent"
        assert events[1].model_used == "claude-sonnet-4-6"
        assert events[2].content == "read ok"
        assert events[2].agent_id == "agent-1"
        assert events[2].agent_name == "sparkling-dancing-peach"
        assert events[3].content == "Checking file"
        assert events[3].model_used == "claude-opus-4-6"
        assert events[4].tool_name == "Read"
        assert events[4].tool_input == {"file_path": "/tmp/x.py"}
        assert events[4].agent_id == "agent-1"
        assert events[5].content == "Done"
        assert events[5].model_used == "claude-opus-4-6"
        assert events[6].content == "Finished"
        assert events[6].model_used == "claude-sonnet-4-6"


@pytest.mark.unit
def test_read_jsonl_lines_respects_line_offset_checkpoint(tmp_path: Path) -> None:
    transcript = tmp_path / "session.jsonl"
    transcript.write_text("one\ntwo\nthree\n")

    lines, checkpoint = read_jsonl_lines(str(transcript), checkpoint="1")

    assert lines == ["two", "three"]
    assert checkpoint == "3"


@pytest.mark.unit
def test_read_incremental_transcript_events_preserves_turns_and_sequences(tmp_path: Path) -> None:
    transcript = tmp_path / "session.jsonl"
    transcript.write_text(
        "\n".join(
            [
                '{"type":"response_item","payload":{"type":"message","role":"user","content":[{"type":"input_text","text":"Review parser"}]}}',
                '{"type":"response_item","payload":{"type":"message","role":"assistant","content":[{"type":"output_text","text":"Tracing now"}]}}',
            ]
        )
        + "\n"
    )

    first_events, first_checkpoint = read_incremental_transcript_events(str(transcript))

    transcript.write_text(
        "\n".join(
            [
                '{"type":"response_item","payload":{"type":"message","role":"user","content":[{"type":"input_text","text":"Review parser"}]}}',
                '{"type":"response_item","payload":{"type":"message","role":"assistant","content":[{"type":"output_text","text":"Tracing now"}]}}',
                '{"type":"response_item","payload":{"type":"function_call","name":"exec_command","arguments":"{\\"cmd\\":\\"git status\\"}"}}',
                '{"type":"response_item","payload":{"type":"function_call_output","output":"M backend/app.py"}}',
                '{"type":"response_item","payload":{"type":"message","role":"user","content":[{"type":"input_text","text":"Patch it"}]}}',
                '{"type":"response_item","payload":{"type":"message","role":"assistant","content":[{"type":"output_text","text":"Done"}]}}',
            ]
        )
        + "\n"
    )

    second_events, second_checkpoint = read_incremental_transcript_events(
        str(transcript),
        checkpoint=first_checkpoint,
    )

    assert [(event.event_type, event.turn, event.sequence) for event in first_events] == [
        ("user_message", 1, 1),
        ("assistant_message", 1, 2),
    ]
    assert [(event.event_type, event.turn, event.sequence) for event in second_events] == [
        ("tool_use", 1, 3),
        ("tool_result", 1, 4),
        ("user_message", 2, 1),
        ("assistant_message", 2, 2),
    ]
    first_state = json.loads(first_checkpoint or "{}")
    second_state = json.loads(second_checkpoint or "{}")
    assert {key: first_state[key] for key in ("line_offset", "saw_content", "sequence", "turn")} == {
        "line_offset": 2, "saw_content": True, "sequence": 2, "turn": 1,
    }
    assert {key: second_state[key] for key in ("line_offset", "saw_content", "sequence", "turn")} == {
        "line_offset": 6, "saw_content": True, "sequence": 2, "turn": 2,
    }
    assert first_state["byte_offset"] < second_state["byte_offset"]
    assert first_state["inode"] == second_state["inode"]


@pytest.mark.unit
def test_incremental_native_execution_keeps_exact_wrapper_across_reads(tmp_path: Path) -> None:
    transcript = tmp_path / "native.jsonl"
    wrapper = {
        "type": "response_item", "ordinal": 1,
        "payload": {"type": "custom_tool_call", "id": "outer-start",
                    "name": "exec", "call_id": "call-outer", "input": "run"},
    }
    command = {
        "type": "event_msg", "ordinal": 2,
        "payload": {
            "type": "item_completed", "started_at_ms": 1_790_614_095_812,
            "completed_at_ms": 1_790_614_096_886,
            "item": {"type": "CommandExecution", "id": "exec-native",
                     "command": "true", "status": "completed", "exit_code": 0,
                     "stdout": "", "stderr": ""},
        },
    }
    result = {
        "type": "response_item", "ordinal": 3,
        "payload": {"type": "custom_tool_call_output", "id": "outer-result",
                    "call_id": "call-outer", "output": "done"},
    }
    transcript.write_text(json.dumps(wrapper) + "\n")

    first, checkpoint = read_incremental_transcript_events(str(transcript))
    with transcript.open("a") as output:
        output.write(json.dumps(command) + "\n" + json.dumps(result) + "\n")
    second, next_checkpoint = read_incremental_transcript_events(str(transcript), checkpoint)
    replay, replay_checkpoint = read_incremental_transcript_events(
        str(transcript), next_checkpoint
    )

    assert first[0].call_id == "call-outer"
    assert json.loads(checkpoint or "{}")["active_exec_call_ids"] == ["call-outer"]
    assert second[0].tool_input is not None
    assert second[0].tool_input["wrapper_candidate_call_id"] == "call-outer"
    assert second[0].call_id == second[1].call_id == "exec-native"
    assert json.loads(next_checkpoint or "{}")["active_exec_call_ids"] == []
    assert replay == []
    assert replay_checkpoint == next_checkpoint


@pytest.mark.unit
def test_read_incremental_transcript_events_replays_legacy_checkpoint_from_start(tmp_path: Path) -> None:
    transcript = tmp_path / "session.jsonl"
    transcript.write_text(
        "\n".join(
            [
                '{"type":"response_item","payload":{"type":"message","role":"user","content":[{"type":"input_text","text":"Review parser"}]}}',
                '{"type":"response_item","payload":{"type":"message","role":"assistant","content":[{"type":"output_text","text":"Tracing now"}]}}',
                '{"type":"response_item","payload":{"type":"function_call","name":"exec_command","arguments":"{\\"cmd\\":\\"git status\\"}"}}',
                '{"type":"response_item","payload":{"type":"function_call_output","output":"M backend/app.py"}}',
            ]
        )
        + "\n"
    )

    events, checkpoint = read_incremental_transcript_events(str(transcript), checkpoint="2")

    assert [(event.event_type, event.turn, event.sequence) for event in events] == [
        ("user_message", 1, 1),
        ("assistant_message", 1, 2),
        ("tool_use", 1, 3),
        ("tool_result", 1, 4),
    ]
    state = json.loads(checkpoint or "{}")
    assert {key: state[key] for key in ("line_offset", "saw_content", "sequence", "turn")} == {
        "line_offset": 4, "saw_content": True, "sequence": 4, "turn": 1,
    }


@pytest.mark.unit
def test_codex_custom_call_result_and_response_usage_keep_source_evidence(tmp_path: Path) -> None:
    transcript = tmp_path / "native.jsonl"
    records = [
        {"type": "response_item", "timestamp": "2026-09-23T15:00:00Z", "ordinal": 1,
         "payload": {"type": "custom_tool_call", "id": "item-call", "call_id": "call-7",
                     "name": "functions.exec", "input": "{\"cmd\":\"pwd\"}"}},
        {"type": "response_item", "timestamp": "2026-09-23T15:00:01Z", "ordinal": 2,
         "payload": {"type": "custom_tool_call_output", "id": "item-result", "call_id": "call-7",
                     "output": [{"type": "input_text", "text": "done"}, {"type": "image", "data": "opaque"}]}},
        {"type": "token_usage_record", "timestamp": "2026-09-23T15:00:02Z", "ordinal": 3,
         "payload": {"response_id": "resp-7", "turn_id": "turn-1", "root_turn_id": "root-1",
                     "usage": {"input_tokens": 100, "cached_input_tokens": 60,
                               "cache_write_input_tokens": 0, "output_tokens": 20},
                     "turn_token_usage": {"input_tokens": 100, "output_tokens": 20},
                     "thread_token_usage": {"input_tokens": 100, "output_tokens": 20}}},
        {"type": "event_msg", "timestamp": "2026-09-23T15:00:03Z", "ordinal": 4,
         "payload": {"type": "token_count", "info": {
             "last_token_usage": {"input_tokens": 100, "output_tokens": 20},
             "total_token_usage": {"input_tokens": 100, "output_tokens": 20}}}},
    ]
    transcript.write_text("\n".join(json.dumps(record) for record in records[:1]) + "\n")
    first, checkpoint = read_incremental_transcript_events(str(transcript))
    with transcript.open("a") as output:
        output.write("\n".join(json.dumps(record) for record in records[1:]) + "\n")
    second, next_checkpoint = read_incremental_transcript_events(str(transcript), checkpoint)
    replay, replay_checkpoint = read_incremental_transcript_events(str(transcript), next_checkpoint)

    assert [event.event_type for event in first + second] == [
        "tool_use", "tool_result", "usage", "usage_counter", "usage_counter", "usage_counter"
    ]
    assert first[0].tool_input == {"cmd": "pwd", "call_id": "call-7"}
    assert first[0].call_id == second[0].call_id == "call-7"
    assert second[0].tool_output == {"output": "done", "opaque_blocks": 1, "call_id": "call-7"}
    assert first[0].source_event_id == "response_item:item-call:1"
    assert second[0].source_event_id == "response_item:item-result:1"
    assert second[1].source_event_id == "response_usage:resp-7:1"
    assert second[1].source_timestamp is not None
    assert second[1].source_timestamp.isoformat() == "2026-09-23T15:00:02+00:00"
    assert second[1].usage == {
        "scope": "response", "source": "codex.token_usage_record.usage",
        "input_tokens": 100, "cached_input_tokens": 60, "cache_write_input_tokens": 0,
        "output_tokens": 20, "response_id": "resp-7", "turn_id": "turn-1", "root_turn_id": "root-1",
    }
    assert all(event.usage and event.usage["scope"] != "response" for event in second[2:])
    assert replay == []
    assert replay_checkpoint == next_checkpoint


@pytest.mark.unit
def test_incremental_reader_waits_for_complete_line_and_survives_rotation(tmp_path: Path) -> None:
    transcript = tmp_path / "native.jsonl"
    first_line = json.dumps({"type": "response_item", "ordinal": 1, "payload": {
        "type": "message", "role": "user", "content": [{"type": "input_text", "text": "first"}]}})
    second_line = json.dumps({"type": "response_item", "ordinal": 2, "payload": {
        "type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "second"}]}})
    transcript.write_text(first_line + "\n" + second_line[:35])
    first, checkpoint = read_incremental_transcript_events(str(transcript))
    assert [event.content for event in first] == ["first"]
    with transcript.open("a") as output:
        output.write(second_line[35:] + "\n")
    second, checkpoint = read_incremental_transcript_events(str(transcript), checkpoint)
    assert [event.content for event in second] == ["second"]
    assert second[0].sequence == 2

    transcript.rename(tmp_path / "native.old.jsonl")
    transcript.write_text(first_line.replace("first", "new turn") + "\n")
    rotated, checkpoint = read_incremental_transcript_events(str(transcript), checkpoint)
    assert [event.content for event in rotated] == ["new turn"]
    assert rotated[0].turn == 2
    assert rotated[0].source_event_id != first[0].source_event_id

    transcript.write_text(second_line + "\n")  # in-place truncation
    truncated, _ = read_incremental_transcript_events(str(transcript), checkpoint)
    assert [event.content for event in truncated] == ["second"]


@pytest.mark.unit
def test_rewritten_same_inode_and_ordinal_has_distinct_source_identity(tmp_path: Path) -> None:
    transcript = tmp_path / "native.jsonl"
    def record(content: str) -> str:
        return json.dumps({"type": "response_item", "ordinal": 1, "payload": {
            "type": "message", "role": "assistant",
            "content": [{"type": "output_text", "text": content}],
        }}) + "\n"

    transcript.write_text(record("original long content"))
    original, checkpoint = read_incremental_transcript_events(str(transcript))
    transcript.write_text(record("replacement"))
    replacement, _ = read_incremental_transcript_events(str(transcript), checkpoint)

    assert [event.content for event in replacement] == ["replacement"]
    assert original[0].source_event_id != replacement[0].source_event_id


@pytest.mark.unit
def test_legacy_json_checkpoint_keeps_existing_sequence_when_usage_precedes_it(tmp_path: Path) -> None:
    transcript = tmp_path / "native.jsonl"
    records = [
        {"type": "response_item", "payload": {"type": "message", "role": "user",
         "content": [{"type": "input_text", "text": "before"}]}},
        {"type": "token_usage_record", "payload": {"response_id": "old",
         "usage": {"input_tokens": 10, "output_tokens": 2}}},
        {"type": "response_item", "payload": {"type": "message", "role": "assistant",
         "content": [{"type": "output_text", "text": "after"}]}},
    ]
    transcript.write_text("\n".join(json.dumps(record) for record in records) + "\n")
    old_checkpoint = json.dumps({"line_offset": 2, "turn": 1, "sequence": 1, "saw_content": True})

    events, checkpoint = read_incremental_transcript_events(str(transcript), old_checkpoint)

    assert [(event.content, event.sequence) for event in events] == [("after", 2)]
    assert json.loads(checkpoint or "{}")["byte_offset"] > 0


@pytest.mark.unit
def test_legacy_json_checkpoint_resets_state_after_truncation(tmp_path: Path) -> None:
    transcript = tmp_path / "native.jsonl"
    transcript.write_text(json.dumps({
        "type": "response_item", "ordinal": 1,
        "payload": {"type": "message", "role": "user",
                    "content": [{"type": "input_text", "text": "replacement file"}]},
    }) + "\n")
    old_checkpoint = json.dumps({
        "line_offset": 8, "turn": 5, "sequence": 9, "saw_content": True,
        "history_start_ordinal": 100, "parent_thread_id": "old-parent",
    })

    events, checkpoint = read_incremental_transcript_events(str(transcript), old_checkpoint)

    assert [(event.content, event.turn, event.sequence) for event in events] == [
        ("replacement file", 1, 1)
    ]
    state = json.loads(checkpoint or "{}")
    assert state["line_offset"] == 1
    assert state["history_start_ordinal"] is None
    assert state["parent_thread_id"] is None


@pytest.mark.unit
def test_child_transcript_excludes_inherited_usage_and_keeps_parent_provenance(tmp_path: Path) -> None:
    transcript = tmp_path / "child.jsonl"
    records = [
        {"type": "session_meta", "ordinal": 0, "payload": {
            "parent_thread_id": "parent-thread", "subagent_history_start_ordinal": 3}},
        {"type": "token_usage_record", "ordinal": 1, "payload": {
            "response_id": "inherited", "usage": {"input_tokens": 500}}},
        {"type": "response_item", "ordinal": 2, "payload": {"type": "message", "role": "assistant",
            "content": [{"type": "output_text", "text": "inherited answer"}]}},
        {"type": "token_usage_record", "ordinal": 3, "payload": {
            "response_id": "own", "usage": {"input_tokens": 100, "output_tokens": 5}}},
    ]
    transcript.write_text("\n".join(json.dumps(record) for record in records[:3]) + "\n")
    first, checkpoint = read_incremental_transcript_events(str(transcript))
    with transcript.open("a") as output:
        output.write(json.dumps(records[3]) + "\n")
    second, checkpoint = read_incremental_transcript_events(str(transcript), checkpoint)

    assert first == []
    assert [event.event_type for event in second] == ["usage"]
    assert second[0].usage == {
        "scope": "response", "source": "codex.token_usage_record.usage",
        "input_tokens": 100, "output_tokens": 5,
        "response_id": "own", "parent_thread_id": "parent-thread",
    }
    assert json.loads(checkpoint or "{}")["history_start_ordinal"] == 3
