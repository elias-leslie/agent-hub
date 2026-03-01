"""Private helpers for OpenAI-compatible adapter.

Not part of the public API — import from openai_compat instead.
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from typing import Any

from app.adapters.base import CompletionResult, Message, ProviderError, StreamEvent, ToolCallResult

logger = logging.getLogger(__name__)


def _to_openai_tool(tool: dict[str, Any]) -> dict[str, Any]:
    """Convert internal tool dict to OpenAI function-calling format.

    Internal format:  ``{"name": ..., "description": ..., "input_schema": ...}``
    OpenAI format:    ``{"type": "function", "function": {"name": ..., "parameters": ...}}``

    If the tool is already in OpenAI format, pass it through unchanged.
    """
    if tool.get("type") == "function" and "function" in tool:
        return tool
    return {
        "type": "function",
        "function": {
            "name": tool["name"],
            "description": tool.get("description", ""),
            "parameters": tool.get("input_schema") or tool.get("parameters", {}),
        },
    }


def parse_tool_call(tc: Any) -> ToolCallResult:
    """Parse a single OpenAI tool call object into ToolCallResult."""
    try:
        args = json.loads(tc.function.arguments)
    except json.JSONDecodeError:
        args = {}
    return ToolCallResult(
        id=tc.id,
        name=tc.function.name,
        input=args,
        caller_type="native",
        original_id=tc.id,
    )


def build_completion_params(
    model_id: str,
    openai_messages: list[dict[str, Any]],
    temperature: float,
    max_tokens: int | None,
    kwargs: dict[str, Any],
) -> dict[str, Any]:
    """Build the params dict for a chat completion request."""
    params: dict[str, Any] = {
        "model": model_id,
        "messages": openai_messages,
        "temperature": temperature,
    }
    if max_tokens:
        params["max_tokens"] = max_tokens
    if kwargs.get("tools"):
        params["tools"] = [_to_openai_tool(t) for t in kwargs["tools"]]
    if kwargs.get("tool_choice"):
        params["tool_choice"] = kwargs["tool_choice"]
    if kwargs.get("response_format"):
        params["response_format"] = kwargs["response_format"]
    if kwargs.get("reasoning_effort"):
        params["reasoning_effort"] = kwargs["reasoning_effort"]
    return params


def build_stream_params(
    model_id: str,
    openai_messages: list[dict[str, Any]],
    temperature: float,
    max_tokens: int | None,
    kwargs: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the params dict for a streaming chat completion request."""
    params: dict[str, Any] = {
        "model": model_id,
        "messages": openai_messages,
        "temperature": temperature,
        "stream": True,
    }
    if max_tokens:
        params["max_tokens"] = max_tokens
    if kwargs:
        if kwargs.get("tools"):
            params["tools"] = [_to_openai_tool(t) for t in kwargs["tools"]]
        if kwargs.get("tool_choice"):
            params["tool_choice"] = kwargs["tool_choice"]
        if kwargs.get("response_format"):
            params["response_format"] = kwargs["response_format"]
        if kwargs.get("reasoning_effort"):
            params["reasoning_effort"] = kwargs["reasoning_effort"]
    return params


def parse_completion_response(response: Any, provider_name: str) -> CompletionResult:
    """Convert an OpenAI chat completion response to CompletionResult."""
    choice = response.choices[0]
    content = choice.message.content or ""
    tool_calls = None
    if choice.message.tool_calls:
        tool_calls = [parse_tool_call(tc) for tc in choice.message.tool_calls]
    return CompletionResult(
        content=content,
        model=response.model,
        provider=provider_name,
        input_tokens=response.usage.prompt_tokens if response.usage else 0,
        output_tokens=response.usage.completion_tokens if response.usage else 0,
        finish_reason=choice.finish_reason,
        raw_response=response,
        tool_calls=tool_calls if tool_calls else None,
    )


def _chunk_to_event(chunk: Any) -> StreamEvent | None:
    """Convert a stream chunk to a StreamEvent, or None to skip."""
    if not chunk.choices:
        return None
    delta = chunk.choices[0].delta
    if delta.content:
        return StreamEvent(type="content", content=delta.content)
    return None


async def iterate_stream(stream: Any) -> AsyncIterator[StreamEvent]:
    """Yield StreamEvents from an OpenAI stream, ending with a done event."""
    tool_call_accumulators: dict[int, dict[str, Any]] = {}

    async for chunk in stream:
        event = _chunk_to_event(chunk)
        if event is not None:
            yield event

        if chunk.choices:
            delta = chunk.choices[0].delta
            if delta.tool_calls:
                for tc_delta in delta.tool_calls:
                    idx = tc_delta.index
                    if idx not in tool_call_accumulators:
                        tool_call_accumulators[idx] = {"id": "", "name": "", "arguments": ""}
                    acc = tool_call_accumulators[idx]
                    if tc_delta.id:
                        acc["id"] = tc_delta.id
                    if tc_delta.function:
                        if tc_delta.function.name:
                            acc["name"] = tc_delta.function.name
                        if tc_delta.function.arguments:
                            acc["arguments"] += tc_delta.function.arguments

    for acc in tool_call_accumulators.values():
        try:
            tool_input = json.loads(acc["arguments"])
        except json.JSONDecodeError:
            tool_input = {}
        yield StreamEvent(
            type="tool_use",
            tool_id=acc["id"],
            tool_name=acc["name"],
            tool_input=tool_input,
        )

    yield StreamEvent(type="done")


def resolve_api_key(provider_name: str, explicit_key: str | None) -> str | None:
    """Try CredentialManager for API key if no explicit key provided."""
    if explicit_key:
        return explicit_key
    try:
        from app.services.credential_manager import get_credential_manager

        cm = get_credential_manager()
        if cm.is_initialized:
            return cm.get_api_key(provider_name)
    except Exception:
        pass
    return None


def build_client_kwargs(
    resolved_key: str,
    base_url: str,
    headers: dict[str, str] | None,
    extra_kwargs: dict[str, Any],
) -> dict[str, Any]:
    """Assemble kwargs for constructing an AsyncOpenAI client."""
    client_kwargs: dict[str, Any] = {"api_key": resolved_key, "base_url": base_url}
    if headers:
        client_kwargs["default_headers"] = headers
    client_kwargs.update(extra_kwargs)
    return client_kwargs


def convert_messages(messages: list[Message]) -> list[dict[str, Any]]:
    """Convert internal Message objects to OpenAI-format dicts."""
    return [{"role": msg.role, "content": msg.content} for msg in messages]


def handle_provider_error(error: Exception, provider_name: str) -> None:
    """Map an exception to a ProviderError and raise it."""
    msg = str(error)
    if "401" in msg or "Authentication" in msg:
        raise ProviderError(msg, provider_name, status_code=401)
    if "429" in msg or "Rate limit" in msg:
        raise ProviderError(msg, provider_name, retriable=True, status_code=429)
    raise ProviderError(msg, provider_name, retriable=True)
