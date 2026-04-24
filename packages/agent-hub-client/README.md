# Agent Hub Python Client

Async Python SDK for the Agent Hub API.

## Installation

```bash
pip install -e packages/agent-hub-client
```

## Quick Start

```python
from agent_hub import AsyncAgentHubClient

async with AsyncAgentHubClient(base_url="http://localhost:8003") as client:
    response = await client.complete(
        agent_slug="chat",
        project_id="agent-hub",
        messages=[{"role": "user", "content": "Hello!"}]
    )
    print(response.content)
```

## Features

- Async completions
- SSE streaming via `stream_sse()`
- Stateful conversations via `session(...)`
- Session management
- Full type hints
- Automatic error handling
