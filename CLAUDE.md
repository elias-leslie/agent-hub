# CLAUDE.md

Agent Hub - Unified agentic AI service for Claude/Gemini workloads

---

## Quick Reference

| Action | Command |
|--------|---------|
| Find work | `st ready` |
| Claim work | `st update <id> --status running` |
| Complete | `st close <id> --reason "Done"` |
| Start services | `bash ~/agent-hub/scripts/restart.sh` |
| Run tests | `cd backend && .venv/bin/pytest` |
| Type check | `cd backend && .venv/bin/mypy app/` |
| Logs | `journalctl --user -u agent-hub-backend -f` |

---

## URLs

| Service | URL |
|---------|-----|
| Local Frontend | http://localhost:3002 |
| Local Backend | http://localhost:8002 |
| API Docs | http://localhost:8002/docs |

---

## Core Rules

1. **Backend changes need UI visibility** - Complete the vertical slice
2. **Track discovered bugs immediately** - `st create "Fix: X" -t bug`
3. **Consolidate over create** - Check for existing implementations before writing new code

---

## Development Workflow

```
/spec_it → /task_it → /do_it
```

| Command | Purpose |
|---------|---------|
| `/spec_it` | Discovery, interview, output spec.json |
| `/task_it` | Generate tasks with subtasks from spec |
| `/do_it` | Execute subtasks, commit, close task |

---

## Essential Commands

### st (SummitFlow Tasks)

```bash
# Core workflow
st ready                              # Tasks ready to work on
st update <id> --status running       # Claim task
st close <id> --reason "Done"         # Complete task

# Create
st create "Title" -t task -p 2 -d "Description"
st bug "Fix: X" -p 2                  # Shorthand for -t bug

# Subtasks & Steps
st subtask list <task-id>             # List subtasks
st step pass <task-id> <subtask-id> <step-number>  # Mark step passed
st subtask pass <task-id> <subtask-id>             # Mark subtask passed
```

---

**Version**: 1.0.0
