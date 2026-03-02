"""Streaming completion example using SSE.

Uses the native /api/complete endpoint with Agent Hub's SSE format.
Events: connected, content, tool_use, tool_result, done, error.
"""

import asyncio
import json

import httpx

# --- Constants ---
API_URL = "http://localhost:8003/api/complete"
HTTP_METHOD = "POST"
AGENT_SLUG = "chat"
PROJECT_ID = "agent-hub"
DEFAULT_PROMPT = "Tell me a short story about a robot."
SSE_DATA_PREFIX = "data: "
SSE_DATA_PREFIX_LEN = len(SSE_DATA_PREFIX)
SSE_DONE_SENTINEL = "[DONE]"
REQUEST_TIMEOUT = 60.0

EVENT_CONNECTED = "connected"
EVENT_CONTENT = "content"
EVENT_DONE = "done"
EVENT_ERROR = "error"


def handle_event(chunk: dict) -> bool:
    """Handle a single SSE event chunk.

    Returns True if streaming should stop, False to continue.
    """
    event_type = chunk.get("type")

    if event_type == EVENT_CONNECTED:
        print(f"Session: {chunk.get('session_id')}")
        return False

    if event_type == EVENT_CONTENT:
        print(chunk.get("content", ""), end="", flush=True)
        return False

    if event_type == EVENT_DONE:
        print(f"\n--- Done (finish: {chunk.get('finish_reason')}) ---")
        return True

    if event_type == EVENT_ERROR:
        print(f"\nError: {chunk.get('error')}")
        return True

    return False


async def main() -> None:
    """Stream a completion response."""
    async with (
        httpx.AsyncClient() as client,
        client.stream(
            HTTP_METHOD,
            API_URL,
            json={
                "agent_slug": AGENT_SLUG,
                "project_id": PROJECT_ID,
                "messages": [{"role": "user", "content": DEFAULT_PROMPT}],
                "stream": True,
            },
            timeout=REQUEST_TIMEOUT,
        ) as response,
    ):
        response.raise_for_status()

        async for line in response.aiter_lines():
            if not line.startswith(SSE_DATA_PREFIX):
                continue

            data = line[SSE_DATA_PREFIX_LEN:]

            if data == SSE_DONE_SENTINEL:
                print("\n--- Done ---")
                break

            chunk = json.loads(data)
            if handle_event(chunk):
                break


if __name__ == "__main__":
    asyncio.run(main())
