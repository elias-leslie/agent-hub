# Agent Hub

AI agent memory and orchestration system with Graphiti-based knowledge graph.

**Project context injected via memory system at session start.**

See `~/.claude/CLAUDE.md` for memory API reference.

## Architecture

```
agent-hub/
├── backend/           # Backend (FastAPI, port 8003)
│   ├── app/
│   │   ├── api/       # REST endpoints
│   │   ├── services/  # Business logic (memory, agents, completion)
│   │   ├── models/    # SQLAlchemy models
│   │   └── workflows/  # Hatchet workflow definitions
│   └── tests/
├── frontend/          # Frontend (Next.js, port 3003)
│   └── src/
│       ├── app/       # Pages
│       ├── components/# React components
│       └── lib/       # Utilities
├── scripts/           # Build, service, and systemd scripts
│   └── systemd/       # Systemd service definitions (symlinked)
└── packages/
    └── graphiti/       # Vendored Graphiti fork
```

## Key Services

- **Memory System**: Progressive context injection (mandates, guardrails, references)
- **Agent Completion**: Multi-model agent orchestration API
- **MCP Server**: Model Context Protocol integration (`backend/mcp_server.py`)

## Database

PostgreSQL + Neo4j (Graphiti knowledge graph). Redis for caching. Hatchet for workflow orchestration.
