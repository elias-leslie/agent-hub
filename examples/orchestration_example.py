"""Orchestration example - multi-agent queries with tracing."""

import asyncio

import httpx

BASE_URL = "http://localhost:8003/api"


async def main() -> None:
    """Run an orchestrated query with tracing."""
    async with httpx.AsyncClient() as client:
        # Start orchestrated query
        response = await client.post(
            f"{BASE_URL}/orchestration/query",
            json={
                "prompt": "Analyze this code and suggest improvements",
                "model": "claude-sonnet-4-5",
                "provider": "claude",
                "options": {
                    "working_dir": ".",
                    "max_turns": 5,
                },
            },
            timeout=120.0,
        )
        data = response.json()
        print("Query completed")
        print(f"Response: {data.get('content', '')[:200]}...")

        # Get trace if available
        trace_id = data.get("trace_id")
        if trace_id:
            print(f"\nTrace ID: {trace_id}")
            trace_response = await client.get(f"{BASE_URL}/orchestration/traces/{trace_id}")
            trace_data = trace_response.json()
            print(f"Duration: {trace_data.get('duration_ms')}ms")
            print(f"Spans: {trace_data.get('span_count')}")


if __name__ == "__main__":
    asyncio.run(main())
