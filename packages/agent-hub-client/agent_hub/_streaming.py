"""Streaming operations for Agent Hub async client."""

import json
from collections.abc import AsyncIterator
from typing import Any

import httpx

from agent_hub._utils import handle_error
from agent_hub.exceptions import AgentHubError
from agent_hub.models import StreamChunk, ToolCall


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

            async for line in response.aiter_lines():
                if not line:
                    continue

                if line.startswith("data: "):
                    data_str = line[6:]

                    if data_str == "[DONE]":
                        return

                    try:
                        data = json.loads(data_str)
                        event_type = data.get("type")

                        if event_type == "content":
                            yield StreamChunk(
                                type="content", content=data.get("content", "")
                            )

                        elif event_type == "thinking":
                            yield StreamChunk(
                                type="thinking", content=data.get("content", "")
                            )

                        elif event_type == "tool_use":
                            tool_id = data.get("tool_id")
                            tool_name = data.get("tool_name")
                            tool_input = data.get("tool_input")
                            yield StreamChunk(
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

                        elif event_type == "tool_result":
                            yield StreamChunk(
                                type="tool_result",
                                tool_id=data.get("tool_id"),
                                tool_result=data.get("tool_result"),
                                tool_status=data.get("tool_status"),
                            )

                        elif event_type == "done":
                            yield StreamChunk(
                                type="done",
                                finish_reason=data.get("finish_reason"),
                                model=data.get("model"),
                                provider=data.get("provider"),
                                input_tokens=data.get("input_tokens"),
                                output_tokens=data.get("output_tokens"),
                                session_id=data.get("session_id"),
                            )
                            return

                        elif event_type == "cancelled":
                            yield StreamChunk(
                                type="cancelled",
                                finish_reason=data.get("finish_reason"),
                                model=data.get("model"),
                                provider=data.get("provider"),
                                input_tokens=data.get("input_tokens"),
                                output_tokens=data.get("output_tokens"),
                                session_id=data.get("session_id"),
                            )
                            return

                        elif event_type == "error":
                            yield StreamChunk(type="error", error=data.get("error"))
                            return

                    except json.JSONDecodeError:
                        continue

    except Exception as e:
        raise AgentHubError(f"SSE streaming error: {e}") from e
