"""API routers for agent-hub."""

from fastapi import APIRouter

from app.api.admin import router as admin_router
from app.api.analytics import router as analytics_router
from app.api.api_keys import router as api_keys_router
from app.api.complete import router as complete_router
from app.api.credentials import router as credentials_router
from app.api.events import router as events_router
from app.api.feedback import router as feedback_router
from app.api.health import router as health_router
from app.api.image import router as image_router
from app.api.memory import router as memory_router
from app.api.openai_compat import router as openai_compat_router
from app.api.orchestration import router as orchestration_router
from app.api.preferences import router as preferences_router
from app.api.sessions import router as sessions_router
from app.api.stream import router as stream_router
from app.api.webhooks import router as webhooks_router

router = APIRouter()
router.include_router(health_router)  # No prefix - /health, /status, /metrics
router.include_router(analytics_router)  # Has its own prefix /analytics
router.include_router(admin_router)  # Has its own prefix /admin and tags
router.include_router(complete_router, tags=["completions"])
router.include_router(credentials_router, tags=["credentials"])
router.include_router(sessions_router, tags=["sessions"])
router.include_router(stream_router, tags=["streaming"])
router.include_router(events_router, tags=["events"])
router.include_router(webhooks_router)  # Has its own prefix /webhooks and tags
router.include_router(api_keys_router)  # Has its own tags
router.include_router(openai_compat_router)  # Has its own tags
router.include_router(feedback_router, tags=["feedback"])
router.include_router(preferences_router, tags=["preferences"])
router.include_router(image_router, tags=["image"])
router.include_router(orchestration_router)  # Has its own prefix /orchestration and tags
router.include_router(memory_router)  # Has its own prefix /memory and tags

__all__ = ["router"]
