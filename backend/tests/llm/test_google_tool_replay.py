from __future__ import annotations

import base64
from dataclasses import replace

import pytest
from google.genai import types as google_types

from app.llm.model_resolver import resolve_llm_model
from app.llm.provider_support.google_shared import convert_messages, requires_tool_call_id
from app.llm.providers.google import _part_to_dict
from app.llm.types import (
    AssistantMessage,
    Context,
    TextContent,
    ToolCall,
    ToolResultMessage,
    Usage,
    UserMessage,
)


@pytest.mark.parametrize("signature", [b"abc", b"abcd"])
def test_google_part_normalizes_sdk_thought_signature_bytes(signature: bytes) -> None:
    part = google_types.Part(
        function_call=google_types.FunctionCall(
            id="call-1",
            name="default_api:bash",
            args={"command": "true"},
        ),
        thought_signature=signature,
    )

    normalized = _part_to_dict(part)

    assert normalized["thought_signature"] == base64.b64encode(signature).decode("ascii")


def test_google_part_preserves_string_thought_signature() -> None:
    part = {"text": "done", "thought_signature": "YWJj"}

    assert _part_to_dict(part) == part


def test_gemini3_tool_round_trip_replays_signature_and_exact_ids() -> None:
    model = resolve_llm_model("gemini-3.5-flash", "gemini")
    signature_bytes = b"opaque-google-thought"
    parsed_part = _part_to_dict(
        google_types.Part(
            function_call=google_types.FunctionCall(
                id="call-123",
                name="default_api:bash",
                args={"command": "true"},
            ),
            thought_signature=signature_bytes,
        )
    )
    assistant = AssistantMessage(
        content=[
            ToolCall(
                id="call-123",
                name="default_api:bash",
                arguments={"command": "true"},
                thought_signature=parsed_part["thought_signature"],
            )
        ],
        api=model.api,
        provider=model.provider,
        model=model.id,
        usage=Usage(),
        stop_reason="toolUse",
        timestamp=0,
    )
    tool_result = ToolResultMessage(
        tool_call_id="call-123",
        tool_name="default_api:bash",
        content=[TextContent(text="ok")],
        is_error=False,
        timestamp=0,
    )
    context = Context(
        messages=[
            UserMessage(content="Run a harmless command.", timestamp=0),
            assistant,
            tool_result,
        ]
    )

    contents = convert_messages(model, context)
    function_call_part = contents[1]["parts"][0]
    function_response_part = contents[2]["parts"][0]

    assert function_call_part == {
        "function_call": {
            "id": "call-123",
            "name": "default_api:bash",
            "args": {"command": "true"},
        },
        "thought_signature": base64.b64encode(signature_bytes).decode("ascii"),
    }
    assert function_response_part["function_response"]["id"] == "call-123"
    assert (
        google_types.Part.model_validate(function_call_part).thought_signature
        == signature_bytes
    )


def test_google_drops_thought_signature_across_models_but_keeps_gemini3_id() -> None:
    source_model = resolve_llm_model("gemini-3.5-flash", "gemini")
    target_model = replace(source_model, id="gemini-3.1-pro-preview")
    assistant = AssistantMessage(
        content=[
            ToolCall(
                id="call.foreign/1",
                name="default_api:bash",
                arguments={},
                thought_signature="YWJj",
            )
        ],
        api=source_model.api,
        provider=source_model.provider,
        model=source_model.id,
        usage=Usage(),
        stop_reason="toolUse",
        timestamp=0,
    )

    part = convert_messages(target_model, Context(messages=[assistant]))[0]["parts"][0]

    assert "thought_signature" not in part
    assert part["function_call"]["id"] == "call.foreign/1"


def test_tool_call_ids_are_required_for_gemini3_not_gemini2() -> None:
    assert requires_tool_call_id("gemini-3.5-flash") is True
    assert requires_tool_call_id("gemini-live-3.0-flash") is True
    assert requires_tool_call_id("gemini-2.5-flash") is False
    assert requires_tool_call_id("gpt-oss-120b") is True
