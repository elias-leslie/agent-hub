# Agent Hub Web — multi-stage Docker build with standalone output
# Image: ghcr.io/elias-leslie/agent-hub-web
# Port: 3003

# ── Stage 0: Dev Runtime ─────────────────────────────────────────
FROM node:20-slim AS dev

RUN corepack enable && corepack prepare pnpm@10.28.0 --activate

WORKDIR /workspace

COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
COPY packages/ ./packages/
COPY frontend/ ./frontend/

RUN CI=true pnpm install --frozen-lockfile

WORKDIR /workspace/frontend

ENV NODE_ENV=development
ENV NEXT_TELEMETRY_DISABLED=1
ENV PORT=3003
ENV HOSTNAME=0.0.0.0

CMD ["pnpm", "dev", "--hostname", "0.0.0.0", "--port", "3003"]

# ── Stage 1: Build ───────────────────────────────────────────────
FROM node:20-slim AS builder

RUN corepack enable && corepack prepare pnpm@10.28.0 --activate

WORKDIR /workspace

COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
COPY packages/ ./packages/
COPY frontend/ ./frontend/

RUN CI=true pnpm install --frozen-lockfile

# Build with standalone output, then prune pnpm store
ENV NEXT_TELEMETRY_DISABLED=1
ARG AGENT_HUB_API_URL=http://agent-hub-api:8003
ARG SUMMITFLOW_API_URL=http://summitflow-api:8001
ARG AGENT_HUB_DASHBOARD_CLIENT_ID=
ENV AGENT_HUB_API_URL=${AGENT_HUB_API_URL}
ENV SUMMITFLOW_API_URL=${SUMMITFLOW_API_URL}
ENV AGENT_HUB_DASHBOARD_CLIENT_ID=${AGENT_HUB_DASHBOARD_CLIENT_ID}
ENV NEXT_PUBLIC_AGENT_HUB_DASHBOARD_CLIENT_ID=${AGENT_HUB_DASHBOARD_CLIENT_ID}
RUN pnpm --filter frontend build && pnpm store prune

# ── Stage 2: Runner ──────────────────────────────────────────────
FROM node:20-slim

RUN useradd -m -s /bin/bash appuser

WORKDIR /app

ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1
ENV PORT=3003
ENV HOSTNAME=0.0.0.0

COPY --chown=appuser:appuser --from=builder /workspace/frontend/.next/standalone ./
COPY --chown=appuser:appuser --from=builder /workspace/frontend/.next/static ./frontend/.next/static
COPY --chown=appuser:appuser --from=builder /workspace/frontend/public ./frontend/public

USER appuser

EXPOSE 3003

CMD ["node", "frontend/server.js"]
