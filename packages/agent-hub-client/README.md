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

### Canonical application integration (0.4.1)

Use this package for completions, agent metadata (`get_agent`) and context
previews (`preview_agent`). Construct it from the application's configured
Agent Hub URL and registered client ID, with a stable `request_source`.
Keep provider credentials, model assignments, fallbacks and shared prompts in
Agent Hub. Applications own their domain validation, not alternative transports.

Pass `agent_slug` and `project_id` on completions. Omit `model` for normal agent
routing; a catalog `model` override is supported for explicit diagnostics and
is never silently ignored. Conflicting model mentions are rejected. Use
`disable_agent_fallbacks=True` when the selected provider is a requirement.
The response preserves actual model and fallback metadata; terminal provider
errors raise even if an older server incorrectly returns HTTP 200.

`system_prompt` supplements canonical context. `response_format` supplies the
JSON contract and validates the answer. Neither replaces application validation
before changing records. Provider quotas and failures must not be represented
as empty successful answers.

Build the wheel once from `packages/agent-hub-client`, then vendor that identical
versioned wheel in consumers and refresh their `uv.lock`. Never edit installed
SDK files or maintain copied SDK implementations. Existing sync and async clients
use the same response handler and identity configuration.
