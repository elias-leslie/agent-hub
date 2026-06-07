# Agent Hub API — multi-stage Docker build
# Image: ghcr.io/elias-leslie/agent-hub-api
# Port: 8003
# Worker: same image with CMD ["python", "-m", "app.worker"]

# ── Stage 1: Builder ─────────────────────────────────────────────
FROM python:3.13-slim-bookworm AS builder

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Build deps for native extensions (pgvector, cryptography, etc.)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy dependency files first (cache-friendly layer)
COPY backend/pyproject.toml backend/uv.lock ./

# Install deps and clean caches in same layer
RUN uv export --frozen --no-dev --no-editable --format requirements-txt \
      --no-header --no-hashes > requirements.txt && \
    sed -i '/^\.$/d' requirements.txt && \
    uv venv .venv && \
    uv pip install --python .venv/bin/python -r requirements.txt && \
    rm -rf /root/.cache/uv /root/.cache/pip requirements.txt

# Copy application source
COPY backend/app ./app
COPY backend/scripts ./scripts
COPY backend/alembic.ini ./
COPY backend/alembic ./alembic

# ── Stage 2: Runtime ─────────────────────────────────────────────
FROM python:3.13-slim-bookworm

RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user before COPY --chown
RUN useradd -m -s /bin/bash appuser

WORKDIR /app

COPY --chown=appuser:appuser --from=builder /app/.venv /app/.venv
COPY --chown=appuser:appuser --from=builder /app/app ./app
COPY --chown=appuser:appuser --from=builder /app/scripts ./scripts
COPY --chown=appuser:appuser --from=builder /app/alembic.ini ./
COPY --chown=appuser:appuser --from=builder /app/alembic ./alembic

ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONUNBUFFERED=1

USER appuser

EXPOSE 8003
ENV PORT=8003

CMD ["sh", "-c", "alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8003}"]
