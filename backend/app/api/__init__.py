"""API routers for agent-hub."""

from fastapi import APIRouter

from app.api.complete import router as complete_router

router = APIRouter()
router.include_router(complete_router, tags=["completions"])

__all__ = ["router"]
