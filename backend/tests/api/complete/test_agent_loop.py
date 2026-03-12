from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.api.complete.agent_loop import AgentLoopRequest, execute_agent_loop
from app.api.complete.types import CompletionInternalResult


def _request(**overrides) -> AgentLoopRequest:
    base = dict(
        provider="codex",
        messages_dict=[{"role": "user", "content": "hi"}],
        user_messages_for_db=[],
        model="codex/gpt-5.4",
        temperature=0.0,
        db=AsyncMock(),
        session=SimpleNamespace(),
        session_id="sess-1",
        is_new_session=True,
        loaded_memory_uuids=[],
        memory_group_id=None,
        skip_cache=True,
        progress_callback=None,
        max_turns=1,
        project_id="agent-hub",
        tools=[],
        tool_catalog=None,
        working_dir=None,
        permission_config=None,
        enable_programmatic_tools=False,
        defer_tool_loading=False,
        enable_caching=False,
        cache_ttl="ephemeral",
        thinking_level=None,
        container_id=None,
        response_format=None,
        agent_slug="refactor",
        task_type=None,
    )
    base.update(overrides)
    return AgentLoopRequest(**base)


@pytest.mark.asyncio
async def test_execute_agent_loop_routes_tools_with_resolved_turn_budget() -> None:
    tool_result = dict(
        content="done",
        model="codex/gpt-5.4",
        provider="codex",
        input_tokens=1,
        output_tokens=1,
        finish_reason="end_turn",
        session_id="sess-1",
        memory_uuids=[],
        cited_uuids=[],
    )

    with patch(
        "app.api.complete.agent_loop.route_tool_execution",
        new=AsyncMock(return_value=tool_result),
    ) as mock_route:
        result = await execute_agent_loop(_request(), should_execute_tools=True)

    assert isinstance(result, CompletionInternalResult)
    assert mock_route.await_args.kwargs["max_turns"] == 20


@pytest.mark.asyncio
async def test_execute_agent_loop_finalizes_multi_turn_results() -> None:
    final_result = SimpleNamespace(
        model_used="codex/gpt-5.4",
        fallback_used=False,
        fallback_reason=None,
    )
    exec_result = {
        "final_result": final_result,
        "final_content": "done",
        "total_input_tokens": 3,
        "total_output_tokens": 5,
        "final_finish_reason": "end_turn",
        "cited_uuids_list": [],
        "total_thinking_tokens": 0,
        "tool_calls_count": 0,
        "execution_status": "success",
        "execution_error": None,
        "current_container_id": None,
        "progress_log": [],
    }
    built = {
        "content": "done",
        "model": "codex/gpt-5.4",
        "provider": "codex",
        "input_tokens": 3,
        "output_tokens": 5,
        "finish_reason": "end_turn",
        "session_id": "sess-1",
        "memory_uuids": [],
        "cited_uuids": [],
    }

    with (
        patch(
            "app.api.complete.agent_loop.get_adapter",
            return_value=SimpleNamespace(),
        ),
        patch(
            "app.api.complete.agent_loop.execute_multi_turn",
            new=AsyncMock(return_value=exec_result),
        ),
        patch(
            "app.api.complete.agent_loop.finalize_completion_result",
            new=AsyncMock(),
        ) as mock_finalize,
        patch(
            "app.api.complete.agent_loop.build_completion_result",
            return_value=built,
        ),
    ):
        result = await execute_agent_loop(_request(), should_execute_tools=False)

    assert isinstance(result, CompletionInternalResult)
    mock_finalize.assert_awaited_once()
    assert mock_finalize.await_args.args[4] == "codex/gpt-5.4"
