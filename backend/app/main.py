"""
agent-hub API Server
"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from app.api import router
from app.api.endpoints import voice
from app.config import settings
from app.db import async_session
from app.middleware.access_control import AccessControlMiddleware
from app.services.credential_manager import get_credential_manager
from app.services.events import stop_all_stream_bridges
from app.services.memory.usage_tracker import shutdown_usage_tracker, start_usage_tracker
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
        async with async_session() as db:
            credential_manager = get_credential_manager()
            loaded = await credential_manager.load(db)
            logger.info(f"Loaded {loaded} credentials at startup")
    except Exception as e:
        logger.warning(f"Failed to load credentials at startup: {e}")

    # Start background usage tracking flush task (30s interval)
    await start_usage_tracker()
    logger.info("Usage tracker started")

    yield
    # Shutdown
    await stop_all_stream_bridges()
    logger.info("Hatchet stream bridges stopped")
    await shutdown_usage_tracker()
    logger.info("Usage tracker stopped")
    print("Shutting down agent-hub")


app = FastAPI(
    title="agent-hub",
    description="Unified agentic AI service for Claude/Gemini workloads",
    version="0.1.0",
    lifespan=lifespan,
)


# --- Global Exception Handlers ---


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """Handle request validation errors with consistent JSON response."""
    errors = exc.errors()
    return JSONResponse(
        status_code=422,
        content={
            "error": "validation_error",
            "message": "Request validation failed",
            "details": [
                {
                    "loc": list(err.get("loc", [])),
                    "msg": err.get("msg", ""),
                    "type": err.get("type", ""),
                }
                for err in errors
            ],
        },
    )


@app.exception_handler(ValidationError)
async def pydantic_validation_exception_handler(
    request: Request, exc: ValidationError
) -> JSONResponse:
    """Handle Pydantic validation errors with consistent JSON response."""
    errors = exc.errors()
    return JSONResponse(
        status_code=422,
        content={
            "error": "validation_error",
            "message": "Data validation failed",
            "details": [
                {
                    "loc": list(err.get("loc", [])),
                    "msg": err.get("msg", ""),
                    "type": err.get("type", ""),
                }
                for err in errors
            ],
        },
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    """Handle HTTP exceptions with consistent JSON response."""
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": "http_error",
            "message": exc.detail,
            "status_code": exc.status_code,
        },
        headers=exc.headers,
    )


@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Handle unexpected exceptions with consistent JSON response."""
    logger.exception(f"Unhandled exception: {exc}")
    return JSONResponse(
        status_code=500,
        content={
            "error": "internal_server_error",
            "message": "An unexpected error occurred",
        },
    )


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
app.include_router(voice.router, prefix="/api/voice", tags=["voice"])
