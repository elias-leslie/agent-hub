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

# SummitFlow (st)
st ready                               # Find work
st update <id> --status running        # Claim
st close <id> --reason "Done"          # Complete
st create "Title" -t task -p 2         # Create task
st bug "Fix: X" -p 2                   # Create bug
st subtask list <task-id>              # List subtasks
st step pass <task-id> <sub-id> <n>    # Pass step
st subtask pass <task-id> <sub-id>     # Pass subtask
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

## Core Rules

1. Backend changes need UI visibility (vertical slice)
2. Track bugs immediately: `st bug "Fix: X"`
3. Consolidate over create (check existing code first)
4. Task completeness mandate: Tasks must achieve both technical goals AND spirit of intent. No stubs, skeletons, partial implementations, or minimal compliance. Every subtask is complete work, not a starting point.

## Workflow

`/spec_it` → `/task_it` → `/do_it`

## Credentials

`~/.env.local`: `POSTGRES_ADMIN_URL`, `AGENT_HUB_DB_URL`, `AGENT_HUB_REDIS_URL`
