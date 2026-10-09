"""Streaming operations for Agent Hub async client."""

import json
from collections.abc import AsyncIterator, Iterator
from typing import Any

import httpx

from agent_hub._utils import handle_error
from agent_hub.exceptions import AgentHubError
from agent_hub.models import StreamChunk, ToolCall


def _build_tool_use_chunk(data: dict[str, Any]) -> StreamChunk:
    """Build a StreamChunk for a tool_use SSE event."""
    tool_id = data.get("tool_id")
    tool_name = data.get("tool_name")
    tool_input = data.get("tool_input")
    return StreamChunk(
        type="tool_use",
        tool_id=tool_id,
        tool_name=tool_name,
        tool_input=tool_input,
        tool_call=ToolCall(
            id=tool_id or "",
            name=tool_name or "",
            input=tool_input or {},
        ),
    )


def _dispatch_sse_event(data: dict[str, Any]) -> tuple[StreamChunk | None, bool]:
    """Map a parsed SSE event dict to a StreamChunk.

    Returns (chunk, is_terminal). chunk is None for unknown event types.
    is_terminal is True for event types that end the stream.
    """
    event_type = data.get("type")

    if event_type == "content":
        return StreamChunk(type="content", content=data.get("content", "")), False

    if event_type == "thinking":
        return StreamChunk(type="thinking", content=data.get("content", "")), False

    if event_type == "tool_use":
        return _build_tool_use_chunk(data), False

    if event_type == "tool_result":
        return StreamChunk(
            type="tool_result",
            tool_id=data.get("tool_id"),
            tool_result=data.get("tool_result"),
            tool_status=data.get("tool_status"),
        ), False

    if event_type in ("done", "cancelled"):
        finish_reason = data.get("finish_reason")
        # Agent-hub emits one `done` per turn during execute_tools loops.
        # Mid-loop turns carry finish_reason="toolUse"; only the final turn
        # carries a true terminal reason (stop / endTurn / length / error).
        # Mirror pi-mono: `agent_end` is the sole terminal event — drop
        # mid-loop dones so the consumer keeps streaming until the loop ends.
        if event_type == "done" and finish_reason == "toolUse":
            return None, False
        return StreamChunk(
            type=event_type,
            finish_reason=finish_reason,
            model=data.get("model"),
            provider=data.get("provider"),
            input_tokens=data.get("input_tokens"),
            output_tokens=data.get("output_tokens"),
            session_id=data.get("session_id"),
            agent_used=data.get("agent_used"),
            model_used=data.get("model_used"),
            fallback_used=data.get("fallback_used"),
            cost_usd=data.get("cost_usd"),
            thinking_tokens=data.get("thinking_tokens"),
            cache_read_tokens=data.get("cache_read_tokens"),
            cache_write_tokens=data.get("cache_write_tokens"),
        ), True

    if event_type == "error":
        return StreamChunk(type="error", error=data.get("error")), True

    return None, False


def _parse_sse_line(line: str) -> tuple[StreamChunk | None, bool]:
    """Parse one SSE line into (chunk, is_terminal)."""
    if not line or not line.startswith("data: "):
        return None, False
    data_str = line[6:]
    if data_str == "[DONE]":
        return None, True
    try:
        data = json.loads(data_str)
    except json.JSONDecodeError:
        return None, False
    return _dispatch_sse_event(data)


async def _stream_sse_lines(
    response: httpx.Response,
) -> AsyncIterator[StreamChunk]:
    """Yield StreamChunks from SSE response lines."""
    async for line in response.aiter_lines():
        chunk, is_terminal = _parse_sse_line(line)
        if chunk is not None:
            yield chunk
        if is_terminal:
            return


async def stream_completion_sse(
    client: httpx.AsyncClient,
    payload: dict[str, Any],
    headers: dict[str, str],
) -> AsyncIterator[StreamChunk]:
    """Stream a completion using SSE (Server-Sent Events).

    Args:
        client: Async httpx client.
        payload: Completion request payload.
        headers: Request headers.

    Yields:
        StreamChunk for each streaming event.

    Raises:
        AgentHubError: If connection or streaming fails.
    """
    try:
        async with client.stream(
            "POST", "/api/complete", json=payload, headers=headers
        ) as response:
            if not response.is_success:
                await response.aread()
                handle_error(response)
            async for chunk in _stream_sse_lines(response):
                yield chunk
    except AgentHubError:
        # Keep typed errors (auth, rate limit with retry_after, kill switch).
        raise
    except Exception as e:
        raise AgentHubError(f"SSE streaming error: {e}") from e


def stream_completion_sse_sync(
    client: httpx.Client,
    payload: dict[str, Any],
    headers: dict[str, str],
    timeout: float | None = None,
) -> Iterator[StreamChunk]:
    """Synchronous counterpart of :func:`stream_completion_sse`."""
    request_timeout = httpx.USE_CLIENT_DEFAULT if timeout is None else timeout
    try:
        with client.stream("POST", "/api/complete", json=payload, headers=headers, timeout=request_timeout) as response:
            if not response.is_success:
                response.read()
                handle_error(response)
            for line in response.iter_lines():
                chunk, is_terminal = _parse_sse_line(line)
                if chunk is not None:
                    yield chunk
                if is_terminal:
                    return
    except AgentHubError:
        raise
    except Exception as e:
        raise AgentHubError(f"SSE streaming error: {e}") from e
