# Agent Hub

AI agent memory and orchestration system with multi-model completion API and PostgreSQL-backed semantic memory.

## Overview

Agent Hub provides a unified API for AI agent completion, memory management, and multi-agent orchestration. It supports multiple model providers (Claude, Gemini, OpenAI, OpenRouter), manages persistent memory through PostgreSQL + pgvector, and handles agent configuration, access control, and session management.

Key capabilities:
- **Completion API** - Unified multi-model completion with streaming, tool use, vision, and extended thinking
- **Memory System** - Progressive context injection with tiered episodes (mandates, guardrails, references)
- **Agent Orchestration** - Multi-agent routing, sub-agent execution, parallel execution, maker-checker patterns
- **Access Control** - Client credentials, API keys, tier-based routing, usage tracking
- **Voice** - Speech-to-text (Whisper) and text-to-speech (Edge TTS)
- **MCP Server** - Model Context Protocol integration for memory and instructions

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | FastAPI, Python 3.13+, SQLAlchemy 2.0, Pydantic 2 |
| Frontend | Next.js 16, React 19, TypeScript, Tailwind CSS 4 |
| Database | PostgreSQL (relational + pgvector memory) |
| Caching | Redis |
| Workflows | Hatchet (completion, observation, scheduled tasks) |
| AI Providers | Anthropic Claude, Google Gemini, OpenAI, OpenRouter |
| Quality | Ruff, Mypy, pytest, Vitest, Playwright, Biome |

## Architecture

```
agent-hub/
├── backend/
│   ├── app/
│   │   ├── api/           # REST endpoint routers
│   │   ├── services/      # Business logic
│   │   │   ├── completion/    # Multi-model completion
│   │   │   │   └── adapters/  # Claude, Gemini, OpenAI, OpenRouter
│   │   │   ├── memory/        # PostgreSQL + pgvector memory system
│   │   │   ├── agent/         # Agent management
│   │   │   └── auth/          # Client authentication
│   │   ├── models/        # SQLAlchemy ORM models
│   │   └── workflows/     # Hatchet workflow definitions
│   ├── mcp_server.py      # MCP server for memory/instructions
│   └── tests/
├── frontend/
│   └── src/
│       ├── app/           # Pages (App Router)
│       ├── components/    # React components
│       ├── hooks/         # Custom React hooks
│       └── lib/           # API clients, utilities
├── packages/
│   ├── agent-hub-client/  # Python SDK (v0.3.0)
│   └── passport-client/   # React auth component library
├── examples/              # SDK usage examples
└── scripts/               # Service management
```

## Key Features

### Completion API
- Unified interface across Claude, Gemini, OpenAI, and OpenRouter
- Server-Sent Events streaming for real-time responses
- Extended thinking mode support
- Tool/function calling with multi-turn execution
- Vision (image understanding) capabilities
- Prompt caching for repeated content
- Session-based multi-turn conversations with branching

### Memory System
- **Progressive context injection** - Mandates (always enforced) → Guardrails (protective rules) → References (searchable knowledge)
- **Semantic memory** - PostgreSQL + pgvector for memory storage and retrieval
- **Episode lifecycle** - Create, search, promote, deduplicate, and optimize memory episodes
- **Session continuity** - Cross-session context preservation
- **Auto-tier optimization** - Promotion and demotion based on usage patterns

### Agent Orchestration
- Route requests to specialized agents by slug
- Hierarchical sub-agent composition
- Parallel multi-agent execution
- Global instructions and per-agent prompt configuration

### Access Control
- Client management with API key authentication
- Tier classification (free, pro, enterprise)
- Per-client usage tracking (tokens, requests)
- Credential encryption (Fernet)

### MCP Server
- `memory://context` resource - Progressive memory context
- `system_instruction` prompt - System instructions for agents
- `save_learning()` tool - Save learnings to memory with confidence scoring

## Ports

| Service | Port |
|---------|------|
| Frontend (Next.js) | 3003 |
| Backend (FastAPI) | 8003 |

Infrastructure dependencies:
- PostgreSQL: 5432
- Redis: 6379
- Hatchet: 8888 (HTTP) / 7077 (gRPC)

## Getting Started

### Prerequisites

- Python 3.13+
- Node.js 20+
- PostgreSQL 15+
- Redis

### Backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# Run migrations
alembic upgrade head

# Start server
uvicorn app.main:app --reload --host 0.0.0.0 --port 8003

# Start Hatchet worker (separate terminal)
python -m app.worker
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```

### Environment

Create `~/.env.local` with:

```bash
# Required
AGENT_HUB_DB_URL=postgresql://agent_hub_app:password@localhost:5432/agent_hub
AGENT_HUB_REDIS_URL=redis://localhost:6379/2
AGENT_HUB_ENCRYPTION_KEY=<44-char-fernet-key>
AGENT_HUB_SECRET_KEY=<random-urlsafe-token>

# AI providers (at least one)
ANTHROPIC_API_KEY=
GEMINI_API_KEY=

# Optional
CORS_ORIGINS=http://localhost:3003
LOG_LEVEL=INFO
```

## Frontend Pages

| Page | Description |
|------|-------------|
| `/` | Dashboard overview |
| `/agents` | Agent configuration and management |
| `/memory` | Memory episode browser and search |
| `/sessions` | Conversation history |
| `/chat` | Chat interface |
| `/access-control` | Client and API key management |
| `/prompts` | Prompt template editor |
| `/monitoring/requests` | Request audit logs |
| `/admin` | Admin panel and database inspection |
| `/dashboard` | Analytics and metrics |

## SDK and Examples

### Python SDK

```bash
pip install agent-hub-client  # from packages/agent-hub-client
```

### Examples

| File | Description |
|------|-------------|
| `examples/simple_completion.py` | Basic completion request |
| `examples/streaming_example.py` | SSE streaming responses |
| `examples/session_management.py` | Multi-turn conversations |
| `examples/orchestration_example.py` | Multi-agent queries |
| `examples/sdk_example.py` | Full SDK feature demo |

## Database

18+ tables across PostgreSQL (agents, sessions, memory episodes, credentials, usage stats, telemetry, pgvector-backed embeddings). Schema managed via Alembic migrations.

## Scheduled Tasks

| Task | Schedule | Description |
|------|----------|-------------|
| Session cleanup | Every 5 min | Remove stale sessions |
| Memory cleanup | Sunday 3 AM | Clean unused memory episodes |
| Tier optimizer | Daily 2 AM | Auto-optimize memory tiers |

## Services

Managed via systemd user services:

```bash
scripts/status.sh     # Check service status
scripts/restart.sh    # Restart all services
```

## Testing

```bash
# Backend
cd backend
pytest tests/ -v --cov=app

# Frontend
cd frontend
npm run test          # Unit tests (Vitest)
npm run test:e2e      # E2E tests (Playwright)
```

## License

Private project - All rights reserved
