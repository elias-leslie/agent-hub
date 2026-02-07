"""Memory API - Knowledge graph memory management."""

from __future__ import annotations

from fastapi import APIRouter

from .memory_agent_tools import router as agent_tools_router
from .memory_bulk_ops import router as bulk_ops_router
from .memory_dashboard import router as dashboard_router
from .memory_dependencies import get_memory_svc, get_scope_params, resolve_episode_uuid
from .memory_entities import router as entities_router
from .memory_episodes import router as episodes_router
from .memory_metrics import router as metrics_router
from .memory_observations import router as observations_router
from .memory_rating import router as rating_router
from .memory_settings import router as settings_router
from .memory_tags import router as tags_router
from .memory_triggers import router as triggers_router

# Create main router
router = APIRouter(prefix="/memory", tags=["memory"])

# Re-export dependencies for sub-routers
__all__ = ["get_memory_svc", "get_scope_params", "resolve_episode_uuid", "router"]

# Include sub-routers
router.include_router(settings_router)
router.include_router(agent_tools_router, tags=["agent-tools"])
router.include_router(rating_router, tags=["agent-tools"])
router.include_router(metrics_router, tags=["metrics"])
router.include_router(bulk_ops_router)
router.include_router(entities_router)
router.include_router(triggers_router)
router.include_router(observations_router)
router.include_router(dashboard_router)
router.include_router(episodes_router)
router.include_router(tags_router)
