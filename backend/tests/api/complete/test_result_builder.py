from __future__ import annotations

from types import SimpleNamespace

from app.api.complete.result_builder import build_completion_result
from app.api.complete.tool_models import AgentProgress


def test_build_completion_result_prefers_explicit_final_result_turns() -> None:
    result = build_completion_result(
        final_content="done",
        model="claude-sonnet-4-6",
        provider="claude",
        total_input_tokens=10,
        total_output_tokens=5,
        final_finish_reason="max_turns",
        final_session_id="sess-1",
        loaded_memory_uuids=[],
        cited_uuids_list=[],
        total_thinking_tokens=None,
        tool_calls_count=4,
        execution_status="success",
        execution_error=None,
        current_container_id=None,
        progress_log=[
            AgentProgress(turn=1, status="tool_use", message="one"),
            AgentProgress(turn=2, status="tool_use", message="two"),
        ],
        final_result=SimpleNamespace(turns=6),
    )

    assert result["turns"] == 6


def test_build_completion_result_falls_back_to_highest_logged_turn() -> None:
    result = build_completion_result(
        final_content="done",
        model="claude-sonnet-4-6",
        provider="claude",
        total_input_tokens=10,
        total_output_tokens=5,
        final_finish_reason="end_turn",
        final_session_id="sess-2",
        loaded_memory_uuids=[],
        cited_uuids_list=[],
        total_thinking_tokens=None,
        tool_calls_count=2,
        execution_status="success",
        execution_error=None,
        current_container_id=None,
        progress_log=[
            AgentProgress(turn=1, status="tool_use", message="one"),
            AgentProgress(turn=4, status="complete", message="done"),
        ],
        final_result=None,
    )

    assert result["turns"] == 4
