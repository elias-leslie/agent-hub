# Getting Started with Agent Hub

Agent Hub is a unified AI service that routes requests to Claude and Gemini models, providing session management, streaming, and cost tracking.

## Prerequisites

- Python 3.11+
- PostgreSQL 15+
- Redis 7+
- Anthropic API key (for Claude models)
- Google AI API key (for Gemini models) - optional

## Installation

### 1. Clone and Setup

```bash
git clone https://github.com/your-org/agent-hub.git
cd agent-hub/backend

# Create virtual environment
python -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -e ".[dev]"
```

### 2. Environment Configuration

Create `~/.env.local` with your credentials:

```bash
# Database
AGENT_HUB_DB_URL=postgresql+asyncpg://user:pass@localhost/agent_hub

# Redis (for caching)
AGENT_HUB_REDIS_URL=redis://localhost:6379

# API Keys
ANTHROPIC_API_KEY=sk-ant-...
GEMINI_API_KEY=...  # Optional
```

### 3. Database Setup

```bash
# Create database
createdb agent_hub

# Run migrations
alembic upgrade head
```

## Quick Start

### Start the Backend

```bash
# Development mode
uvicorn app.main:app --reload --port 8003

# Or use the service script
bash ~/agent-hub/scripts/restart.sh
```

The API will be available at `http://localhost:8003`.

### Your First API Call

```bash
curl -X POST http://localhost:8003/api/complete \
  -H "Content-Type: application/json" \
  -d '{
    "model": "claude-sonnet-4-5",
    "messages": [{"role": "user", "content": "Hello!"}]
  }'
```

Response:
```json
{
  "content": "Hello! How can I help you today?",
  "model": "claude-sonnet-4-5-20250514",
  "provider": "claude",
  "usage": {
    "input_tokens": 10,
    "output_tokens": 12,
    "total_tokens": 22
  },
  "session_id": "abc123..."
}
```

## Using the Python SDK

### Installation

```bash
pip install -e packages/agent-hub-client
```

### Basic Usage

```python
from agent_hub import AsyncAgentHubClient

async with AsyncAgentHubClient(base_url="http://localhost:8003") as client:
    # Simple completion
    response = await client.complete(
        model="claude-sonnet-4-5",
        messages=[{"role": "user", "content": "Hello!"}]
    )
    print(response.content)

    # Streaming
    async for chunk in client.stream_sse(
        model="claude-sonnet-4-5",
        messages=[{"role": "user", "content": "Tell me a story"}]
    ):
        print(chunk.content, end="", flush=True)
```

### Session Management

```python
async with client.session(
    project_id="my-project",
    provider="claude",
    model="claude-sonnet-4-5"
) as session:
    response = await session.complete("What is 2+2?")
    print(response.content)  # "4"

    response = await session.complete("Multiply that by 3")
    print(response.content)  # "12"

    # Get conversation history
    history = await session.get_history()
```

## OpenAI-Compatible API

Use existing OpenAI SDK code with Agent Hub:

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:8003/api/v1",
    api_key="sk-ah-..."  # Optional
)

response = client.chat.completions.create(
    model="gpt-4",  # Maps to Claude Sonnet
    messages=[{"role": "user", "content": "Hello"}]
)
print(response.choices[0].message.content)
```

## Troubleshooting

### "Claude adapter requires either Claude CLI (OAuth) or API key"

Set the `ANTHROPIC_API_KEY` environment variable:
```bash
export ANTHROPIC_API_KEY=sk-ant-your-key
```

### "Database connection error"

1. Ensure PostgreSQL is running
2. Check `AGENT_HUB_DB_URL` is correct
3. Run migrations: `alembic upgrade head`

### "Redis connection refused"

1. Start Redis: `redis-server`
2. Check `AGENT_HUB_REDIS_URL` is correct

### Rate limit errors (429)

Agent Hub handles rate limits automatically with exponential backoff. If you're hitting limits frequently:

1. Use prompt caching (`enable_caching: true`)
2. Implement request batching
3. Consider upgrading your API tier

## Next Steps

- [API Guide](./api-guide.md) - Detailed endpoint documentation
- [Examples](./examples.md) - Code examples for common use cases
- [API Reference](http://localhost:8003/docs) - OpenAPI/Swagger docs
