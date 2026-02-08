"""Tool execution support for Gemini adapter."""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import AsyncIterator
from typing import Any, cast

from google import genai
from google.genai import types

from app.adapters.base import Message, ProviderError, is_retriable_error
from app.adapters.gemini_events import MockContentBlock, MockEvent, MockMessage
from app.adapters.gemini_thinking import get_thinking_level
from app.adapters.gemini_utils import convert_messages
from app.services.tools import ToolCall
from app.services.tools.direct_executor import create_direct_handler

logger = logging.getLogger(__name__)

_GENERATE_MAX_RETRIES = 3
_GENERATE_RETRY_BASE_DELAY = 2.0
_GENERATE_RETRY_MAX_DELAY = 30.0


async def _generate_with_retry(
    client: genai.Client,
    model: str,
    contents: list[Any],
    config: types.GenerateContentConfig,
) -> Any:
    """Call generate_content with retry on transient errors (429, 503, 504)."""
    last_exc: Exception | None = None
    for attempt in range(_GENERATE_MAX_RETRIES):
        try:
            return await client.aio.models.generate_content(
                model=model, contents=contents, config=config
            )
        except Exception as e:
            if not is_retriable_error(e) and "DEADLINE_EXCEEDED" not in str(e):
                raise
            last_exc = e
            delay = min(
                _GENERATE_RETRY_BASE_DELAY * (2**attempt),
                _GENERATE_RETRY_MAX_DELAY,
            )
            logger.warning(
                "Gemini generate_content retry %d/%d after %s (delay=%.1fs)",
                attempt + 1,
                _GENERATE_MAX_RETRIES,
                type(e).__name__,
                delay,
            )
            await asyncio.sleep(delay)
    raise last_exc  # type: ignore[misc]


def _build_gemini_tools(tools: list[dict[str, Any]]) -> list[types.Tool]:
    """Build Gemini Tool objects from tool definitions."""
    return [
        types.Tool(
            function_declarations=[
                types.FunctionDeclaration(
                    name=t.get("name", ""),
                    description=t.get("description", ""),
                    parameters=t.get("input_schema") or t.get("parameters", {}),
                )
            ]
        )
        for t in tools
    ]


def _yield_text_event(text: str) -> MockEvent:
    """Create a text content event."""
    return MockEvent(type="assistant", message=MockMessage(content=[MockContentBlock(type="text", text=text)]))


def _yield_tool_use_event(tc: ToolCall) -> MockEvent:
    """Create a tool use event."""
    return MockEvent(type="assistant", message=MockMessage(content=[MockContentBlock(type="tool_use", name=tc.name, input=tc.input, id=tc.id)]))


async def _execute_tools(tool_calls: list[ToolCall], tool_handler: Any) -> AsyncIterator[tuple[MockEvent, types.Part]]:
    """Execute tools and yield results with corresponding parts."""
    for tc in tool_calls:
        result = await tool_handler.execute(tc)
        yield (
            MockEvent(type="tool_result", content=result.content, tool_use_id=tc.id, is_error=result.is_error),
            types.Part.from_function_response(name=tc.name, response={"result": result.content}),
        )


async def execute_tool_loop(
    client: genai.Client,
    messages: list[Message],
    model: str,
    tools: list[dict[str, Any]],
    working_dir: str | None,
    max_tokens: int | None,
    max_turns: int,
    provider_name: str,
    permission_config: dict[str, Any] | None = None,
    project_id: str | None = None,
    **kwargs: Any,
) -> AsyncIterator[tuple[Any, str]]:
    """Run agentic loop with tool execution."""
    tool_handler = create_direct_handler(working_dir, permission_config, project_id=project_id)
    session_id = str(uuid.uuid4())
    gemini_tools = _build_gemini_tools(tools)
    system_instruction, contents = convert_messages(messages)
    accumulated_text = ""

    try:
        for _ in range(max_turns):
            config_params: dict[str, Any] = {
                "temperature": 1.0,
                "tools": cast(Any, gemini_tools) if gemini_tools else None,
                "automatic_function_calling": types.AutomaticFunctionCallingConfig(disable=True),
                "system_instruction": system_instruction,
            }
            if max_tokens is not None:
                config_params["max_output_tokens"] = max_tokens
            config = types.GenerateContentConfig(**config_params)
            thinking_level = get_thinking_level(model, kwargs.get("thinking_level"))
            if thinking_level:
                config.thinking_config = types.ThinkingConfig(thinking_level=thinking_level)

            response = await _generate_with_retry(client, model, contents, config)

            if not response.candidates or not response.candidates[0].content:
                yield (MockEvent(type="error", error="Empty response from model"), session_id)
                return

            candidate = response.candidates[0]
            response_parts = list(candidate.content.parts) if candidate.content and candidate.content.parts else []
            text_content = ""
            tool_calls: list[ToolCall] = []

            for part in response_parts:
                if part.text:
                    text_content += part.text
                elif part.function_call:
                    fc = part.function_call
                    tool_calls.append(ToolCall(id=fc.id or f"{fc.name}_{uuid.uuid4().hex[:8]}", name=fc.name or "unknown", input=dict(fc.args) if fc.args else {}))

            if text_content:
                accumulated_text += text_content
                yield (_yield_text_event(text_content), session_id)

            for tc in tool_calls:
                yield (_yield_tool_use_event(tc), session_id)

            if not tool_calls:
                yield (MockEvent(type="result", subtype="success", result=accumulated_text), session_id)
                return

            tool_results_parts: list[types.Part] = []
            async for event, part in _execute_tools(tool_calls, tool_handler):
                yield (event, session_id)
                tool_results_parts.append(part)

            if candidate.content:
                contents.append(candidate.content)
            contents.append(types.Content(role="user", parts=tool_results_parts))

        yield (MockEvent(type="result", subtype="success", result=accumulated_text), session_id)

    except Exception as e:
        import traceback

        logger.error(
            "Gemini tool error: %s\n%s",
            e,
            traceback.format_exc(),
        )
        yield (MockEvent(type="error", error=str(e)), session_id)
        raise ProviderError(f"Gemini tool error: {e}", provider=provider_name, retriable=True) from e
