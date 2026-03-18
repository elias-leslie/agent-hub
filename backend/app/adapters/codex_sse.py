"""Codex SSE event parsing and HTTP streaming helpers.

Provides utilities for parsing Server-Sent Events from the Codex
Responses API and building HTTP requests.
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from typing import Any

import httpx

from app.adapters.base import (
    AuthenticationError,
    CompletionResult,
    ProviderError,
    RateLimitError,
    StreamEvent,
    ToolCallResult,
)
from app.adapters.codex_auth import CodexCredentials

logger = logging.getLogger(__name__)

CODEX_API_URL = "https://chatgpt.com/backend-api/codex/responses"
DEFAULT_TIMEOUT = 120.0  # seconds


def build_headers(credentials: CodexCredentials) -> dict[str, str]:
    """Build request headers for the Codex backend API."""
    return {
        "Authorization": f"Bearer {credentials.access_token}",
        "chatgpt-account-id": credentials.account_id,
        "Content-Type": "application/json",
        "OpenAI-Beta": "responses=experimental",
        "Accept": "text/event-stream",
        "originator": "agent-hub",
    }


def build_request_body(
    input_items: list[dict[str, Any]],
    model: str,
    *,
    instructions: str | None = None,
    temperature: float = 1.0,  # accepted but ignored — Codex API rejects temperature
    max_tokens: int | None = None,
    stream: bool = True,
    **kwargs: Any,
) -> dict[str, Any]:
    """Build the JSON body for a Codex Responses API request."""
    body: dict[str, Any] = {
        "model": model,
        "input": input_items,
        "stream": stream,
        "store": False,
    }
    if instructions:
        body["instructions"] = instructions
    # NOTE: temperature is intentionally NOT sent — the Codex Responses API
    # returns 400 "Unsupported parameter: temperature".
    if max_tokens is not None:
        body["max_output_tokens"] = max_tokens
    if kwargs.get("tools"):
        body["tools"] = _convert_tools(kwargs["tools"])
        body["tool_choice"] = "auto"
        body["parallel_tool_calls"] = True
    if kwargs.get("reasoning_effort"):
        body["reasoning"] = {"effort": kwargs["reasoning_effort"], "summary": "auto"}
    if kwargs.get("verbosity_level"):
        body["text"] = {"verbosity": kwargs["verbosity_level"]}
    if kwargs.get("prompt_cache_key"):
        body["prompt_cache_key"] = kwargs["prompt_cache_key"]
    return body


def _convert_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert internal tool definitions to Codex Responses function tools."""
    converted: list[dict[str, Any]] = []
    for tool in tools:
        if tool.get("type") == "function":
            converted.append(tool)
            continue
        converted.append({
            "type": "function",
            "name": tool["name"],
            "description": tool.get("description", ""),
            "parameters": tool.get("input_schema", {"type": "object", "properties": {}}),
        })
    return converted


def handle_error_response(status_code: int, body_text: str) -> None:
    """Raise the appropriate ProviderError subclass based on HTTP status and body."""
    error_code = ""
    error_message = body_text
    try:
        data = json.loads(body_text)
        if isinstance(data, dict):
            err = data.get("error", {})
            if isinstance(err, dict):
                error_code = err.get("code") or err.get("type") or ""
                error_message = err.get("message") or body_text
    except json.JSONDecodeError:
        pass

    if (
        status_code == 429
        or "usage_limit_reached" in error_code
        or "rate_limit" in error_code.lower()
    ):
        raise RateLimitError(provider="codex")
    if status_code in (401, 403):
        raise AuthenticationError(provider="codex")
    raise ProviderError(
        error_message,
        provider="codex",
        retriable=status_code >= 500,
        status_code=status_code,
    )


def _parse_delta(event: dict[str, Any]) -> str:
    """Extract text delta from a Codex SSE event, or empty string."""
    event_type = event.get("type", "")
    if event_type == "response.output_text.delta":
        return event.get("delta", "")
    if event_type == "response.content_part.delta":
        delta = event.get("delta", "")
        return delta if isinstance(delta, str) else ""
    return ""


def _parse_completion_event(event: dict[str, Any], resolved_model: str = "") -> dict[str, Any]:
    """Extract usage, finish_reason, and model from a completion event."""
    resp_data = event.get("response", {})
    usage = resp_data.get("usage", {})
    status = resp_data.get("status", "completed")
    finish_reason = (
        "stop" if status == "completed" else ("length" if status == "incomplete" else status)
    )
    return {
        "input_tokens": usage.get("input_tokens", 0),
        "output_tokens": usage.get("output_tokens", 0),
        "finish_reason": finish_reason,
        "model": resp_data.get("model", resolved_model),
    }


def _error_message(event_type: str, event: dict[str, Any]) -> str | None:
    """Return a formatted error message for error events, else None."""
    if event_type == "error":
        raw = event.get("message") or event.get("code") or json.dumps(event)
        return f"Codex error: {raw}"
    if event_type == "response.failed":
        return (
            (event.get("response") or {})
            .get("error", {})
            .get("message", "Codex response failed")
        )
    return None


async def parse_sse_lines(response: httpx.Response) -> AsyncIterator[dict[str, Any]]:
    """Yield parsed JSON event dicts from an SSE response stream."""
    async for line in response.aiter_lines():
        if not line.startswith("data: "):
            continue
        raw = line[6:].strip()
        if raw == "[DONE]":
            return
        try:
            yield json.loads(raw)
        except json.JSONDecodeError:
            continue


def _handle_output_item_added(
    item: dict[str, Any],
    reasoning_by_id: dict[str, list[str]],
    tool_call_args: dict[str, str],
) -> None:
    """Register a new output item in the tracking dicts."""
    item_type = item.get("type")
    if item_type == "reasoning":
        reasoning_by_id[str(item.get("id", ""))] = []
    elif item_type == "function_call":
        tool_call_args[str(item.get("call_id", ""))] = item.get("arguments", "") or ""


def _handle_reasoning_delta(
    event: dict[str, Any],
    reasoning_by_id: dict[str, list[str]],
) -> None:
    """Append a reasoning summary delta to the appropriate reasoning item."""
    item_id = event.get("item_id")
    if item_id is not None and item_id in reasoning_by_id:
        reasoning_by_id[item_id].append(event.get("delta", ""))
    else:
        active_ids = list(reasoning_by_id)
        if active_ids:
            reasoning_by_id[active_ids[-1]].append(event.get("delta", ""))


def _handle_function_call_delta(
    event: dict[str, Any],
    tool_call_args: dict[str, str],
) -> None:
    """Append a function call arguments delta to the appropriate call."""
    call_id = event.get("call_id")
    if call_id is not None and call_id in tool_call_args:
        tool_call_args[call_id] += event.get("delta", "")
    else:
        active_ids = list(tool_call_args)
        if active_ids:
            tool_call_args[active_ids[-1]] += event.get("delta", "")


def _finalize_function_call(
    item: dict[str, Any],
    tool_call_args: dict[str, str],
) -> ToolCallResult:
    """Build a ToolCallResult from a completed function_call output item."""
    call_id = str(item.get("call_id", ""))
    raw_args = tool_call_args.get(call_id) or item.get("arguments", "") or "{}"
    try:
        parsed_args = json.loads(raw_args) if raw_args else {}
    except json.JSONDecodeError:
        parsed_args = {}
    return ToolCallResult(
        id=call_id,
        original_id=str(item.get("id", "")) or None,
        name=str(item.get("name", "")),
        input=parsed_args,
    )


def _handle_output_item_done(
    item: dict[str, Any],
    reasoning_by_id: dict[str, list[str]],
    tool_call_args: dict[str, str],
    thinking_parts: list[str],
    tool_calls: list[ToolCallResult],
) -> None:
    """Update thinking_parts or tool_calls from a completed output item."""
    item_type = item.get("type")
    if item_type == "reasoning":
        summary = "".join(reasoning_by_id.get(str(item.get("id", "")), []))
        if summary:
            thinking_parts.append(summary)
    elif item_type == "function_call":
        tool_calls.append(_finalize_function_call(item, tool_call_args))


async def collect_completion(
    response: httpx.Response,
    resolved_model: str,
) -> CompletionResult:
    """Collect a full completion result from an SSE stream response."""
    content_parts: list[str] = []
    thinking_parts: list[str] = []
    tool_calls: list[ToolCallResult] = []
    reasoning_by_id: dict[str, list[str]] = {}
    tool_call_args: dict[str, str] = {}
    input_tokens = 0
    output_tokens = 0
    finish_reason: str | None = None
    response_model = resolved_model

    async for event in parse_sse_lines(response):
        event_type = event.get("type", "")
        msg = _error_message(event_type, event)
        if msg is not None:
            raise ProviderError(msg, provider="codex", retriable=False)
        delta = _parse_delta(event)
        if delta:
            content_parts.append(delta)
        if event_type == "response.output_item.added":
            _handle_output_item_added(event.get("item", {}), reasoning_by_id, tool_call_args)
        if event_type == "response.reasoning_summary_text.delta":
            _handle_reasoning_delta(event, reasoning_by_id)
        if event_type == "response.function_call_arguments.delta":
            _handle_function_call_delta(event, tool_call_args)
        if event_type == "response.output_item.done":
            _handle_output_item_done(
                event.get("item", {}), reasoning_by_id, tool_call_args, thinking_parts, tool_calls
            )
        if event_type in ("response.completed", "response.done"):
            parsed = _parse_completion_event(event, resolved_model)
            input_tokens = parsed["input_tokens"]
            output_tokens = parsed["output_tokens"]
            finish_reason = parsed["finish_reason"]
            response_model = parsed["model"]

    return CompletionResult(
        content="".join(content_parts),
        model=response_model,
        provider="codex",
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        finish_reason=finish_reason,
        tool_calls=tool_calls or None,
        thinking_content="\n".join(part for part in thinking_parts if part) or None,
    )


async def iter_stream_events(
    response: httpx.Response,
) -> AsyncIterator[StreamEvent]:
    """Yield StreamEvent objects from an SSE stream response."""
    input_tokens = 0
    output_tokens = 0
    finish_reason: str | None = None

    async for event in parse_sse_lines(response):
        event_type = event.get("type", "")

        msg = _error_message(event_type, event)
        if msg is not None:
            yield StreamEvent(type="error", error=msg)
            return

        delta = _parse_delta(event)
        if delta:
            yield StreamEvent(type="content", content=delta)

        if event_type in ("response.completed", "response.done"):
            parsed = _parse_completion_event(event)
            input_tokens = parsed["input_tokens"]
            output_tokens = parsed["output_tokens"]
            finish_reason = parsed["finish_reason"]

    yield StreamEvent(
        type="done",
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        finish_reason=finish_reason,
    )
