"""Streaming operations for Agent Hub async client."""

import json
from collections.abc import AsyncIterator
from typing import Any

import httpx

from agent_hub._utils import handle_error
from agent_hub.exceptions import AgentHubError
from agent_hub.models import MessageInput, StreamChunk


async def stream_completion_sse(
    client: httpx.AsyncClient,
    messages: list[dict[str, str] | MessageInput],
    project_id: str,
    headers: dict[str, str],
    agent_slug: str | None = None,
    model: str | None = None,
    temperature: float = 1.0,
) -> AsyncIterator[StreamChunk]:
    """Stream a completion using SSE (Server-Sent Events).

    Args:
        client: Async httpx client.
        messages: Conversation messages.
        project_id: Project ID for session tracking.
        headers: Request headers.
        agent_slug: Agent slug for routing.
        model: Direct model specification.
        temperature: Sampling temperature.

    Yields:
        StreamChunk for each streaming event.

    Raises:
        AgentHubError: If connection or streaming fails.
    """
    # Normalize messages
    msg_dicts = []
    for msg in messages:
        if isinstance(msg, MessageInput):
            msg_dicts.append(msg.model_dump())
        else:
            msg_dicts.append(msg)

    payload: dict[str, Any] = {
        "messages": msg_dicts,
        "project_id": project_id,
        "temperature": temperature,
        "stream": True,
    }
    if agent_slug:
        payload["agent_slug"] = agent_slug
    if model:
        payload["model"] = model

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

                        elif event_type == "error":
                            yield StreamChunk(type="error", error=data.get("error"))
                            return

                    except json.JSONDecodeError:
                        continue

    except Exception as e:
        raise AgentHubError(f"SSE streaming error: {e}") from e
