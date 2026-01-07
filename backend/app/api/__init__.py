"""API routers for agent-hub."""

from fastapi import APIRouter

from app.api.api_keys import router as api_keys_router
from app.api.complete import router as complete_router
from app.api.credentials import router as credentials_router
from app.api.health import router as health_router
from app.api.openai_compat import router as openai_compat_router
from app.api.sessions import router as sessions_router
from app.api.stream import router as stream_router

router = APIRouter()
router.include_router(health_router)  # No prefix - /health, /status, /metrics
router.include_router(complete_router, tags=["completions"])
router.include_router(credentials_router, tags=["credentials"])
router.include_router(sessions_router, tags=["sessions"])
router.include_router(stream_router, tags=["streaming"])
router.include_router(api_keys_router)  # Has its own tags
router.include_router(openai_compat_router)  # Has its own tags

__all__ = ["router"]
