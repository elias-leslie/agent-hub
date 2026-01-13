# Agent Hub

Unified agentic AI service for Claude/Gemini workloads.

## URLs

| Service | URL |
|---------|-----|
| Frontend | http://localhost:3003 |
| Backend | http://localhost:8003 |
| API Docs | http://localhost:8003/docs |

## Commands

```bash
# Services
bash ~/agent-hub/scripts/restart.sh    # Start services
journalctl --user -u agent-hub-backend -f  # Logs

# Dev
cd backend && .venv/bin/pytest         # Tests
cd backend && .venv/bin/mypy app/      # Type check

# SummitFlow (st) - use --compact flag always
st --compact ready                     # Find work
st --compact context <id>              # Full context (PREFERRED - one call)
st update <id> --status running        # Claim
st close <id> --reason "Done"          # Complete
st bug "Fix: X" -p 2                   # Create bug
st import plan.json [--task <id>]      # Import/update from plan
# Full reference: st skill auto-triggers on task-xxx IDs
```

## OpenAI-Compatible API

Agent Hub provides OpenAI-compatible endpoints for drop-in integration with existing tools.

| Endpoint | Description |
|----------|-------------|
| `/api/v1/chat/completions` | Chat completions (streaming supported) |
| `/api/v1/models` | List available models |
| `/api/api-keys` | API key management |

**Model Mapping:**
- `gpt-4`, `gpt-4-turbo`, `gpt-4o` -> Claude Sonnet 4.5
- `gpt-3.5-turbo`, `gpt-4o-mini` -> Claude Haiku 4.5
- Native Claude/Gemini model names also accepted

**Usage with OpenAI SDK:**
```python
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:8003/api/v1",
    api_key="sk-ah-..."  # Optional - create via /api/api-keys
)

response = client.chat.completions.create(
    model="gpt-4",
    messages=[{"role": "user", "content": "Hello"}]
)
```

## Python SDK

Native Python client for Agent Hub API.

**Install:**
```bash
pip install -e packages/agent-hub-client
```

**Usage:**
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

See `packages/agent-hub-client/examples/` for more.

## Core Rules

1. Backend changes need UI visibility (vertical slice)
2. Track bugs immediately: `st bug "Fix: X"`
3. Consolidate over create (check existing code first)
4. Task completeness mandate: Tasks must achieve both technical goals AND spirit of intent. No stubs, skeletons, partial implementations, or minimal compliance. Every subtask is complete work, not a starting point.
5. **Claude uses OAuth, NOT API keys.** User has Max subscription. Claude adapter uses `claude` CLI for zero-cost OAuth auth. NEVER suggest/check for `ANTHROPIC_API_KEY`.

## Workflow

`/spec_it` → `/task_it` → `/do_it`

## Credentials

`~/.env.local`: `POSTGRES_ADMIN_URL`, `AGENT_HUB_DB_URL`, `AGENT_HUB_REDIS_URL`

## Reference Projects

Local copies in `references/` (gitignored). Update when needed for patterns/solutions.

| Project | Description | Clone |
|---------|-------------|-------|
| Auto-Claude | Multi-agent orchestration, extended thinking, SDK patterns | `git clone https://github.com/AndyMik90/Auto-Claude references/Auto-Claude` |
| vibe-kanban | Kanban board with AI features | `git clone https://github.com/BloopAI/vibe-kanban references/vibe-kanban` |

**Key patterns from Auto-Claude:**
- `services/sdk_utils.py`: ThinkingBlock extraction from OAuth stream
- `phase_config.py`: Thinking budget levels (low/medium/high)
- `ClaudeAgentOptions.max_thinking_tokens`: OAuth extended thinking
