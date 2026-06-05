# Agent Hub Web — multi-stage Docker build with standalone output
# Image: ghcr.io/elias-leslie/agent-hub-web
# Port: 3003
# Requires: workspace packages (chat-ui, passport-client, notes-ui) pre-packed as tarballs

# ── Stage 0: Dev Runtime ─────────────────────────────────────────
FROM node:20-slim AS dev

RUN corepack enable && corepack prepare pnpm@10.28.0 --activate

WORKDIR /app

COPY frontend/ ./
COPY docker/workspace-packages/*.tgz /tmp/workspace-packages/

RUN sed -i 's|"@agent-hub/chat-ui": "workspace:\*"|"@agent-hub/chat-ui": "file:/tmp/workspace-packages/agent-hub-chat-ui-0.1.0.tgz"|g' package.json \
    && sed -i 's|"@agent-hub/passport-client": "workspace:\*"|"@agent-hub/passport-client": "file:/tmp/workspace-packages/agent-hub-passport-client-0.1.0.tgz"|g' package.json \
    && sed -i 's|"@summitflow/notes-ui": "workspace:\*"|"@summitflow/notes-ui": "file:/tmp/workspace-packages/summitflow-notes-ui-0.1.0.tgz"|g' package.json

RUN node -e "\
  const fs = require('fs');\
  const pkg = JSON.parse(fs.readFileSync('package.json'));\
  pkg.pnpm = pkg.pnpm || {};\
  pkg.pnpm.overrides = { ...pkg.pnpm?.overrides, '@agent-hub/passport-client': 'file:/tmp/workspace-packages/agent-hub-passport-client-0.1.0.tgz' };\
  fs.writeFileSync('package.json', JSON.stringify(pkg, null, 2));"

RUN CI=true pnpm install --no-frozen-lockfile

ENV NODE_ENV=development
ENV NEXT_TELEMETRY_DISABLED=1
ENV PORT=3003
ENV HOSTNAME=0.0.0.0

CMD ["pnpm", "dev", "--hostname", "0.0.0.0", "--port", "3003"]

# ── Stage 1: Build ───────────────────────────────────────────────
FROM node:20-slim AS builder

RUN corepack enable && corepack prepare pnpm@10.28.0 --activate

WORKDIR /app

# Copy all frontend source
COPY frontend/ ./

# Copy workspace package tarballs (built by pack-workspace-packages.sh)
COPY docker/workspace-packages/*.tgz /tmp/workspace-packages/

# Replace workspace:* references with file: paths to tarballs
RUN sed -i 's|"@agent-hub/chat-ui": "workspace:\*"|"@agent-hub/chat-ui": "file:/tmp/workspace-packages/agent-hub-chat-ui-0.1.0.tgz"|g' package.json \
    && sed -i 's|"@agent-hub/passport-client": "workspace:\*"|"@agent-hub/passport-client": "file:/tmp/workspace-packages/agent-hub-passport-client-0.1.0.tgz"|g' package.json \
    && sed -i 's|"@summitflow/notes-ui": "workspace:\*"|"@summitflow/notes-ui": "file:/tmp/workspace-packages/summitflow-notes-ui-0.1.0.tgz"|g' package.json

# Override transitive passport-client dep (chat-ui depends on it, not on npm)
RUN node -e "\
  const fs = require('fs');\
  const pkg = JSON.parse(fs.readFileSync('package.json'));\
  pkg.pnpm = pkg.pnpm || {};\
  pkg.pnpm.overrides = { ...pkg.pnpm?.overrides, '@agent-hub/passport-client': 'file:/tmp/workspace-packages/agent-hub-passport-client-0.1.0.tgz' };\
  fs.writeFileSync('package.json', JSON.stringify(pkg, null, 2));"

# Install dependencies and clean temp files in same layer
RUN CI=true pnpm install --no-frozen-lockfile && \
    rm -rf /tmp/workspace-packages

# Build with standalone output, then prune pnpm store
ENV NEXT_TELEMETRY_DISABLED=1
ARG AGENT_HUB_API_URL=http://agent-hub-api:8003
ARG SUMMITFLOW_API_URL=http://summitflow-api:8001
ARG AGENT_HUB_DASHBOARD_CLIENT_ID=
ENV AGENT_HUB_API_URL=${AGENT_HUB_API_URL}
ENV SUMMITFLOW_API_URL=${SUMMITFLOW_API_URL}
ENV AGENT_HUB_DASHBOARD_CLIENT_ID=${AGENT_HUB_DASHBOARD_CLIENT_ID}
ENV NEXT_PUBLIC_AGENT_HUB_DASHBOARD_CLIENT_ID=${AGENT_HUB_DASHBOARD_CLIENT_ID}
RUN pnpm build && pnpm store prune

# ── Stage 2: Runner ──────────────────────────────────────────────
FROM node:20-slim

RUN useradd -m -s /bin/bash appuser

WORKDIR /app

ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1
ENV PORT=3003
ENV HOSTNAME=0.0.0.0

COPY --chown=appuser:appuser --from=builder /app/.next/standalone ./
COPY --chown=appuser:appuser --from=builder /app/.next/static ./.next/static
COPY --chown=appuser:appuser --from=builder /app/public ./public

USER appuser

EXPOSE 3003

CMD ["node", "server.js"]
