# Agent Hub Python Client

Python SDK for the Agent Hub API.

## Installation

```bash
pip install -e packages/agent-hub-client
```

## Quick Start

```python
from agent_hub import AgentHubClient, AsyncAgentHubClient

# Sync client
client = AgentHubClient(base_url="http://localhost:8003")
response = client.complete(
    model="claude-sonnet-4-5",
    messages=[{"role": "user", "content": "Hello!"}]
)
print(response.content)

# Async client
async with AsyncAgentHubClient(base_url="http://localhost:8003") as client:
    response = await client.complete(
        model="claude-sonnet-4-5",
        messages=[{"role": "user", "content": "Hello!"}]
    )
    print(response.content)
```

## Features

- Sync and async clients
- Streaming support (WebSocket)
- Session management
- Full type hints
- Automatic error handling
