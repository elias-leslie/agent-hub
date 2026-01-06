"""API routers for agent-hub."""

from fastapi import APIRouter

from app.api.complete import router as complete_router
from app.api.sessions import router as sessions_router

router = APIRouter()
router.include_router(complete_router, tags=["completions"])
router.include_router(sessions_router, tags=["sessions"])

__all__ = ["router"]
