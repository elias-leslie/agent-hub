# Agent Hub API — multi-stage Docker build
# Image: ghcr.io/summitflow-solutions/agent-hub-api
# Port: 8003
# Worker: same image with CMD ["python", "-m", "app.worker"]

# ── Stage 1: Builder ─────────────────────────────────────────────
FROM python:3.13-slim-bookworm AS builder

# Install uv for fast dependency resolution
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Install build dependencies for native extensions (pgvector, etc.)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy dependency files
COPY backend/pyproject.toml backend/uv.lock ./

# Copy pre-built agent-hub-client wheel
COPY docker/workspace-packages/*.whl /tmp/wheels/

# Install deps: export requirements, swap local path dep with wheel, install
RUN uv export --frozen --no-dev --no-editable --format requirements-txt \
      --no-header > requirements.txt && \
    sed -i '/^\.$/d; /agent-hub-client$/d; /^\.\.\//d' requirements.txt && \
    uv venv .venv && \
    uv pip install --python .venv/bin/python \
      -r requirements.txt /tmp/wheels/agent_hub_client-*.whl

# Copy application source
COPY backend/app ./app
COPY backend/alembic.ini ./
COPY backend/alembic ./alembic

# ── Stage 2: Runtime ─────────────────────────────────────────────
FROM python:3.13-slim-bookworm

# Install curl for healthchecks
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy virtual environment and application from builder
COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /app/app ./app
COPY --from=builder /app/alembic.ini ./
COPY --from=builder /app/alembic ./alembic

# Ensure venv binaries are on PATH
ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONUNBUFFERED=1

# Create non-root user for runtime
RUN useradd -m -s /bin/bash appuser \
    && chown -R appuser:appuser /app

USER appuser

EXPOSE 8003
ENV PORT=8003

# Default: run API server. Override CMD for worker.
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8003}"]
