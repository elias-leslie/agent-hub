"""
agent-hub API Server
"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.db import get_db
from app.services.credential_manager import get_credential_manager
from app.services.telemetry import init_telemetry

# Configure logging for application modules (must be after imports)
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Application lifespan manager."""
    # Startup
    print(f"Starting agent-hub on port {settings.port}")

    # Initialize OpenTelemetry tracing
    init_telemetry()
    logger.info("OpenTelemetry initialized")

    # Load credentials from database into cache
    try:
        async for db in get_db():
            credential_manager = get_credential_manager()
            loaded = await credential_manager.load(db)
            logger.info(f"Loaded {loaded} credentials at startup")
            break
    except Exception as e:
        logger.warning(f"Failed to load credentials at startup: {e}")
        # Non-fatal - credentials can be loaded later or provided via env

    yield
    # Shutdown
    print("Shutting down agent-hub")


app = FastAPI(
    title="agent-hub",
    description="Unified agentic AI service for Claude/Gemini workloads",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Kill switch middleware for usage control
from app.middleware.kill_switch import KillSwitchMiddleware  # noqa: E402

app.add_middleware(KillSwitchMiddleware)


@app.get("/")
async def root() -> dict[str, str]:
    """Root endpoint."""
    return {"message": "Welcome to agent-hub", "docs": "/docs"}


@app.get("/health")
async def health_check() -> dict[str, str]:
    """Basic liveness check at root level for k8s probes."""
    return {"status": "healthy", "service": "agent-hub"}


# Import and include routers (must be after app is created to avoid circular imports)
from app.api import router  # noqa: E402

app.include_router(router, prefix="/api")

# Voice Router
from app.api.endpoints import voice  # noqa: E402

app.include_router(voice.router, prefix="/api/voice", tags=["voice"])
