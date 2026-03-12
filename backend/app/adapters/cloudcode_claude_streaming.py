"""Streaming and tool-loop helpers for CloudCode Claude adapter."""

from __future__ import annotations

import logging
import traceback
import uuid
from collections.abc import AsyncIterator
from typing import Any

from app.adapters.base import StreamEvent
from app.adapters.cloudcode_claude_transforms import (
    build_claude_generation_config,
)
from app.adapters.cloudcode_client import CloudCodeClient
from app.adapters.gemini_events import ToolContentBlock, ToolEvent, ToolMessage
from app.services.tools import ToolCall

logger = logging.getLogger(__name__)


def _extract_stream_usage(response: dict[str, Any], input_tokens: int, output_tokens: int) -> tuple[int, int]:
    """Extract token counts from a stream chunk's usageMetadata."""
    usage = response.get("usageMetadata", {})
    if usage.get("promptTokenCount"):
        input_tokens = usage["promptTokenCount"]
    if usage.get("candidatesTokenCount"):
        output_tokens = usage["candidatesTokenCount"]
    return input_tokens, output_tokens


async def stream_generate(
    client: CloudCodeClient,
    resolved: str,
    contents: list[dict[str, Any]],
    sys_inst: dict[str, Any] | None,
    gen_config: dict[str, Any] | None,
    tools: list[dict[str, Any]] | None,
    tool_config: dict[str, Any] | None,
) -> AsyncIterator[StreamEvent]:
    """Yield StreamEvents from a CloudCode streaming generate call."""
    total_content = ""
    input_tokens = 0
    output_tokens = 0
    finish_reason = "STOP"

    try:
        async for chunk in client.stream_generate_content(
            model=resolved,
            contents=contents,
            system_instruction=sys_inst,
            generation_config=gen_config,
            tools=tools,
            tool_config=tool_config,
        ):
            response = chunk.get("response", chunk)
            candidates = response.get("candidates", [])

            if candidates:
                candidate = candidates[0]
                if candidate.get("finishReason"):
                    finish_reason = candidate["finishReason"]
                for part in (candidate.get("content") or {}).get("parts", []):
                    if part.get("text") and not part.get("thought"):
                        total_content += part["text"]
                        yield StreamEvent(type="content", content=part["text"])
                    elif part.get("functionCall"):
                        fc = part["functionCall"]
                        yield StreamEvent(
                            type="tool_use",
                            tool_id=fc.get("id") or f"tool_{uuid.uuid4().hex[:12]}",
                            tool_name=fc.get("name", "unknown"),
                            tool_input=fc.get("args", {}),
                        )

            input_tokens, output_tokens = _extract_stream_usage(response, input_tokens, output_tokens)

        yield StreamEvent(
            type="done",
            input_tokens=input_tokens,
            output_tokens=output_tokens or len(total_content) // 4,
            finish_reason=finish_reason,
        )
    except Exception as e:
        logger.error("CloudCode Claude stream error: %s", e)
        yield StreamEvent(type="error", error=str(e))


def _parse_parts(parts: list[dict[str, Any]]) -> tuple[str, list[ToolCall]]:
    """Extract text content and tool calls from response parts."""
    text_content = ""
    tool_calls: list[ToolCall] = []
    for part in parts:
        if part.get("text") and not part.get("thought"):
            text_content += part["text"]
        elif part.get("functionCall"):
            fc = part["functionCall"]
            tool_calls.append(ToolCall(
                id=fc.get("id") or f"{fc.get('name', 'unknown')}_{uuid.uuid4().hex[:8]}",
                name=fc.get("name", "unknown"),
                input=fc.get("args", {}),
            ))
    return text_content, tool_calls


def _build_model_parts(parts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Rebuild model parts, preserving thoughtSignature on function calls/thoughts.

    CloudCode PA API requires thoughtSignature when thinking is enabled.
    """
    model_parts: list[dict[str, Any]] = []
    for part in parts:
        if part.get("text") and not part.get("thought"):
            model_parts.append({"text": part["text"]})
        elif part.get("thought") and part.get("text"):
            thought_part: dict[str, Any] = {"text": part["text"], "thought": True}
            if part.get("thoughtSignature"):
                thought_part["thoughtSignature"] = part["thoughtSignature"]
            model_parts.append(thought_part)
        elif part.get("functionCall"):
            fc_part: dict[str, Any] = {"functionCall": part["functionCall"]}
            if part.get("thoughtSignature"):
                fc_part["thoughtSignature"] = part["thoughtSignature"]
            model_parts.append(fc_part)
    return model_parts


def _yield_text_event(text_content: str, session_id: str) -> tuple[ToolEvent, str]:
    return (
        ToolEvent(
            type="assistant",
            message=ToolMessage(content=[ToolContentBlock(type="text", text=text_content)]),
        ),
        session_id,
    )


def _yield_tool_use_event(tc: ToolCall, session_id: str) -> tuple[ToolEvent, str]:
    return (
        ToolEvent(
            type="assistant",
            message=ToolMessage(content=[
                ToolContentBlock(type="tool_use", name=tc.name, input=tc.input, id=tc.id),
            ]),
        ),
        session_id,
    )


async def run_tool_loop(
    client: CloudCodeClient,
    resolved: str,
    contents: list[dict[str, Any]],
    system_instruction: dict[str, Any] | None,
    cc_tools: list[dict[str, Any]],
    tool_config: dict[str, Any],
    thinking_level: str | None,
    max_tokens: int | None,
    max_turns: int,
    tool_handler: Any,
    session_id: str,
) -> AsyncIterator[tuple[Any, str | None]]:
    """Run the agentic tool loop, yielding (ToolEvent, session_id) pairs."""
    accumulated_text = ""

    try:
        for _ in range(max_turns):
            gen_config = build_claude_generation_config(
                thinking_level=thinking_level,
                max_tokens=max_tokens,
                model=resolved,
            )
            data = await client.generate_content(
                model=resolved,
                contents=contents,
                system_instruction=system_instruction,
                generation_config=gen_config,
                tools=cc_tools,
                tool_config=tool_config,
            )

            response = data.get("response", data)
            candidates = response.get("candidates", [])
            if not candidates:
                yield (ToolEvent(type="error", error="Empty response from model"), session_id)
                return

            candidate = candidates[0]
            parts = (candidate.get("content") or {}).get("parts", [])
            text_content, tool_calls = _parse_parts(parts)

            if text_content:
                accumulated_text += text_content
                yield _yield_text_event(text_content, session_id)

            for tc in tool_calls:
                yield _yield_tool_use_event(tc, session_id)

            if not tool_calls:
                yield (
                    ToolEvent(
                        type="result",
                        subtype="success",
                        result=accumulated_text,
                        finish_reason="end_turn",
                    ),
                    session_id,
                )
                return

            # Execute tools and collect results
            tool_response_parts: list[dict[str, Any]] = []
            for tc in tool_calls:
                result = await tool_handler.execute(tc)
                yield (
                    ToolEvent(
                        type="tool_result",
                        content=result.content,
                        tool_use_id=tc.id,
                        is_error=result.is_error,
                        duration_ms=result.duration_ms,
                    ),
                    session_id,
                )
                tool_response_parts.append({
                    "functionResponse": {
                        "name": tc.name,
                        "id": tc.id,
                        "response": {"result": result.content},
                    },
                })

            contents.append({"role": "model", "parts": _build_model_parts(parts)})
            contents.append({"role": "user", "parts": tool_response_parts})

        # Exhausted max_turns
        yield (
            ToolEvent(
                type="result",
                subtype="success",
                result=accumulated_text,
                finish_reason="max_turns",
            ),
            session_id,
        )

    except Exception as e:
        logger.error("CloudCode Claude tool error: %s\n%s", e, traceback.format_exc())
        yield (ToolEvent(type="error", error=str(e)), session_id)
