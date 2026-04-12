"""Tool execution support for Gemini adapter."""

from __future__ import annotations

import asyncio
import logging
import traceback
import uuid
from collections.abc import AsyncIterator
from typing import Any, cast

from google import genai
from google.genai import types

from app.adapters.base import Message, ProviderError, is_retriable_error
from app.adapters.gemini_events import ToolContentBlock, ToolEvent, ToolMessage
from app.adapters.gemini_thinking import get_thinking_level
from app.adapters.gemini_utils import convert_messages
from app.services.tools import ToolCall
from app.services.tools.direct_executor import create_direct_handler

logger = logging.getLogger(__name__)

_GENERATE_MAX_RETRIES = 3
_GENERATE_RETRY_BASE_DELAY = 2.0
_GENERATE_RETRY_MAX_DELAY = 30.0


def _is_retryable(e: Exception) -> bool:
    """Return True if the exception warrants a retry."""
    return is_retriable_error(e) or "DEADLINE_EXCEEDED" in str(e)


async def _attempt_generate(
    client: genai.Client,
    model: str,
    contents: list[Any],
    config: types.GenerateContentConfig,
) -> Any:
    """Single generate_content attempt; raises non-retryable errors, returns result or exception."""
    try:
        return await client.aio.models.generate_content(
            model=model, contents=contents, config=config
        )
    except Exception as e:
        if not _is_retryable(e):
            raise
        return e


async def _generate_with_retry(
    client: genai.Client,
    model: str,
    contents: list[Any],
    config: types.GenerateContentConfig,
) -> Any:
    """Call generate_content with retry on transient errors (429, 503, 504)."""
    last_exc: Exception | None = None
    for attempt in range(_GENERATE_MAX_RETRIES):
        result = await _attempt_generate(client, model, contents, config)
        if not isinstance(result, Exception):
            return result
        last_exc = result
        delay = min(_GENERATE_RETRY_BASE_DELAY * (2**attempt), _GENERATE_RETRY_MAX_DELAY)
        logger.warning(
            "Gemini generate_content retry %d/%d after %s (delay=%.1fs)",
            attempt + 1,
            _GENERATE_MAX_RETRIES,
            type(last_exc).__name__,
            delay,
        )
        await asyncio.sleep(delay)
    raise last_exc  # type: ignore[misc]


def build_gemini_tools(tools: list[dict[str, Any]]) -> list[types.Tool]:
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


def _build_generate_config(
    gemini_tools: list[types.Tool],
    system_instruction: Any,
    max_tokens: int | None,
    model: str,
    thinking_level_hint: Any,
) -> types.GenerateContentConfig:
    """Build GenerateContentConfig for a single generation call."""
    config_params: dict[str, Any] = {
        "temperature": 1.0,
        "tools": cast(Any, gemini_tools) if gemini_tools else None,
        "automatic_function_calling": types.AutomaticFunctionCallingConfig(disable=True),
        "system_instruction": system_instruction,
    }
    if max_tokens is not None:
        config_params["max_output_tokens"] = max_tokens
    config = types.GenerateContentConfig(**config_params)
    thinking_level = get_thinking_level(model, thinking_level_hint)
    if thinking_level:
        config.thinking_config = types.ThinkingConfig(thinking_level=thinking_level)
    return config


def _parse_response_parts(response_parts: list[Any]) -> tuple[str, list[ToolCall]]:
    """Extract text content and tool calls from response parts."""
    text_content = ""
    tool_calls: list[ToolCall] = []
    for part in response_parts:
        if part.text:
            text_content += part.text
        elif part.function_call:
            fc = part.function_call
            tool_calls.append(
                ToolCall(
                    id=fc.id or f"{fc.name}_{uuid.uuid4().hex[:8]}",
                    name=fc.name or "unknown",
                    input=dict(fc.args) if fc.args else {},
                )
            )
    return text_content, tool_calls


def _yield_text_event(text: str) -> ToolEvent:
    """Create a text content event."""
    return ToolEvent(
        type="assistant", message=ToolMessage(content=[ToolContentBlock(type="text", text=text)])
    )


def _yield_tool_use_event(tc: ToolCall) -> ToolEvent:
    """Create a tool use event."""
    return ToolEvent(
        type="assistant",
        message=ToolMessage(
            content=[ToolContentBlock(type="tool_use", name=tc.name, input=tc.input, id=tc.id)]
        ),
    )


async def _execute_tools(
    tool_calls: list[ToolCall], tool_handler: Any
) -> AsyncIterator[tuple[ToolEvent, types.Part]]:
    """Execute tools and yield results with corresponding parts."""
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
            types.Part.from_function_response(name=tc.name, response={"result": result.content}),
        )


async def _agentic_loop(
    client: genai.Client,
    model: str,
    contents: list[Any],
    gemini_tools: list[types.Tool],
    system_instruction: Any,
    max_tokens: int | None,
    thinking_level_hint: Any,
    max_turns: int,
    tool_handler: Any,
) -> AsyncIterator[ToolEvent]:
    """Inner agentic loop; yields ToolEvents (without session_id)."""
    accumulated_text = ""
    for _ in range(max_turns):
        config = _build_generate_config(
            gemini_tools, system_instruction, max_tokens, model, thinking_level_hint
        )
        response = await _generate_with_retry(client, model, contents, config)
        if not response.candidates or not response.candidates[0].content:
            yield ToolEvent(type="error", error="Empty response from model")
            return
        candidate = response.candidates[0]
        raw_parts = (candidate.content.parts or []) if candidate.content else []
        text_content, tool_calls = _parse_response_parts(list(raw_parts))
        if text_content:
            accumulated_text += text_content
            yield _yield_text_event(text_content)
        for tc in tool_calls:
            yield _yield_tool_use_event(tc)
        if not tool_calls:
            yield ToolEvent(type="result", subtype="success", result=accumulated_text)
            return
        tool_results_parts: list[types.Part] = []
        async for event, part in _execute_tools(tool_calls, tool_handler):
            yield event
            tool_results_parts.append(part)
        contents.append(candidate.content)
        contents.append(types.Content(role="user", parts=tool_results_parts))
    yield ToolEvent(type="result", subtype="success", result=accumulated_text)


async def execute_tool_loop(
    client: genai.Client,
    messages: list[Message],
    model: str,
    tools: list[dict[str, Any]],
    working_dir: str | None,
    max_tokens: int | None,
    max_turns: int,
    provider_name: str,
    project_id: str | None = None,
    **kwargs: Any,
) -> AsyncIterator[tuple[Any, str]]:
    """Run agentic loop with tool execution."""
    tool_handler = create_direct_handler(
        working_dir,
        project_id=project_id,
        agent_slug=kwargs.get("agent_slug"),
        tool_catalog=kwargs.get("tool_catalog"),
    )
    session_id = str(uuid.uuid4())
    gemini_tools = build_gemini_tools(tools)
    system_instruction, contents = convert_messages(messages)
    try:
        async for event in _agentic_loop(
            client,
            model,
            contents,
            gemini_tools,
            system_instruction,
            max_tokens,
            kwargs.get("thinking_level"),
            max_turns,
            tool_handler,
        ):
            yield (event, session_id)
    except Exception as e:
        logger.error("Gemini tool error: %s\n%s", e, traceback.format_exc())
        yield (ToolEvent(type="error", error=str(e)), session_id)
        msg = f"Gemini tool error: {e}"
        raise ProviderError(msg, provider=provider_name, retriable=True) from e
