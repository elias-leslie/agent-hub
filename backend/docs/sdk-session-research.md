# Claude SDK Session Resumption Research

Research findings for Agent Hub SDK integration options.

## Executive Summary

The Claude Agent SDK supports session resumption via session IDs. However, the base Messages API does NOT have server-side session management - you must always send full conversation history. For stateless APIs, **prompt caching** provides the cost/latency benefits of session resumption without server state.

## SDK Session Management (Claude Agent SDK)

### How Sessions Work

The Claude Agent SDK automatically creates sessions and returns session IDs in the initial system message.

```python
from claude_agent_sdk import query, ClaudeAgentOptions

session_id = None

async for message in query(
    prompt="Help me build a web application",
    options=ClaudeAgentOptions(model="claude-sonnet-4-5")
):
    if hasattr(message, 'subtype') and message.subtype == 'init':
        session_id = message.data.get('session_id')
```

### Resuming Sessions

Use the `resume` parameter with a session ID:

```python
async for message in query(
    prompt="Continue where we left off",
    options=ClaudeAgentOptions(resume=session_id)
):
    print(message)
```

### Forking Sessions

Create branches without modifying original:

```python
async for message in query(
    prompt="Try different approach",
    options=ClaudeAgentOptions(
        resume=session_id,
        fork_session=True
    )
):
    print(message)
```

### Known Limitations

1. **No Historical Message Retrieval**: When resuming via SDK, you cannot retrieve the previous messages - only new messages stream.
2. **Session IDs Change on Resume**: The `session_id` provided to hooks is a new UUID, not the original.
3. **Local Storage**: Sessions stored in `~/.claude/projects/` - requires SDK to access.

## Base Messages API (What Agent Hub Uses)

The Anthropic Messages API is **stateless**:
- No server-side conversation tracking
- No conversation_id parameter
- Full message history must be sent each request
- Claude maintains context only through provided messages

### Implication for Agent Hub

Agent Hub already implements session management:
- Sessions stored in PostgreSQL
- Full message history reconstructed per request
- This is the correct architecture for the Messages API

## Prompt Caching (Cost Optimization Alternative)

Prompt caching provides session-like benefits without server state.

### How It Works

1. Mark static content with `cache_control: {"type": "ephemeral"}`
2. Identical prefixes are cached for 5 minutes (refreshed on use)
3. Cache hits cost **10%** of base input token price
4. Cache writes cost **25% more** than base input tokens

### Implementation Example

```python
response = client.messages.create(
    model="claude-sonnet-4-5",
    max_tokens=1024,
    system=[
        {
            "type": "text",
            "text": "System instructions...",
            "cache_control": {"type": "ephemeral"}
        }
    ],
    messages=[
        {"role": "user", "content": "Hello"},
        {"role": "assistant", "content": "Hi there!"},
        {
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": "What's the weather?",
                    "cache_control": {"type": "ephemeral"}
                }
            ]
        }
    ]
)
```

### Cache Requirements

| Model | Minimum Tokens |
|-------|---------------|
| Claude Opus 4.5 | 4096 |
| Claude Sonnet 4.5/4, Opus 4/4.1 | 1024 |
| Claude Haiku 4.5 | 4096 |
| Claude Haiku 3.5/3 | 2048 |

### Best Practices

1. Place static content at prompt beginning
2. Mark end of reusable content with `cache_control`
3. System → Tools → Conversation history order
4. Up to 4 cache breakpoints allowed
5. Cache refreshes on each hit (5-min rolling window)

### Extended Cache (1 Hour)

For longer sessions:

```python
"cache_control": {
    "type": "ephemeral",
    "ttl": "1h"
}
```

## Recommendations for Agent Hub

### What Agent Hub Should Do

1. **Keep current session architecture**: PostgreSQL storage + full history reconstruction is correct
2. **Add prompt caching support**: Add `cache_control` to system prompts and conversation history
3. **Do NOT try to use Claude Agent SDK sessions**: Those are for local CLI usage, not server APIs

### Implementation Plan

1. Add `cache_control` field support to Message model
2. Add caching logic to Claude adapter:
   - Cache system prompts (rarely change)
   - Cache conversation history up to last N messages
3. Track cache metrics: `cache_creation_input_tokens`, `cache_read_input_tokens`
4. Configure minimum token thresholds per model

### Expected Benefits

- 85% latency reduction for repeated system prompts
- 90% cost reduction for cached content
- No architecture changes needed

## References

- [Claude Session Management](https://platform.claude.com/docs/en/agent-sdk/sessions)
- [Prompt Caching](https://platform.claude.com/docs/en/build-with-claude/prompt-caching)
- [Anthropic News: Prompt Caching](https://www.anthropic.com/news/prompt-caching)
