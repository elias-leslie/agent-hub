"""Streaming completion example using SSE."""

import asyncio

import httpx


async def main() -> None:
    """Stream a completion response."""
    async with httpx.AsyncClient() as client, client.stream(
        "POST",
        "http://localhost:8003/api/v1/chat/completions",
        json={
            "model": "claude-sonnet-4-5",
            "messages": [{"role": "user", "content": "Tell me a short story about a robot."}],
            "stream": True,
        },
        timeout=60.0,
    ) as response:
        response.raise_for_status()

        async for line in response.aiter_lines():
            if line.startswith("data: "):
                data = line[6:]
                if data == "[DONE]":
                    print("\n--- Done ---")
                    break

                import json

                chunk = json.loads(data)
                if chunk.get("choices"):
                    content = chunk["choices"][0].get("delta", {}).get("content", "")
                    if content:
                        print(content, end="", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
