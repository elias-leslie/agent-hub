"""Session management example - multi-turn conversations."""

import asyncio

import httpx

BASE_URL = "http://localhost:8003/api"


async def main() -> None:
    """Demonstrate session-based conversation."""
    async with httpx.AsyncClient() as client:
        # First message - creates session
        response = await client.post(
            f"{BASE_URL}/complete",
            json={
                "model": "claude-sonnet-4-5",
                "messages": [{"role": "user", "content": "My name is Alice."}],
                "project_id": "demo",
            },
            timeout=30.0,
        )
        data = response.json()
        session_id = data["session_id"]
        print(f"Session created: {session_id}")
        print(f"Response: {data['content']}\n")

        # Second message - continues session
        response = await client.post(
            f"{BASE_URL}/complete",
            json={
                "model": "claude-sonnet-4-5",
                "messages": [{"role": "user", "content": "What is my name?"}],
                "session_id": session_id,
            },
            timeout=30.0,
        )
        data = response.json()
        print(f"Response: {data['content']}")
        print(f"Context usage: {data.get('context_usage', {}).get('percent_used', 0):.1%}\n")

        # Get session history
        response = await client.get(f"{BASE_URL}/sessions/{session_id}/messages")
        messages = response.json()
        print(f"Session has {len(messages)} messages")


if __name__ == "__main__":
    asyncio.run(main())
