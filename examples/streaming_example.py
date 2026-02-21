"""Streaming completion example using SSE.

Uses the native /api/complete endpoint with Agent Hub's SSE format.
Events: connected, content, tool_use, tool_result, done, error.
"""

import asyncio
import json

import httpx


async def main() -> None:
    """Stream a completion response."""
    async with (
        httpx.AsyncClient() as client,
        client.stream(
            "POST",
            "http://localhost:8003/api/complete",
            json={
                "agent_slug": "chat",
                "project_id": "agent-hub",
                "messages": [
                    {"role": "user", "content": "Tell me a short story about a robot."}
                ],
                "stream": True,
            },
            timeout=60.0,
        ) as response,
    ):
        response.raise_for_status()

        async for line in response.aiter_lines():
            if line.startswith("data: "):
                data = line[6:]
                if data == "[DONE]":
                    print("\n--- Done ---")
                    break

                chunk = json.loads(data)
                event_type = chunk.get("type")

                if event_type == "connected":
                    print(f"Session: {chunk.get('session_id')}")
                elif event_type == "content":
                    print(chunk.get("content", ""), end="", flush=True)
                elif event_type == "done":
                    print(f"\n--- Done (finish: {chunk.get('finish_reason')}) ---")
                    break
                elif event_type == "error":
                    print(f"\nError: {chunk.get('error')}")
                    break


if __name__ == "__main__":
    asyncio.run(main())
