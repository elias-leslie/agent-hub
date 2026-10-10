"""Orchestration API routes.

Only the committee roundtable remains here; it backs the agent page's
Committee tab validation run. General multi-agent execution goes through
/api/complete agentic mode.
"""

from typing import Any

from fastapi import APIRouter

from app.api.endpoints.committee import router as committee_router

router = APIRouter(prefix="/orchestration", tags=["orchestration"])


@router.get("/health")
async def orchestration_health() -> dict[str, Any]:
    """Check orchestration services health."""
    return {
        "status": "healthy",
        "services": {
            "committee_roundtable": True,
        },
    }


router.include_router(committee_router)
