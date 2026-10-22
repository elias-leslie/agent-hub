"""Native stop comparisons expose evidence and denominators, never prompt text."""

import json
from unittest.mock import AsyncMock

import pytest

from app.services.session_turn_diagnostics import native_turn_diagnostics, summarize_native_turns


@pytest.mark.unit
def test_stop_comparison_uses_native_outcomes_and_observed_setting_differences() -> None:
    rows = []
    for index, (turn, model, status) in enumerate([
        ("before", "model-a", "completed"), ("stop", "model-b", "failed"), ("after", "model-b", "completed"),
    ]):
        rows.extend([
            {"id": turn + "-settings", "event_type": "native_settings", "source_event_id": turn,
             "tool_output": {"native_turn_id": turn, "requested_model": model}},
            {"id": turn + "-terminal", "event_type": "native_lifecycle", "source_event_id": turn,
             "source_timestamp": f"2026-10-22T00:00:0{index}Z",
             "tool_output": {"native_turn_id": turn, "status": status,
                             **({"native_category": "cyber_policy"} if status == "failed" else {})}},
        ])
    # A cumulative usage counter and unbacked hook error are not terminal turns.
    rows.extend([{"id": "counter", "event_type": "usage_counter", "usage": {"scope": "thread", "input_tokens": 100}},
                 {"id": "hook", "event_type": "error", "tool_output": {"turn_id": "unbacked", "codex_error_info": "other"}}])
    result = summarize_native_turns(rows, limit=20)
    assert result["denominator"] == 3
    assert result["categories"] == [{"category": "completed", "turns": 2, "rate": 2 / 3}, {"category": "cyber_policy", "turns": 1, "rate": 1 / 3}]
    stopped = result["turns"][1]
    assert stopped["classifier_cause"] == "unknown"
    assert stopped["nearby_turns"][0]["observed_setting_differences"] == {
        "requested_model": {"this_turn": "model-b", "nearby_turn": "model-a"},
    }
    assert stopped["nearby_turns"][1]["observed_setting_differences"] == {}


@pytest.mark.unit
@pytest.mark.asyncio
async def test_managed_comparison_reads_registered_source_without_projecting_commands(tmp_path) -> None:
    path = tmp_path / "native.jsonl"
    path.write_text("".join(json.dumps(record) + "\n" for record in [
        {"type": "event_msg", "payload": {"type": "task_complete", "turn_id": "completed"}},
        {"type": "event_msg", "payload": {"type": "task_complete", "turn_id": "failed",
         "error": {"message": "Native stop", "codex_error_info": "cyber_policy"}}},
    ]))
    db = AsyncMock()
    result = await native_turn_diagnostics(db, "managed", limit=20, event_limit=100, managed_transcript=str(path))
    assert result["denominator"] == 2
    assert result["source"] == "registered_native_transcript"
    assert result["categories"][1]["rate"] == 0.5
    db.execute.assert_not_awaited()
    missing = await native_turn_diagnostics(db, "managed", limit=20, event_limit=100, managed_transcript=str(tmp_path / "missing.jsonl"))
    assert missing["denominator"] == 0
    assert missing["source_health"]["state"] == "blocked"
