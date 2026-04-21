"""Orchestration API routes - Multi-agent execution endpoints.

Provides HTTP endpoints for:
- Canonical clarify -> plan -> execute -> review -> QA workflow
- Subagent spawning
- Parallel execution
- Maker-checker verification

Note: Agent runner functionality has been consolidated into /api/complete
with agentic mode (max_turns > 1 or execute_tools=True). The generic
subagent/parallel/chain routes remain low-level plumbing; operators should
prefer /api/orchestration/workflow when they want an explicit stage-based flow.
"""

from typing import Any

from fastapi import APIRouter

# Import endpoint routers
from app.api.endpoints.chain import router as chain_router
from app.api.endpoints.committee import router as committee_router
from app.api.endpoints.maker_checker import router as maker_checker_router
from app.api.endpoints.parallel import router as parallel_router
from app.api.endpoints.subagent import router as subagent_router
from app.api.endpoints.workflow import router as workflow_router

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
            "chain_executor": True,
            "maker_checker": True,
            "committee_roundtable": True,
        },
    }


# ========== Include Sub-routers ==========

# Include all endpoint routers
router.include_router(workflow_router)
router.include_router(subagent_router)
router.include_router(parallel_router)
router.include_router(chain_router)
router.include_router(maker_checker_router)
router.include_router(committee_router)
