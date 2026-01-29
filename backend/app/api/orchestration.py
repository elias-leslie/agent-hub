"""Orchestration API routes - Multi-agent execution endpoints.

Provides HTTP endpoints for:
- Subagent spawning
- Parallel execution
- Maker-checker verification
- Agent runner (main chat functionality)
"""

from typing import Any

from fastapi import APIRouter

# Import endpoint routers
from app.api.endpoints.agent_runner import router as agent_runner_router
from app.api.endpoints.maker_checker import router as maker_checker_router
from app.api.endpoints.parallel import router as parallel_router
from app.api.endpoints.subagent import router as subagent_router

router = APIRouter(prefix="/orchestration", tags=["orchestration"])


# ========== Health Check ==========


@router.get("/health")
async def orchestration_health() -> dict[str, Any]:
    """Check orchestration services health."""
    return {
        "status": "healthy",
        "services": {
            "subagent_manager": True,
            "parallel_executor": True,
            "maker_checker": True,
            "agent_runner": True,
        },
    }


# ========== Include Sub-routers ==========

# Include all endpoint routers
router.include_router(subagent_router)
router.include_router(parallel_router)
router.include_router(maker_checker_router)
router.include_router(agent_runner_router)
