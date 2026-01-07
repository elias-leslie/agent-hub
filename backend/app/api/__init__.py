"""API routers for agent-hub."""

from fastapi import APIRouter

from app.api.complete import router as complete_router
from app.api.credentials import router as credentials_router
from app.api.sessions import router as sessions_router
from app.api.stream import router as stream_router

router = APIRouter()
router.include_router(complete_router, tags=["completions"])
router.include_router(credentials_router, tags=["credentials"])
router.include_router(sessions_router, tags=["sessions"])
router.include_router(stream_router, tags=["streaming"])

__all__ = ["router"]
