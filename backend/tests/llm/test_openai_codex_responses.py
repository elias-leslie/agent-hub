from __future__ import annotations

import json

from app.llm.providers.openai_codex_responses import _input_from_context
from app.llm.types import AssistantMessage, Context, TextContent, ToolCall, ToolResultMessage, Usage


def _assistant(content, *, response_id: str | None = None) -> AssistantMessage:
    return AssistantMessage(
        content=content,
        api="openai-codex-responses",
        provider="openai-codex",
        model="gpt-5.4",
        usage=Usage(),
        stop_reason="stop",
        timestamp=123,
        response_id=response_id,
    )


def test_replayed_assistant_text_never_uses_response_id_as_message_id() -> None:
    items, _instructions = _input_from_context(
        Context(
            messages=[
                _assistant(
                    [TextContent(text="done")],
                    response_id="resp_03a5f5ea998ae73a016a0524a7e0508191931dd30c385d52a7",
                )
            ]
        )
    )

    assert items[0]["type"] == "message"
    assert items[0]["id"] == "msg_123"


def test_replayed_assistant_text_uses_text_signature_message_id() -> None:
    signature = json.dumps({"v": 1, "id": "msg_keep", "phase": "final_answer"})

    items, _instructions = _input_from_context(
        Context(messages=[_assistant([TextContent(text="done", text_signature=signature)])])
    )

    assert items[0]["id"] == "msg_keep"
    assert items[0]["phase"] == "final_answer"


def test_replayed_codex_tool_ids_use_call_id_and_item_id_parts() -> None:
    items, _instructions = _input_from_context(
        Context(
            messages=[
                _assistant([ToolCall(id="call_123|fc_456", name="read_file", arguments={"path": "a.py"})]),
                ToolResultMessage(
                    tool_call_id="call_123|fc_456",
                    tool_name="read_file",
                    content=[TextContent(text="ok")],
                    is_error=False,
                    timestamp=124,
                ),
            ]
        )
    )

    assert items[0]["type"] == "function_call"
    assert items[0]["call_id"] == "call_123"
    assert items[0]["id"] == "fc_456"
    assert items[1]["type"] == "function_call_output"
    assert items[1]["call_id"] == "call_123"
