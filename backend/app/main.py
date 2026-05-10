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
from app.services.agent_bootstrap_service import bootstrap_default_agents
from app.services.agent_model_reconciliation_service import (
    reconcile_agent_models_to_available_providers,
)
from app.services.credential_manager import get_credential_manager
from app.services.env_credential_service import load_env_credentials_into_cache
from app.services.events import stop_all_stream_bridges
from app.services.first_party_client_service import reconcile_first_party_clients
from app.services.memory.scope_normalization import normalize_legacy_scope_rows
from app.services.memory.usage_tracker import shutdown_usage_tracker, start_usage_tracker
from app.services.model_catalog_service import refresh_runtime_model_catalog
from app.services.project_permission_service import reconcile_registered_project_access
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

    credential_manager = get_credential_manager()
    loaded = await credential_manager.load_with_retry(async_session)
    logger.info("Loaded %d credentials at startup", loaded)

    env_credentials = load_env_credentials_into_cache()
    if env_credentials:
        logger.warning(
            "Loaded %d env-backed credential override(s): %s",
            len(env_credentials),
            ", ".join(env_credentials),
        )
    else:
        logger.info("No env-backed credential overrides configured")

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

    try:
        async with async_session() as db:
            seeded_agents = await bootstrap_default_agents(db)
        if seeded_agents:
            logger.warning("Seeded %d default agent(s) for a fresh database", seeded_agents)
        else:
            logger.info("Default agents already present")
    except Exception as e:
        logger.warning("Failed default agent bootstrap at startup: %s", e)

    try:
        async with async_session() as db:
            seeded_models = await refresh_runtime_model_catalog(db)
        if seeded_models:
            logger.warning("Seeded %d model catalog row(s)/alias(es) into DB", seeded_models)
        else:
            logger.info("Model catalog loaded from DB")
    except Exception as e:
        logger.warning("Failed model catalog DB load at startup: %s", e)

    try:
        async with async_session() as db:
            changed_routing_rows = await reconcile_agent_models_to_available_providers(db)
        if changed_routing_rows:
            logger.warning(
                "Seeded/refreshed adaptive routing metadata: %s",
                ", ".join(changed_routing_rows),
            )
        else:
            logger.info("Adaptive routing metadata already aligned")
    except Exception as e:
        logger.warning("Failed adaptive routing reconciliation at startup: %s", e)

    try:
        async with async_session() as db:
            changed_client_ids = await reconcile_first_party_clients(db)
        if changed_client_ids:
            logger.warning(
                "Reconciled %d first-party client registration(s): %s",
                len(changed_client_ids),
                ", ".join(changed_client_ids),
            )
        else:
            logger.info("First-party client registrations already aligned")
    except Exception as e:
        logger.warning("Failed first-party client reconciliation at startup: %s", e)

    try:
        async with async_session() as db:
            changed_client_ids = await reconcile_registered_project_access(db)
        if changed_client_ids:
            logger.warning(
                "Reconciled registered project access for %d SummitFlow-owned client(s): %s",
                len(changed_client_ids),
                ", ".join(changed_client_ids),
            )
        else:
            logger.info("Registered project access already aligned")
    except Exception as e:
        logger.warning("Failed registered project access reconciliation at startup: %s", e)

    try:
        from app.services.compactness_policy import load_policy_from_db
        async with async_session() as db:
            policy = await load_policy_from_db(db)
        logger.info("Loaded compactness policy: memory<=%d chars, sentence<=%d words",
                    policy.memory_max_chars, policy.max_sentence_words)
    except Exception as e:
        logger.warning("Failed to load compactness policy at startup: %s", e)

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
