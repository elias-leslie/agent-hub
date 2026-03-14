"""
agent-hub API Server
"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import router
from app.config import settings
from app.db import async_session
from app.exception_handlers import setup_exception_handlers
from app.middleware.access_control import AccessControlMiddleware
from app.services.credential_manager import get_credential_manager
from app.services.events import stop_all_stream_bridges
from app.services.memory.scope_normalization import normalize_legacy_scope_rows
from app.services.memory.usage_tracker import shutdown_usage_tracker, start_usage_tracker
from app.services.telemetry import init_telemetry

# Configure logging for application modules (must be after imports)
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


async def _startup() -> None:
    """Run all startup tasks."""
    logger.info("Starting agent-hub on port %d", settings.port)

    init_telemetry()
    logger.info("OpenTelemetry initialized")

    try:
        async with async_session() as db:
            credential_manager = get_credential_manager()
            loaded = await credential_manager.load(db)
            logger.info("Loaded %d credentials at startup", loaded)
    except Exception as e:
        logger.warning("Failed to load credentials at startup: %s", e)

    await start_usage_tracker()
    logger.info("Usage tracker started")

    try:
        from app.constants.projects import refresh_project_ids_cache
        project_ids = await refresh_project_ids_cache()
        logger.info("Loaded %d valid project IDs", len(project_ids))
    except Exception as e:
        logger.warning("Failed to load project IDs at startup: %s", e)

    try:
        normalized = await normalize_legacy_scope_rows()
        updated_rows = sum(normalized.values())
        if updated_rows:
            logger.warning("Normalized %d legacy memory scope row(s) at startup: %s", updated_rows, normalized)
        else:
            logger.info("Memory scope integrity check passed")
    except Exception as e:
        logger.warning("Failed memory scope normalization at startup: %s", e)

    from app.services.health_prober import init_health_prober
    prober = init_health_prober()
    logger.info("Provider health tracker initialized for %d providers (passive mode)", len(prober._providers))


async def _shutdown() -> None:
    """Run all shutdown tasks."""
    from app.services.health_prober import shutdown_health_prober

    await stop_all_stream_bridges()
    logger.info("Hatchet stream bridges stopped")
    await shutdown_health_prober()
    logger.info("Health prober stopped")
    await shutdown_usage_tracker()
    logger.info("Usage tracker stopped")
    logger.info("Shutting down agent-hub")


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Application lifespan manager."""
    await _startup()
    yield
    await _shutdown()


app = FastAPI(
    title="agent-hub",
    description="Unified agentic AI service for Claude/Gemini workloads",
    version="0.1.0",
    lifespan=lifespan,
)


# --- Global Exception Handlers ---
setup_exception_handlers(app)


# --- CORS configuration ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Access control middleware for mandatory client authentication
app.add_middleware(AccessControlMiddleware)


@app.get("/")
async def root() -> dict[str, str]:
    """Root endpoint."""
    return {"message": "Welcome to agent-hub", "docs": "/docs"}


@app.get("/health")
async def health_check() -> dict[str, str]:
    """Basic liveness check at root level for k8s probes."""
    return {"status": "healthy", "service": "agent-hub"}


# Include routers
app.include_router(router, prefix="/api")
