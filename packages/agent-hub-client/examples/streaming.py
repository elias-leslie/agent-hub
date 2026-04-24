#!/usr/bin/env python3
"""Streaming example using the Agent Hub Python SDK."""

import asyncio

from agent_hub import AsyncAgentHubClient


async def main() -> None:
    """Demonstrate streaming completion."""
    async with AsyncAgentHubClient(base_url="http://localhost:8003") as client:
        print("Streaming response: ", end="", flush=True)

        # Stream via the configured chat agent instead of pinning a model.
        async for chunk in client.stream_sse(
            agent_slug="chat",
            project_id="agent-hub",
            messages=[{"role": "user", "content": "Write a haiku about coding."}],
        ):
            if chunk.type == "content":
                print(chunk.content, end="", flush=True)
            elif chunk.type == "done":
                print(f"\n\n[Finished: {chunk.finish_reason}]")


if __name__ == "__main__":
    asyncio.run(main())
