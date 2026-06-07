# Agent Hub

Self-hosted control plane for running, observing, and improving multi-provider
AI agents.

![Agent Hub dashboard](docs/screenshots/dashboard.png)

[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.13+-3776ab.svg)](https://python.org)
[![Next.js](https://img.shields.io/badge/Next.js-16-000.svg)](https://nextjs.org)

## Why it exists

Most agent demos stop at chat. Agent Hub adds the operational layer needed to
run agents as infrastructure: provider routing, persistent memory, sessions,
access control, cost/latency visibility, and operator dashboards.

## What you get

- Unified completions and streaming across configured providers such as Gemini,
  OpenAI, OpenRouter, Kimi, MiniMax, DeepSeek, xAI, and local OpenAI-compatible
  endpoints.
- PostgreSQL-backed memory and context injection.
- Named agents/personas, session history, request logs, and routing telemetry.
- Client registration and access-control surfaces for companion apps.
- Optional web research, browser, push, Telegram, and voice integrations.

The target user is a developer or operator running their own agent
infrastructure, not a hosted SaaS user.

## Requirements

Native development:

- Python 3.13+
- Node.js 20+
- pnpm 10+
- PostgreSQL 15+ with pgvector support recommended
- Redis
- Hatchet, for workflow/worker execution

Container development:

- Docker Engine with Docker Compose v2

## Quickstart: bundled Docker stack

```bash
git clone https://github.com/elias-leslie/agent-hub.git
cd agent-hub
cp .env.example .env
```

Set the generated secrets in `.env`:

```bash
python - <<'PY'
from pathlib import Path
import base64
import os
import secrets
path = Path('.env')
values = {
    'POSTGRES_PASSWORD': secrets.token_urlsafe(24),
    'AGENT_HUB_ENCRYPTION_KEY': base64.urlsafe_b64encode(os.urandom(32)).decode(),
    'AGENT_HUB_SECRET_KEY': secrets.token_urlsafe(32),
    'INTERNAL_SERVICE_SECRET': secrets.token_urlsafe(32),
}
lines = path.read_text().splitlines()
seen = set()
next_lines = []
for line in lines:
    key = line.split('=', 1)[0] if '=' in line and not line.startswith('#') else None
    if key in values:
        next_lines.append(f'{key}={values[key]}')
        seen.add(key)
    else:
        next_lines.append(line)
for key, value in values.items():
    if key not in seen:
        next_lines.append(f'{key}={value}')
path.write_text('\n'.join(next_lines) + '\n')
PY
```

Generate the Hatchet client token and start the stack:

```bash
./scripts/generate-hatchet-dev-token.sh .env
docker compose --env-file .env up -d --build
```

Open:

- Frontend: <http://localhost:3003>
- Backend health: <http://localhost:8003/health>

For Docker, leave `AGENT_HUB_DB_URL`, `AGENT_HUB_REDIS_URL`, and
`TEST_AGENT_HUB_DB_URL` blank. Compose injects container-internal service URLs.

## Native development

```bash
cp .env.example .env.local
pnpm install

cd backend
uv sync --all-extras --dev
uv run alembic upgrade head
uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8003
```

Worker, in another shell:

```bash
cd backend
uv run python -m app.worker
```

Frontend, in another shell from the repo root:

```bash
pnpm --filter frontend dev -- --hostname 0.0.0.0 --port 3003
```

## Configuration

Start from [`.env.example`](.env.example). Minimum native values:

```bash
AGENT_HUB_DB_URL=postgresql://agent_hub_app:PASSWORD@localhost:5432/agent_hub
AGENT_HUB_REDIS_URL=redis://localhost:6379/2
AGENT_HUB_ENCRYPTION_KEY=<44-character-fernet-key>
AGENT_HUB_SECRET_KEY=<random-secret>
HATCHET_CLIENT_TOKEN=<generated-token>
HATCHET_CLIENT_HOST_PORT=127.0.0.1:7070
HATCHET_CLIENT_TLS_STRATEGY=none
```

Provider API keys are optional. Configure only the providers you intend to use:
`ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, `OPENAI_API_KEY`, `OPENROUTER_API_KEY`,
`DEEPSEEK_API_KEY`, `KIMI_CODE_API_KEY`, `MOONSHOT_API_KEY`, `MINIMAX_API_KEY`,
`XAI_API_KEY`, `ZHIPU_API_KEY`, `NVIDIA_API_KEY`, and Cloudflare image keys.

If you expose Agent Hub beyond loopback, put it behind a reverse proxy or other
network controls and set strong client/internal secrets. Empty provider keys are
valid for local UI/API smoke tests, but provider-backed completions will be
unavailable until configured.

## Architecture

```text
agent-hub/
├── backend/            FastAPI app, provider adapters, memory, workflows, tests
├── frontend/           Next.js dashboard and operator UI
├── packages/           Shared SDKs and UI packages
├── examples/           SDK usage examples
├── docker-compose.yml  Standalone local Docker stack
├── scripts/            Bootstrap and service helpers
└── docs/screenshots/   Public-safe UI screenshots
```

## SDK

The Python SDK lives in `packages/agent-hub-client` and exposes the async client
used for completions, SSE streaming, and stateful sessions.

```bash
pip install -e packages/agent-hub-client
```

## Testing, linting, type checks, and build

Install dependencies first:

```bash
pnpm install --frozen-lockfile
cd backend && uv sync --all-extras --dev
```

Backend checks:

```bash
cd backend
uv run ruff check .
uv run ty check app
uv run pytest
uv build
```

Frontend checks:

```bash
pnpm --filter frontend lint
pnpm --filter frontend exec tsc --noEmit
pnpm --filter frontend exec vitest run
pnpm --filter frontend build
```

Smoke test a running app:

```bash
curl -fsS http://localhost:8003/health
curl -fsS http://localhost:3003/ >/dev/null
```

## Screenshots

The checked-in screenshots use safe demo/empty data and were inspected before
public release. To refresh them, start the local frontend and run:

```bash
cd frontend
AGENT_HUB_SCREENSHOT_BASE_URL=http://localhost:3003 pnpm screenshot:all
```

Inspect screenshots before committing them. Do not include provider tokens,
private sessions, private infrastructure details, personal data, or customer
content.

## Optional and degraded behavior

Agent Hub can boot without provider keys. Dashboards, health checks, sessions,
and configuration pages remain available. Provider completions, web research,
push, Telegram, browser, and voice integrations require their corresponding
configuration and should fail clearly when absent.

## License

Apache License 2.0. See [LICENSE](LICENSE) and [NOTICE](NOTICE).
Security reporting is described in [SECURITY.md](SECURITY.md).
