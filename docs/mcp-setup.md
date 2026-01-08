# MCP Setup Guide

Agent Hub supports the Model Context Protocol (MCP), enabling AI applications to use Agent Hub as a tool provider and allowing Agent Hub to consume tools from external MCP servers.

## Overview

Agent Hub implements MCP with:
- **MCP Server**: Expose Agent Hub's AI capabilities as MCP tools
- **MCP Client**: Connect to external MCP servers for additional tools
- **Registry Integration**: Discover servers from the official MCP Registry
- **OAuth Authentication**: RFC 9728 Protected Resource Metadata

## Quick Start

### Using Agent Hub as an MCP Server

Agent Hub exposes these MCP capabilities:

| Feature | Endpoint | Description |
|---------|----------|-------------|
| Tools | `/mcp/tools` | AI completion, chat, code analysis |
| Resources | `agenthub://sessions`, `agenthub://models` | Sessions and models |
| Prompts | `code_review`, `summarize`, `translate` | Pre-built prompts |
| Registry | `/mcp/registry` | External server discovery |

### Check MCP Server Status

```bash
curl http://localhost:8003/api/mcp/health
```

Response:
```json
{
  "status": "healthy",
  "server_name": "agent-hub",
  "tools_count": 4,
  "tools": ["complete", "chat", "analyze_code", "models"]
}
```

### Get Server Capabilities

```bash
curl http://localhost:8003/api/mcp/info
```

Response:
```json
{
  "name": "agent-hub",
  "version": "1.0.0",
  "protocol_version": "2025-11-25",
  "capabilities": {
    "tools": true,
    "resources": true,
    "prompts": true,
    "logging": true,
    "tasks": true
  }
}
```

## Connecting Claude Desktop to Agent Hub

Add Agent Hub as an MCP server in Claude Desktop's configuration:

**macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`
**Windows**: `%APPDATA%\Claude\claude_desktop_config.json`
**Linux**: `~/.config/Claude/claude_desktop_config.json`

```json
{
  "mcpServers": {
    "agent-hub": {
      "command": "npx",
      "args": [
        "@anthropic/mcp-proxy",
        "http://localhost:8003/api/mcp"
      ]
    }
  }
}
```

After adding, restart Claude Desktop. Agent Hub tools will be available in your conversations.

## Available MCP Tools

### complete

Generate AI completions using Agent Hub's unified provider system.

```json
{
  "name": "complete",
  "input": {
    "prompt": "Explain quantum computing",
    "model": "claude-sonnet-4-5",
    "max_tokens": 4096,
    "temperature": 1.0
  }
}
```

### chat

Multi-turn chat completion with conversation history.

```json
{
  "name": "chat",
  "input": {
    "messages": [
      {"role": "user", "content": "Hello"},
      {"role": "assistant", "content": "Hi!"},
      {"role": "user", "content": "How are you?"}
    ],
    "model": "claude-sonnet-4-5",
    "system": "You are helpful"
  }
}
```

### analyze_code

Analyze code for quality, security, or explanation.

```json
{
  "name": "analyze_code",
  "input": {
    "code": "def hello(): pass",
    "language": "python",
    "analysis_type": "review"
  }
}
```

Analysis types: `review`, `explain`, `improve`, `security`

### models

List available AI models.

```json
{
  "name": "models",
  "input": {}
}
```

## MCP Resources

Access Agent Hub data through MCP resources.

### agenthub://sessions

List active sessions.

```bash
curl http://localhost:8003/api/mcp/resources/sessions
```

### agenthub://sessions/{session_id}

Get session details.

### agenthub://models

List available models.

## MCP Prompts

Pre-built prompts for common workflows.

### code_review

Generate a code review request.

Parameters:
- `code` (required): Source code to review
- `language` (optional): Programming language (default: python)

### summarize

Generate a summarization request.

Parameters:
- `text` (required): Text to summarize
- `style` (optional): concise, detailed, or bullet_points

### translate

Generate a translation request.

Parameters:
- `text` (required): Text to translate
- `target_language` (required): Target language (e.g., Spanish, French)

## Connecting to External MCP Servers

Agent Hub can consume tools from external MCP servers.

### Discover Servers

Search the official MCP Registry:

```bash
curl "http://localhost:8003/api/mcp/registry?search=filesystem"
```

Response:
```json
{
  "servers": [
    {
      "name": "filesystem-server",
      "description": "File system access",
      "transport": "stdio",
      "is_local": false
    }
  ],
  "count": 1,
  "cached": true
}
```

### Configure Local Servers

Add local MCP servers via environment variable:

```bash
export MCP_LOCAL_SERVERS='[{"name": "my-server", "description": "Custom server", "url": "http://localhost:9000"}]'
```

Or in `~/.env.local`:

```
MCP_LOCAL_SERVERS=[{"name":"my-server","url":"http://localhost:9000"}]
```

## OAuth Authentication

Agent Hub implements MCP OAuth per RFC 9728.

### Protected Resource Metadata

```bash
curl http://localhost:8003/.well-known/oauth-protected-resource
```

Response:
```json
{
  "authorization_servers": ["http://localhost:8003/api/api-keys"],
  "bearer_methods_supported": ["header"],
  "scopes_supported": [
    "mcp:complete",
    "mcp:chat",
    "mcp:tools",
    "mcp:resources",
    "mcp:prompts",
    "mcp:*"
  ]
}
```

### Authenticating Requests

Use Agent Hub API keys as Bearer tokens:

```bash
# Create API key
curl -X POST http://localhost:8003/api/api-keys \
  -H "Content-Type: application/json" \
  -d '{"name": "mcp-client"}'

# Use with MCP requests
curl -H "Authorization: Bearer sk-ah-..." \
  http://localhost:8003/api/mcp/tools
```

### WWW-Authenticate Response

On 401, the server returns:

```
WWW-Authenticate: Bearer resource_metadata="http://localhost:8003/.well-known/oauth-protected-resource"
```

### Scope Errors (403)

When authenticated but lacking scope:

```
WWW-Authenticate: Bearer error="insufficient_scope", scope="mcp:tools", resource_metadata="..."
```

## Configuration

Environment variables for MCP configuration:

| Variable | Default | Description |
|----------|---------|-------------|
| `MCP_REGISTRY_URL` | `https://registry.modelcontextprotocol.io` | Official MCP Registry URL |
| `MCP_LOCAL_SERVERS` | (empty) | JSON list of local MCP servers |
| `MCP_REGISTRY_CACHE_TTL` | `300` | Registry cache TTL in seconds |
| `MCP_BASE_URL` | (auto) | Base URL for this MCP server |
| `MCP_OAUTH_AUTH_SERVERS` | (empty) | Comma-separated OAuth servers |
| `MCP_REQUIRE_AUTH` | `false` | Require auth for MCP endpoints |

## Troubleshooting

### MCP Server Not Responding

1. Check server health: `curl http://localhost:8003/api/mcp/health`
2. Verify server is running: `journalctl --user -u agent-hub-backend -f`
3. Check logs for errors

### Tools Not Appearing in Claude Desktop

1. Verify config file path is correct
2. Restart Claude Desktop after config changes
3. Check Claude Desktop logs for connection errors

### Registry Connection Failed

1. Check network connectivity
2. Verify `MCP_REGISTRY_URL` is accessible
3. Registry results are cached - use `force_refresh=true` to bypass

### Authentication Errors

1. Verify API key is valid and not expired
2. Check `Authorization: Bearer` header format
3. Ensure key has required scopes

## API Reference

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/mcp/health` | GET | Server health status |
| `/api/mcp/info` | GET | Server capabilities |
| `/api/mcp/tools` | GET | List available tools |
| `/api/mcp/registry` | GET | List registry servers |
| `/.well-known/oauth-protected-resource` | GET | OAuth metadata |

## See Also

- [API Guide](./api-guide.md)
- [Getting Started](./getting-started.md)
- [MCP Specification](https://modelcontextprotocol.io)
- [MCP Registry](https://registry.modelcontextprotocol.io)
