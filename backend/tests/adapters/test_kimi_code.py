"""Tests for Kimi Code subscription adapter."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.adapters.base import AuthenticationError
from app.adapters.kimi_code import KimiCodeAdapter
from app.adapters.types import Message


def test_kimi_code_adapter_uses_subscription_endpoint() -> None:
    adapter = KimiCodeAdapter(api_key="kc-test")

    assert adapter.provider_name == "kimi-code"
    assert adapter._get_base_url() == "https://api.kimi.com/coding/"
    assert adapter._resolve_model("kimi-code/kimi-for-coding") == "kimi-for-coding"
    assert adapter._get_default_headers() == {"User-Agent": "agent-hub/1.0"}


def test_kimi_code_adapter_requires_key() -> None:
    with pytest.raises(AuthenticationError):
        KimiCodeAdapter(api_key="")


@pytest.mark.asyncio
@patch("app.adapters.kimi_code.anthropic.AsyncAnthropic")
async def test_kimi_code_complete_uses_anthropic_protocol(mock_anthropic: MagicMock) -> None:
    mock_client = MagicMock()
    mock_client.close = AsyncMock()
    mock_client.messages.create = AsyncMock(return_value=_message_response("KIMI_OK"))
    mock_anthropic.return_value = mock_client

    adapter = KimiCodeAdapter(api_key="kc-test")
    result = await adapter.complete(
        [Message(role="user", content="Return exactly KIMI_OK.")],
        "kimi-code/kimi-for-coding",
        max_tokens=32,
        temperature=0,
    )

    assert result.content == "KIMI_OK"
    assert result.model == "kimi-for-coding"
    mock_anthropic.assert_called_once_with(
        api_key="kc-test",
        base_url="https://api.kimi.com/coding/",
        default_headers={"User-Agent": "agent-hub/1.0"},
    )
    mock_client.messages.create.assert_awaited_once()
    create_args = mock_client.messages.create.await_args
    assert create_args is not None
    assert create_args.kwargs["model"] == "kimi-for-coding"
    mock_client.close.assert_awaited_once()


@pytest.mark.asyncio
@patch("app.adapters.kimi_code.anthropic.AsyncAnthropic")
async def test_kimi_code_complete_with_tools_executes_tool_loop(mock_anthropic: MagicMock) -> None:
    mock_client = MagicMock()
    mock_client.close = AsyncMock()
    mock_client.messages.create = AsyncMock(
        side_effect=[
            _message_response("", [_tool_block("toolu_1", "read_file", {"path": "README.md"})]),
            _message_response("Done"),
        ]
    )
    mock_anthropic.return_value = mock_client
    tool_handler = AsyncMock(return_value="readme contents")

    adapter = KimiCodeAdapter(api_key="kc-test")
    events = [
        event
        async for event in adapter.complete_with_tools(
            messages=[Message(role="user", content="Read README")],
            model="kimi-code/kimi-for-coding",
            tools=[{"name": "read_file", "description": "Read file", "input_schema": {"type": "object"}}],
            tool_handler=tool_handler,
            max_turns=3,
            temperature=0,
        )
    ]

    assert [event.type for event in events] == ["tool_use", "tool_result", "content", "done"]
    tool_handler.assert_awaited_once_with("read_file", {"path": "README.md"})
    assert mock_client.messages.create.await_count == 2
    second_call_messages = mock_client.messages.create.await_args_list[1].kwargs["messages"]
    assert second_call_messages[-1]["content"] == [
        {"type": "tool_result", "tool_use_id": "toolu_1", "content": "readme contents"}
    ]


def _message_response(text: str, extra_blocks: list[SimpleNamespace] | None = None) -> SimpleNamespace:
    blocks = []
    if text:
        blocks.append(SimpleNamespace(type="text", text=text))
    blocks.extend(extra_blocks or [])
    return SimpleNamespace(
        id="msg_test",
        type="message",
        role="assistant",
        content=blocks,
        model="kimi-for-coding",
        stop_reason="end_turn",
        usage=SimpleNamespace(input_tokens=10, output_tokens=5),
    )


def _tool_block(tool_id: str, name: str, tool_input: dict[str, object]) -> SimpleNamespace:
    return SimpleNamespace(type="tool_use", id=tool_id, name=name, input=tool_input)
