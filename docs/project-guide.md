# Agent Hub project guide

[Project overview](../README.md). This guide retains detailed setup, operating contracts, and verification notes. Run shell commands from the repository root unless a step changes directory.

## What you get

**Provider routing**

- Unified completions and SSE streaming across many providers from one API:
  Gemini, OpenAI, OpenRouter, DeepSeek, Kimi/Moonshot, MiniMax, xAI, Zhipu (GLM),
  NVIDIA, Cloudflare Workers AI, OpenAI Codex, and any local OpenAI-compatible
  endpoint. (Anthropic/Claude is catalogued for reference but excluded from
  workload routing by design.)
- Model-to-provider resolution from a catalog, per-agent routing with fallbacks,
  a provider circuit breaker, and runtime provider-health probing.
- Image generation across Gemini, NVIDIA, MiniMax, and Cloudflare image adapters.

**Memory, sessions, and agents**

- PostgreSQL + pgvector memory ("memory-first"): semantic search, episodes,
  learning extraction, tiering/promotion/retirement, and tiered context injection
  into completions, with citation tracking.
- Stateful sessions with full history, branching, ingestion, LLM-generated
  summaries, and token accounting.
- Named agents with version history and per-agent model routing. Agents can dispatch background agent runs ("wakes"),
  each in its own session.
- Memory archive: an episode can be archived and restored. Archived episodes
  stay stored but are never injected into context.
- A DB-backed prompts catalog with revisions/restore and per-agent assignments.

**Orchestration and tools**

- An agentic tool loop in `/api/complete` that can delegate work to other agents
  as child sessions, plus a committee roundtable endpoint
  (`/api/orchestration/committee`) that runs several agents on one question
  and synthesizes their views.
- Server-side tool execution inside that loop: shell, file read/write/edit,
  precision code search, and web search/research/fetch (backed by SearXNG and a
  CDP browser).

**Operability and access control**

- Cost/latency telemetry, request logs, truncation events, analytics, and
  operator dashboards over a 6-axis model catalog (coding/reasoning/planning/
  tool-use/instruction/design scores, plus per-token/image/second pricing).
- Cost accounting that separates metered spend from subscription plans
  (Claude/Codex plan cost, plan limits, Codex credits, and API-equivalent
  value), plus `POST /api/analytics/costs/ingest` so external clients can
  record model calls they paid for outside Agent Hub. Ingest is idempotent per
  key and does not count against the project's completion budget.
- Context governance: one selector and renderer decide what prompts and memory
  reach Claude Code, Codex, Pi, Google's Antigravity CLI, MCP clients and
  internal agents. Operators can preview the exact delivered context, save
  edits with revision checks, and undo a saved batch. See
  [context governance](architecture/context-governance.md).
- Client registration and access control, per-project permissions, per-project
  daily/monthly cost budgets, per-agent hourly request and daily token limits,
  encrypted credential storage (Fernet at rest), and OAuth (Codex/PKCE).
- Optional web research, browser, and voice
  (faster-whisper STT → completion → edge-tts) integrations.
- A Python SDK (`agent-hub-client`) with sync + async clients for completions,
  SSE streaming, stateful sessions, image generation, and memory operations.

Under the hood: 33 API routers, multi-provider image/completion adapters, and
13 Hatchet background workflows (agentic completions, background agent wakes,
session summaries and reaping, memory governance and cleanup, model catalog
enrichment, data retention, and more).

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

Start from [`.env.example`](../.env.example). Minimum native values:

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
└── docs/               Guides, architecture notes, and evaluations
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

The animation in the README shows the dashboard before the October 2026
redesign. To capture current screenshots, start a local instance with an empty
database and run (images are written to `docs/screenshots/` by default):

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
browser, and voice integrations require their corresponding
configuration and should fail clearly when absent.

## License

Apache License 2.0. See [LICENSE](../LICENSE) and [NOTICE](../NOTICE).
Security reporting is described in [SECURITY.md](../SECURITY.md).
