# Agent Hub Web — multi-stage Docker build with standalone output
# Image: ghcr.io/summitflow-solutions/agent-hub-web
# Port: 3003
# Requires: workspace packages (chat-ui, passport-client) pre-packed as tarballs

# ── Stage 1: Build ───────────────────────────────────────────────
FROM node:20-slim AS builder

RUN corepack enable && corepack prepare pnpm@latest --activate

WORKDIR /app

# Copy all frontend source
COPY frontend/ ./

# Copy workspace package tarballs (built by pack-workspace-packages.sh)
COPY docker/workspace-packages/*.tgz /tmp/workspace-packages/

# Replace workspace:* references with file: paths to tarballs
RUN sed -i 's|"@agent-hub/chat-ui": "workspace:\*"|"@agent-hub/chat-ui": "file:/tmp/workspace-packages/agent-hub-chat-ui-0.1.0.tgz"|g' package.json \
    && sed -i 's|"@agent-hub/passport-client": "workspace:\*"|"@agent-hub/passport-client": "file:/tmp/workspace-packages/agent-hub-passport-client-0.1.0.tgz"|g' package.json

# Override transitive passport-client dep (chat-ui depends on it, not on npm)
RUN node -e "\
  const fs = require('fs');\
  const pkg = JSON.parse(fs.readFileSync('package.json'));\
  pkg.pnpm = pkg.pnpm || {};\
  pkg.pnpm.overrides = { ...pkg.pnpm?.overrides, '@agent-hub/passport-client': 'file:/tmp/workspace-packages/agent-hub-passport-client-0.1.0.tgz' };\
  fs.writeFileSync('package.json', JSON.stringify(pkg, null, 2));"

# Install dependencies
RUN pnpm install --no-frozen-lockfile

# Build with standalone output
ENV NEXT_TELEMETRY_DISABLED=1
# API URLs for Next.js rewrites (baked at build time)
ARG AGENT_HUB_API_URL=http://agent-hub-api:8003
ARG SUMMITFLOW_API_URL=http://summitflow-api:8001
ENV AGENT_HUB_API_URL=${AGENT_HUB_API_URL}
ENV SUMMITFLOW_API_URL=${SUMMITFLOW_API_URL}
RUN pnpm build

# ── Stage 2: Runner ──────────────────────────────────────────────
FROM node:20-slim

WORKDIR /app

ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1
ENV PORT=3003
ENV HOSTNAME=0.0.0.0

# Copy standalone output
COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static
COPY --from=builder /app/public ./public

EXPOSE 3003

CMD ["node", "server.js"]
