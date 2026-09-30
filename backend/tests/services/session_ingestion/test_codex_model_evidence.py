"""Current native model evidence, independent of requested model routing."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.services.session_ingestion.adapters.transcript_parsers import (
    read_incremental_transcript_events,
)


def _record(kind: str, payload: dict, time: str = "2026-09-30T15:00:00Z", **extra: object) -> str:
    return json.dumps({"type": kind, "payload": payload, "timestamp": time, **extra}) + "\n"


def _evidence(checkpoint: str | None) -> dict:
    assert checkpoint is not None
    return json.loads(checkpoint)["codex_model_state"]["evidence"]


def test_incremental_latest_turn_request_is_distinct_from_observation(tmp_path: Path) -> None:
    path = tmp_path / "native.jsonl"
    first = (
        _record("session_meta", {"id": "root", "session_id": "root"})
        + _record("event_msg", {"type": "task_started", "turn_id": "turn-1"})
        + _record("turn_context", {"turn_id": "turn-1", "model": "gpt-5.4", "effort": "high"})
        + _record("response_item", {"type": "message", "role": "assistant", "model": "gpt-5.4"})
    )
    path.write_text(first)
    _, checkpoint = read_incremental_transcript_events(str(path))
    assert _evidence(checkpoint)["observed_model"] == "gpt-5.4"
    path.write_text(first + _record("event_msg", {"type": "task_started", "turn_id": "turn-2"}))
    _, checkpoint = read_incremental_transcript_events(str(path), checkpoint)
    assert _evidence(checkpoint)["turn_id"] == "turn-2"
    assert _evidence(checkpoint)["requested_model"] is None
    assert _evidence(checkpoint)["observed_model"] is None
    with path.open("a") as transcript:
        transcript.write(_record("turn_context", {"turn_id": "turn-2", "model": "gpt-6.1-sol", "effort": "high"}))
    _, checkpoint = read_incremental_transcript_events(str(path), checkpoint)
    evidence = _evidence(checkpoint)
    assert evidence["requested_model"] == "gpt-6.1-sol"
    assert evidence["requested_reasoning_effort"] == "high"
    assert evidence["observed_model"] is None
    assert evidence["source_line"] == 6
    events, unchanged = read_incremental_transcript_events(str(path), checkpoint)
    assert events == []
    assert unchanged == checkpoint
    with path.open("a") as transcript:
        transcript.write(_record("token_usage_record", {
            "session_id": "root", "thread_id": "root", "turn_id": "turn-2", "model": "gpt-6.1-sol",
        }))
    _, checkpoint = read_incremental_transcript_events(str(path), checkpoint)
    assert _evidence(checkpoint)["observed_model"] == "gpt-6.1-sol"
    assert _evidence(checkpoint)["observed_source"] == "codex.token_usage_record.model"
    assert _evidence(checkpoint)["observed_source_line"] == 7


@pytest.mark.parametrize("nested_parent", [False, True])
def test_child_excludes_inherited_context_and_conflicting_response_attribution(
    tmp_path: Path, nested_parent: bool,
) -> None:
    path = tmp_path / "child.jsonl"
    header = {"id": "child", "session_id": "root", "agent_path": "/root/child"}
    if nested_parent:
        header["source"] = {"subagent": {"thread_spawn": {"parent_thread_id": "root"}}}
    else:
        header["parent_thread_id"] = "root"
    path.write_text(
        _record("session_meta", header)
        + _record("event_msg", {"type": "task_started", "turn_id": "parent-turn"}, "2026-09-29T15:00:00Z")
        + _record("turn_context", {"turn_id": "parent-turn", "model": "inherited"}, "2026-09-29T15:00:00Z")
        + _record("turn_context", {"turn_id": "copied", "model": "copied"})
        + _record("event_msg", {"type": "task_started", "turn_id": "child-turn"})
        + _record("turn_context", {"turn_id": "child-turn", "model": "requested"})
        + _record("token_usage_record", {"thread_id": "child", "session_id": "wrong-root", "turn_id": "child-turn", "model": "wrong"})
        + _record("token_usage_record", {"thread_id": "parent", "session_id": "root", "turn_id": "child-turn", "model": "wrong"})
        + _record("token_usage_record", {"thread_id": "child", "session_id": "root", "turn_id": "parent-turn", "model": "wrong"})
    )
    _, checkpoint = read_incremental_transcript_events(str(path))
    evidence = _evidence(checkpoint)
    assert evidence["session_id"] == "child"
    assert evidence["native_session_id"] == "root"
    assert evidence["requested_model"] == "requested"
    assert evidence["observed_model"] is None


def test_ordinal_child_boundary_and_cursor_upgrade_preserve_evidence(tmp_path: Path) -> None:
    path = tmp_path / "child.jsonl"
    path.write_text(
        _record("session_meta", {"id": "child", "parent_thread_id": "root", "subagent_history_start_ordinal": 20})
        + _record("turn_context", {"turn_id": "old", "model": "parent"}, ordinal=19)
        + _record("turn_context", {"turn_id": "new", "model": "child"}, ordinal=20)
    )
    _, checkpoint = read_incremental_transcript_events(str(path))
    assert _evidence(checkpoint)["requested_model"] == "child"
    legacy = json.loads(checkpoint)
    legacy.pop("codex_model_state")
    events, upgraded = read_incremental_transcript_events(str(path), json.dumps(legacy))
    assert events == []
    assert _evidence(upgraded) == _evidence(checkpoint)


def test_rewritten_source_discards_previous_model_evidence(tmp_path: Path) -> None:
    path = tmp_path / "native.jsonl"
    path.write_text(
        _record("session_meta", {"id": "root"})
        + _record("turn_context", {"turn_id": "old", "model": "requested"})
        + _record("response_item", {"type": "reasoning", "model": "old-observed"})
    )
    _, checkpoint = read_incremental_transcript_events(str(path))
    path.write_text(_record("session_meta", {"id": "root"}))
    _, checkpoint = read_incremental_transcript_events(str(path), checkpoint)
    assert _evidence(checkpoint)["observed_model"] is None
    assert _evidence(checkpoint)["requested_model"] is None


def test_same_turn_model_change_and_missing_observation_freshness(tmp_path: Path) -> None:
    path = tmp_path / "native.jsonl"
    first = (
        _record("session_meta", {"id": "root"})
        + _record("turn_context", {"turn_id": "same", "model": "old"})
        + _record("response_item", {"type": "reasoning", "model": "old-served"})
    )
    path.write_text(first)
    _, checkpoint = read_incremental_transcript_events(str(path))
    path.write_text(first + _record("turn_context", {"turn_id": "same", "model": "gpt-6.1-sol", "effort": "high"}) + json.dumps({"type": "response_item", "payload": {"type": "reasoning", "model": "unattributed"}}) + "\n")
    _, checkpoint = read_incremental_transcript_events(str(path), checkpoint)
    assert _evidence(checkpoint)["requested_model"] == "gpt-6.1-sol"
    assert _evidence(checkpoint)["observed_model"] is None
    assert json.loads(checkpoint)["codex_model_state"]["observed_models"] == ["old-served"]
