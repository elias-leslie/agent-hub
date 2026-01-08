# Agent Hub vs Claude Code Feature Parity

Comparison of Agent Hub features against Claude Code (Anthropic's official CLI).

**Legend:** Supported | Partial | Not Supported | N/A

## Authentication

| Feature | Agent Hub | Claude Code | Notes |
|---------|-----------|-------------|-------|
| API Key Authentication | Supported | Supported | `ANTHROPIC_API_KEY` env var |
| OAuth / Claude.ai Login | Not Supported | Supported | Claude Code uses `/login` command |
| AWS Bedrock | Not Supported | Supported | IAM-based authentication |
| Google Vertex AI | Not Supported | Supported | GCP service accounts |
| API Key Management UI | Supported | Not Supported | Agent Hub has `/api/api-keys` CRUD |
| Per-request API Key | Supported | Supported | Header-based auth |

**Gap:** OAuth is critical for Claude Max subscription access. API keys work but OAuth enables higher rate limits.

## Streaming

| Feature | Agent Hub | Claude Code | Notes |
|---------|-----------|-------------|-------|
| Text Streaming | Supported | Supported | SSE format |
| Claude Streaming | Supported | Supported | Full support |
| Gemini Streaming | Not Supported | N/A | Blocked by SDK limitation |
| JSON Streaming | Supported | Supported | Newline-delimited JSON |
| Partial Messages | Supported | Supported | Delta events |

**Gap:** Gemini streaming requires google-genai SDK update.

## Tool Calling

| Feature | Agent Hub | Claude Code | Notes |
|---------|-----------|-------------|-------|
| Function/Tool Definition | Supported | Supported | OpenAI-compatible format |
| Tool Results | Supported | Supported | tool_use/tool_result blocks |
| Parallel Tool Calls | Supported | Supported | Multiple tools per turn |
| MCP Protocol | Partial | Supported | Client exists, server not exposed |
| Built-in Tools | Not Supported | Supported | 14 built-in tools (Bash, Edit, etc.) |
| Permission-based Control | Not Supported | Supported | Fine-grained tool permissions |

**Gap:** MCP client mode exists but not wired to API. Built-in tools are Claude Code specific.

## Thinking/Reasoning

| Feature | Agent Hub | Claude Code | Notes |
|---------|-----------|-------------|-------|
| Extended Thinking | Not Supported | Supported | `ultrathink` keyword, Alt+T |
| Max Thinking Tokens | Not Supported | Supported | `MAX_THINKING_TOKENS` env var |
| Thinking Display | Not Supported | Supported | Ctrl+O toggle |
| Plan Mode | Not Supported | Supported | Read-only analysis mode |

**Gap:** Extended thinking is a powerful feature for complex reasoning tasks.

## Vision/Image Support

| Feature | Agent Hub | Claude Code | Notes |
|---------|-----------|-------------|-------|
| Image Input (base64) | Supported | Supported | `image` content blocks |
| Multiple Images | Supported | Supported | Array of content blocks |
| Image Analysis | Supported | Supported | Via Claude/Gemini vision |
| PDF Support | Not Supported | Supported | Page-by-page processing |
| Drag-drop/Paste | N/A | Supported | CLI-specific feature |

**Gap:** PDF support could be added with pdfplumber or similar.

## Caching

| Feature | Agent Hub | Claude Code | Notes |
|---------|-----------|-------------|-------|
| Prompt Caching | Not Supported | Supported | Automatic, reduces cost |
| Cache Configuration | Not Supported | Supported | Per-model disable flags |
| Response Caching | Supported | Not Supported | Redis-based (Agent Hub specific) |

**Gap:** Anthropic prompt caching could reduce costs significantly.

## Context Management

| Feature | Agent Hub | Claude Code | Notes |
|---------|-----------|-------------|-------|
| Session Persistence | Supported | Supported | Database-backed |
| Session History | Supported | Supported | Full conversation retrieval |
| Max Turns Limit | Supported | Supported | `max_turns` parameter |
| Token Counting | Supported | Supported | Per-request tracking |
| Cost Tracking | Partial | Supported | Token counts, not USD |
| 1M Context Window | Supported | Supported | Model-dependent |

## OpenAI Compatibility

| Feature | Agent Hub | Claude Code | Notes |
|---------|-----------|-------------|-------|
| `/v1/chat/completions` | Supported | N/A | Drop-in replacement |
| `/v1/models` | Supported | N/A | Model listing |
| GPT Model Aliases | Supported | N/A | gpt-4 -> Claude mapping |
| Function Calling Format | Supported | N/A | OpenAI-style tools |

**Advantage:** Agent Hub provides OpenAI-compatible API that Claude Code doesn't need.

## Multi-Provider Support

| Feature | Agent Hub | Claude Code | Notes |
|---------|-----------|-------------|-------|
| Claude Provider | Supported | Supported | Primary provider |
| Gemini Provider | Supported | Not Supported | Agent Hub advantage |
| Provider Abstraction | Supported | N/A | Unified interface |
| Model Routing | Supported | N/A | Automatic provider selection |

**Advantage:** Agent Hub supports multiple providers through a single API.

## Advanced Features (Claude Code Specific)

| Feature | Agent Hub | Claude Code | Notes |
|---------|-----------|-------------|-------|
| CLAUDE.md Memory | N/A | Supported | Project instructions |
| Plugins | N/A | Supported | Extensibility system |
| Skills | N/A | Supported | Reusable prompts |
| Hooks | N/A | Supported | Pre/post tool execution |
| Subagents | N/A | Supported | Specialized agent delegation |
| Sandboxing | N/A | Supported | Bash command isolation |
| IDE Integration | N/A | Supported | VS Code, JetBrains |
| Git Integration | N/A | Supported | PR/commit workflows |

**Note:** These features are CLI-specific and not applicable to Agent Hub's API service model.

## Summary

### Agent Hub Advantages
- Multi-provider support (Claude + Gemini)
- OpenAI-compatible API for drop-in replacement
- Session persistence with database backend
- API key management UI
- Response caching with Redis

### Features to Consider Adding
1. **OAuth Authentication** - Enable Claude Max subscription access
2. **Extended Thinking** - Pass through thinking parameters
3. **Prompt Caching** - Leverage Anthropic's caching for cost reduction
4. **Gemini Streaming** - Blocked by SDK, monitor for updates

### Not Applicable
- CLI-specific features (plugins, hooks, sandboxing, IDE integration) are not applicable to Agent Hub's API service model
- Agent Hub serves as a backend API, not an interactive CLI

## Roadmap

| Priority | Feature | Rationale |
|----------|---------|-----------|
| P1 | OAuth Authentication | Unlock Claude Max rate limits |
| P1 | Extended Thinking | Enable complex reasoning tasks |
| P2 | Prompt Caching | Cost reduction |
| P2 | Gemini Streaming | Feature parity across providers |
| P3 | PDF Support | Document analysis use case |
