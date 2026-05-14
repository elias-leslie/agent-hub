# Agent Hub

Self-hosted control plane for running, observing, and improving multi-provider AI agents.

![Agent Hub dashboard](docs/screenshots/dashboard.png)

## Why It Exists

Most agent demos stop at chat. Agent Hub adds the operational layer that real deployments need:

- Unified completions across routed providers such as Gemini, OpenAI, OpenRouter, Kimi, and MiniMax
- Persistent PostgreSQL-backed memory with progressive context injection
- A named persona workspace with heartbeat automation and self-improvement loops
- Operator dashboards for sessions, regressions, routing pressure, and cost

The target user is a developer or operator running agent infrastructure, not a general end user.

## What You Get

- `/dashboard`: system health, usage, and provider status
- `/persona`: live persona workspace and heartbeat activity
- `/arena`: benchmark and regression pressure across agents
- `/sessions`: conversation history and drill-down inspection
- `/memory`: searchable memory episodes and reference tuning
- `/access-control`: client registration and execution permissions

## Quickstart

### Prerequisites

- Python 3.13+
- Node.js 20+
- PostgreSQL
- Redis
- Docker, if you want the bundled compose stack

### Option A: Bundled Docker Stack

```bash
cp .env.example .env
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
python -c "import secrets; print(secrets.token_urlsafe(32))"
./scripts/generate-hatchet-dev-token.sh .env
docker compose up -d --build
```

Open:

- Frontend: `http://localhost:3003`
- Backend: `http://localhost:8003`

For the bundled Docker stack, leave `AGENT_HUB_DB_URL`, `AGENT_HUB_REDIS_URL`, and `TEST_AGENT_HUB_DB_URL` blank in `.env`. Compose injects the internal service URLs.

### Option B: Native Local Run

```bash
cp .env.example .env.local
pnpm install

cd backend
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
alembic upgrade head
uvicorn app.main:app --reload --host 0.0.0.0 --port 8003
```

In a second shell:

```bash
cd /path/to/agent-hub/backend
source .venv/bin/activate
python -m app.worker
```

In a third shell:

```bash
cd /path/to/agent-hub/frontend
pnpm dev --hostname 0.0.0.0 --port 3003
```

## Environment

Start from [`.env.example`](.env.example). The minimum required variables for native installs are:

```bash
AGENT_HUB_DB_URL=postgresql://agent_hub_app:PASSWORD@localhost:5432/agent_hub
AGENT_HUB_REDIS_URL=redis://localhost:6379/2
AGENT_HUB_ENCRYPTION_KEY=<44-char-fernet-key>
AGENT_HUB_SECRET_KEY=<random-urlsafe-token>
HATCHET_CLIENT_TOKEN=<generated-by-scripts/generate-hatchet-dev-token.sh>
HATCHET_CLIENT_HOST_PORT=127.0.0.1:7070
HATCHET_CLIENT_TLS_STRATEGY=none
GEMINI_API_KEY=
OPENAI_API_KEY=
OPENROUTER_API_KEY=
```

If you are exposing Agent Hub beyond the local machine, do not rely on permissive defaults alone. Put it behind a reverse proxy or equivalent network controls.

## Architecture

```text
agent-hub/
├── backend/                 FastAPI app, workflows, models, tests
├── frontend/                Next.js dashboard and operator UI
├── packages/                Shared SDKs and frontend packages
├── examples/                SDK usage examples
├── docker-compose.yml       Standalone Docker stack
└── scripts/                 Bootstrap helpers
```

## SDK

The Python SDK lives in [packages/agent-hub-client](packages/agent-hub-client) and exposes the async client used for completions, SSE streaming, and stateful sessions.

```bash
pip install -e packages/agent-hub-client
```

## Testing

Use the shared quality wrapper from the repo root:

```bash
st check --check
```

Frontend-only checks:

```bash
st check --frontend-only
```

Targeted backend suites:

```bash
st check pytest -- backend/tests/path/to/test_file.py
```

## Screenshots

The docs screenshot flow uses `st browser`, not local Playwright:

```bash
cd frontend
pnpm screenshot:all
```

Base URL resolution order:

1. `AGENT_HUB_SCREENSHOT_BASE_URL`
2. `network.host_ip` from [`.index.yaml`](.index.yaml)
3. `http://localhost:3003`

When `st browser` is attached to the shared browser VM, do not use `localhost`; the remote browser must reach the app over the host IP.

## License

Apache License 2.0. See [LICENSE](LICENSE), [NOTICE](NOTICE), and [SECURITY.md](SECURITY.md).
