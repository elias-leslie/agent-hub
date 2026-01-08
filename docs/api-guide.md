# Agent Hub API Guide

Complete reference for all Agent Hub API endpoints.

## Base URL

```
http://localhost:8003/api
```

## Authentication

Agent Hub supports optional API key authentication.

### API Key Management

```bash
# Create API key
curl -X POST http://localhost:8003/api/api-keys \
  -H "Content-Type: application/json" \
  -d '{"name": "my-app"}'

# Response: {"key": "sk-ah-...", "name": "my-app", "created_at": "..."}
```

### Using API Keys

Include in `Authorization` header:
```bash
curl -H "Authorization: Bearer sk-ah-..." http://localhost:8003/api/complete
```

## OpenAI-Compatible API

Drop-in replacement for OpenAI SDK.

### POST /api/v1/chat/completions

```bash
curl -X POST http://localhost:8003/api/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gpt-4",
    "messages": [
      {"role": "system", "content": "You are helpful."},
      {"role": "user", "content": "Hello!"}
    ],
    "max_tokens": 100,
    "temperature": 0.7,
    "stream": false
  }'
```

**Model Mapping:**

| OpenAI Model | Agent Hub Model |
|--------------|-----------------|
| `gpt-4`, `gpt-4-turbo`, `gpt-4o` | `claude-sonnet-4-5` |
| `gpt-3.5-turbo`, `gpt-4o-mini` | `claude-haiku-4-5` |

### GET /api/v1/models

List available models.

```bash
curl http://localhost:8003/api/v1/models
```

## Native API

Full-featured Agent Hub API with advanced capabilities.

### POST /api/complete

Generate a completion with session tracking and caching.

**Request:**
```json
{
  "model": "claude-sonnet-4-5",
  "messages": [
    {"role": "user", "content": "Hello!"}
  ],
  "max_tokens": 4096,
  "temperature": 1.0,
  "session_id": null,
  "project_id": "default",
  "enable_caching": true,
  "cache_ttl": "ephemeral",
  "persist_session": true,
  "budget_tokens": null,
  "auto_thinking": false,
  "tools": null,
  "enable_programmatic_tools": false
}
```

**Response:**
```json
{
  "content": "Hello! How can I help?",
  "model": "claude-sonnet-4-5-20250514",
  "provider": "claude",
  "usage": {
    "input_tokens": 10,
    "output_tokens": 12,
    "total_tokens": 22,
    "cache": {
      "cache_creation_input_tokens": 0,
      "cache_read_input_tokens": 100,
      "cache_hit_rate": 0.9
    }
  },
  "context_usage": {
    "used_tokens": 1234,
    "limit_tokens": 200000,
    "percent_used": 0.6,
    "remaining_tokens": 198766,
    "warning": null
  },
  "session_id": "abc123",
  "finish_reason": "end_turn",
  "from_cache": false,
  "thinking": null,
  "tool_calls": null
}
```

**Vision API (Images):**
```json
{
  "model": "claude-sonnet-4-5",
  "messages": [{
    "role": "user",
    "content": [
      {"type": "text", "text": "What's in this image?"},
      {
        "type": "image",
        "source": {
          "type": "base64",
          "media_type": "image/png",
          "data": "<base64-encoded-data>"
        }
      }
    ]
  }]
}
```

### POST /api/estimate

Estimate tokens and cost before making a request.

```json
{
  "model": "claude-sonnet-4-5",
  "messages": [{"role": "user", "content": "Hello"}],
  "max_tokens": 100
}
```

**Response:**
```json
{
  "input_tokens": 10,
  "estimated_output_tokens": 100,
  "total_tokens": 110,
  "estimated_cost_usd": 0.0033,
  "context_limit": 200000,
  "context_usage_percent": 0.055,
  "context_warning": null
}
```

## Sessions API

Manage conversation sessions.

### POST /api/sessions

Create a new session.

```json
{
  "project_id": "my-project",
  "provider": "claude",
  "model": "claude-sonnet-4-5"
}
```

### GET /api/sessions/{session_id}

Get session details.

### GET /api/sessions/{session_id}/messages

Get session message history.

### DELETE /api/sessions/{session_id}

Delete a session.

## Orchestration API

Multi-agent orchestration endpoints.

### POST /api/orchestration/query

Execute an orchestrated query with optional tracing.

```json
{
  "prompt": "Analyze this codebase",
  "model": "claude-sonnet-4-5",
  "provider": "claude",
  "options": {
    "working_dir": "/path/to/project",
    "max_turns": 10
  }
}
```

### GET /api/orchestration/traces/{trace_id}

Get trace details for debugging.

### GET /api/orchestration/traces/{trace_id}/spans

Get spans for a trace.

## Streaming

### SSE Streaming

Use `stream: true` for Server-Sent Events:

```bash
curl -X POST http://localhost:8003/api/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Accept: text/event-stream" \
  -d '{
    "model": "claude-sonnet-4-5",
    "messages": [{"role": "user", "content": "Tell a story"}],
    "stream": true
  }'
```

**Event Format:**
```
data: {"choices":[{"delta":{"content":"Once"},"index":0}]}

data: {"choices":[{"delta":{"content":" upon"},"index":0}]}

data: [DONE]
```

### SDK Streaming

```python
async for chunk in client.stream_sse(
    model="claude-sonnet-4-5",
    messages=[{"role": "user", "content": "Hello"}]
):
    print(chunk.content, end="")
```

## Extended Thinking

Enable Claude's extended thinking for complex reasoning.

```json
{
  "model": "claude-sonnet-4-5",
  "messages": [{"role": "user", "content": "Solve this complex problem..."}],
  "budget_tokens": 16000
}
```

**Response includes thinking:**
```json
{
  "content": "The answer is...",
  "thinking": {
    "content": "<detailed reasoning process>",
    "tokens": 12000,
    "budget_used": 16000,
    "cost_usd": 0.036
  }
}
```

### Auto-Thinking

Set `auto_thinking: true` to automatically enable thinking for complex requests:

```json
{
  "model": "claude-sonnet-4-5",
  "messages": [{"role": "user", "content": "ultrathink: solve this..."}],
  "auto_thinking": true
}
```

Triggers: `ultrathink`, `think hard`, `analyze`, `debug`, etc.

## Tool Calling

Provide tools for the model to call.

```json
{
  "model": "claude-sonnet-4-5",
  "messages": [{"role": "user", "content": "What's the weather in NYC?"}],
  "tools": [{
    "name": "get_weather",
    "description": "Get current weather",
    "input_schema": {
      "type": "object",
      "properties": {
        "location": {"type": "string"}
      },
      "required": ["location"]
    }
  }]
}
```

**Response with tool call:**
```json
{
  "content": "",
  "tool_calls": [{
    "id": "call_123",
    "name": "get_weather",
    "input": {"location": "NYC"}
  }],
  "finish_reason": "tool_use"
}
```

## Error Handling

| Status | Meaning |
|--------|---------|
| 400 | Invalid request |
| 401 | Authentication failed |
| 413 | Context window exceeded |
| 429 | Rate limit exceeded |
| 500 | Server error |

**Rate Limit Response:**
```json
{
  "detail": "Rate limit exceeded for claude"
}
```

Headers include `Retry-After` with seconds to wait.

## Headers

| Header | Description |
|--------|-------------|
| `Authorization` | `Bearer <api-key>` |
| `X-Skip-Cache` | `true` to bypass response cache |
| `Content-Type` | `application/json` |

## See Also

- [Getting Started](./getting-started.md)
- [Examples](./examples.md)
- [OpenAPI Docs](http://localhost:8003/docs)
