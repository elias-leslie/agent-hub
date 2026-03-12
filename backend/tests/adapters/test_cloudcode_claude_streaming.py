from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.adapters.cloudcode_claude_streaming import run_tool_loop


@pytest.mark.asyncio
async def test_run_tool_loop_marks_end_turn_when_model_finishes_without_tools() -> None:
    client = AsyncMock()
    client.generate_content.return_value = {
        "response": {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {"text": "Finished cleanly."},
                        ]
                    }
                }
            ]
        }
    }

    events = []
    async for event, _session_id in run_tool_loop(
        client=client,
        resolved="claude-sonnet-4-6",
        contents=[],
        system_instruction=None,
        cc_tools=[],
        tool_config={},
        thinking_level=None,
        max_tokens=None,
        max_turns=1,
        tool_handler=AsyncMock(),
        session_id="sess-1",
    ):
        events.append(event)

    assert [event.type for event in events] == ["assistant", "result"]
    assert events[-1].finish_reason == "end_turn"
    assert events[-1].result == "Finished cleanly."


@pytest.mark.asyncio
async def test_run_tool_loop_marks_max_turns_when_budget_is_exhausted() -> None:
    client = AsyncMock()
    client.generate_content.return_value = {
        "response": {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {"text": "Step 1"},
                            {
                                "functionCall": {
                                    "id": "call-1",
                                    "name": "Bash",
                                    "args": {"command": "printf 'STEP 1\\n'"},
                                }
                            },
                        ]
                    }
                }
            ]
        }
    }
    tool_handler = AsyncMock()
    tool_handler.execute.return_value = SimpleNamespace(
        content="STEP 1\n",
        is_error=False,
        duration_ms=3,
    )

    events = []
    async for event, _session_id in run_tool_loop(
        client=client,
        resolved="claude-sonnet-4-6",
        contents=[],
        system_instruction=None,
        cc_tools=[],
        tool_config={},
        thinking_level=None,
        max_tokens=None,
        max_turns=1,
        tool_handler=tool_handler,
        session_id="sess-2",
    ):
        events.append(event)

    assert [event.type for event in events] == ["assistant", "assistant", "tool_result", "result"]
    assert events[-1].finish_reason == "max_turns"
    assert events[-1].result == "Step 1"
