# Agent Hub

Unified agentic AI service for Claude/Gemini workloads.

## Quick Start

**Read `.index.yaml` first** - contains pages, endpoints, tables, tasks, and folder structure.

## Key Locations

| Area | Path |
|------|------|
| API routes | `backend/app/api/` |
| Services | `backend/app/services/` |
| Models | `backend/app/models.py` |
| Memory system | `backend/app/services/memory/` |
| Frontend pages | `frontend/src/app/` |
| Components | `frontend/src/components/` |
| Tests | `backend/tests/`, `frontend/src/**/*.test.ts` |

## Commands

```bash
# Services
bash ~/agent-hub/scripts/restart.sh
journalctl --user -u agent-hub-backend -f

# Backend
cd backend && .venv/bin/pytest
cd backend && .venv/bin/mypy app/
cd backend && alembic upgrade head

# Frontend
cd frontend && npm run build
systemctl --user restart agent-hub-frontend
```

## URLs

- Frontend: http://localhost:3003
- Backend: http://localhost:8003
- API Docs: http://localhost:8003/docs

## Python SDK

```bash
pip install -e packages/agent-hub-client
```


