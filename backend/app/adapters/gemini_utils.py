"""Utility functions for Gemini adapter.

This module re-exports functions from focused submodules for backward compatibility.
All functionality has been split into specialized modules:
- gemini_messages: Message and content conversion
- gemini_config: Configuration building
- gemini_response: Response processing
- gemini_errors: Error handling
"""

import uuid
from typing import Any, cast

from google.genai import types

from app.adapters.base import StreamEvent
from app.adapters.gemini_config import build_config
from app.adapters.gemini_errors import handle_error
from app.adapters.gemini_messages import build_parts, convert_messages
from app.adapters.gemini_response import process_response
from app.adapters.gemini_thinking import get_thinking_level


async def do_complete_call(
    client: Any,
    messages: Any,
    model: str,
    temperature: float,
    max_tokens: int | None,
    provider_name: str,
    kwargs: dict[str, Any],
) -> Any:
    """Build config, call Gemini generate_content, and return processed result."""
    system_instruction, contents = convert_messages(messages)
    config_kwargs = {k: v for k, v in kwargs.items() if k not in ("response_format", "tools")}
    config = build_config(
        temperature=temperature,
        max_tokens=max_tokens,
        model=model,
        response_format=kwargs.get("response_format"),
        system_instruction=system_instruction,
        tools=kwargs.get("tools"),
        **config_kwargs,
    )
    try:
        response = await client.aio.models.generate_content(
            model=model, contents=contents, config=config,
        )
        return process_response(response, model, provider_name)
    except Exception as e:
        handle_error(e, provider_name)


def resolve_api_key(api_key: str | None) -> str | None:
    """Resolve API key via DB credential manager if explicit key not provided."""
    if api_key:
        return api_key
    try:
        from app.services.credential_manager import get_credential_manager

        cm = get_credential_manager()
        if cm.is_initialized:
            return cm.get_api_key("gemini")
    except Exception:
        pass
    return None


def extract_chunk_tool_events(chunk: Any) -> list[StreamEvent]:
    """Extract tool-use StreamEvents from a streaming response chunk."""
    events: list[StreamEvent] = []
    if not chunk.candidates:
        return events
    for candidate in chunk.candidates:
        if not (candidate.content and candidate.content.parts):
            continue
        for part in candidate.content.parts:
            if part.function_call:
                fc = part.function_call
                events.append(
                    StreamEvent(
                        type="tool_use",
                        tool_id=f"tool_{uuid.uuid4().hex[:12]}",
                        tool_name=fc.name,
                        tool_input=dict(fc.args) if fc.args else {},
                    )
                )
    return events


def build_stream_config(
    temperature: float,
    max_tokens: int | None,
    model: str,
    system_instruction: Any,
    tools_defs: Any,
    thinking_level: str | None,
) -> types.GenerateContentConfig:
    """Build a GenerateContentConfig for streaming requests."""
    config_params: dict[str, Any] = {
        "temperature": temperature,
        "automatic_function_calling": types.AutomaticFunctionCallingConfig(disable=True),
    }
    if max_tokens is not None:
        config_params["max_output_tokens"] = max_tokens

    config = types.GenerateContentConfig(**config_params)

    if thinking_level:
        config.thinking_config = types.ThinkingConfig(thinking_level=thinking_level)

    if system_instruction:
        config.system_instruction = system_instruction

    if tools_defs:
        from app.adapters.gemini_tools import build_gemini_tools  # lazy to avoid circular import
        config.tools = cast(Any, build_gemini_tools(tools_defs))

    return config


__all__ = [
    "build_config",
    "build_parts",
    "build_stream_config",
    "convert_messages",
    "do_complete_call",
    "extract_chunk_tool_events",
    "get_thinking_level",
    "handle_error",
    "process_response",
    "resolve_api_key",
]
