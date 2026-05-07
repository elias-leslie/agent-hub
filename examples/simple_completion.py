"""Simple completion example using curl-style requests."""

import asyncio

import httpx


async def main() -> None:
    """Run a simple completion request."""
    async with httpx.AsyncClient() as client:
        response = await client.post(
            "http://localhost:8003/api/complete",
            json={
                "agent_slug": "chat",
                "project_id": "demo",
                "messages": [{"role": "user", "content": "What is 2 + 2?"}],
                "max_tokens": 100,
            },
            timeout=30.0,
        )
        response.raise_for_status()
        data = response.json()

        print(f"Response: {data['content']}")
        print(f"Model: {data['model']}")
        print(f"Tokens: {data['usage']['total_tokens']}")


if __name__ == "__main__":
    asyncio.run(main())
