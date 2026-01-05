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

## Core Rules

1. Backend changes need UI visibility (vertical slice)
2. Track bugs immediately: `st bug "Fix: X"`
3. Consolidate over create (check existing code first)

## Workflow

`/spec_it` → `/task_it` → `/do_it`

## Credentials

`~/.env.local`: `POSTGRES_ADMIN_URL`, `AGENT_HUB_DB_URL`, `AGENT_HUB_REDIS_URL`
