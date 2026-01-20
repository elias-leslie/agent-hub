# Agent Hub

Unified agentic AI service for Claude/Gemini workloads.

**Project-specific context is injected via memory system at session start.**

See `~/.claude/CLAUDE.md` for memory API reference.

## Python SDK

Native Python client for Agent Hub API.

```bash
pip install -e packages/agent-hub-client
```

```python
from agent_hub import AsyncAgentHubClient

async with AsyncAgentHubClient(base_url="http://localhost:8003") as client:
    # Completion
    response = await client.complete(
        model="claude-sonnet-4-5",
        messages=[{"role": "user", "content": "Hello"}]
    )

    # Streaming (SSE)
    async for chunk in client.stream_sse(model="claude-sonnet-4-5", messages=[...]):
        print(chunk.content, end="")

    # Session management
    async with client.session(project_id="proj", provider="claude", model="claude-sonnet-4-5") as s:
        response = await s.complete("Hello")
        history = await s.get_history()
```

## OpenAI-Compatible API

Drop-in replacement endpoints:

| Endpoint | Description |
|----------|-------------|
| `/api/v1/chat/completions` | Chat completions (streaming supported) |
| `/api/v1/models` | List available models |
| `/api/api-keys` | API key management |

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:8003/api/v1",
    api_key="sk-ah-..."  # Optional - create via /api/api-keys
)

response = client.chat.completions.create(
    model="gpt-4",  # Maps to Claude Sonnet 4.5
    messages=[{"role": "user", "content": "Hello"}]
)
```

## Reference Projects

Local copies in `references/` (gitignored):

| Project | Clone |
|---------|-------|
| Auto-Claude | `git clone https://github.com/AndyMik90/Auto-Claude references/Auto-Claude` |
| vibe-kanban | `git clone https://github.com/BloopAI/vibe-kanban references/vibe-kanban` |
