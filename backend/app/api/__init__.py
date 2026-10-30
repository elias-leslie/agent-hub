"""API routers for agent-hub."""

from fastapi import APIRouter

from app.api.access_control import router as access_control_router
from app.api.admin import router as admin_router
from app.api.agents import router as agents_router
from app.api.analytics import router as analytics_router
from app.api.api_keys import router as api_keys_router
from app.api.auth import router as auth_router
from app.api.automations import router as automations_router
from app.api.complete import router as complete_router
from app.api.cost_ingest import router as cost_ingest_router
from app.api.credentials import router as credentials_router
from app.api.dashboard_stats import router as dashboard_stats_router
from app.api.db import router as db_router

# Endpoints from app.api.endpoints
from app.api.endpoints.voice import router as voice_router
from app.api.events import router as events_router
from app.api.health import router as health_router
from app.api.image import router as image_router
from app.api.lab_credentials import router as lab_credentials_router
from app.api.memory import router as memory_router
from app.api.models import router as models_router
from app.api.narration import router as narration_router
from app.api.oauth import router as oauth_router
from app.api.orchestration import router as orchestration_router
from app.api.ownership import router as ownership_router
from app.api.preferences import router as preferences_router
from app.api.project_agent_context import router as project_agent_context_router
from app.api.project_permissions import router as project_permissions_router
from app.api.prompts import router as prompts_router
from app.api.providers import router as providers_router
from app.api.remote_hosts import host_router as host_credentials_router
from app.api.remote_hosts import owner_router as remote_hosts_router
from app.api.runtime_context import router as runtime_context_router
from app.api.session_close_settings import router as session_close_settings_router
from app.api.session_ingestion import router as session_ingestion_router
from app.api.session_stream import router as session_stream_router
from app.api.sessions import router as sessions_router
from app.api.subscription_accounting import router as subscription_accounting_router
from app.api.tasks import router as tasks_router
from app.api.workflow_runs import router as workflow_runs_router

router = APIRouter()
router.include_router(health_router)  # No prefix - /health, /status, /metrics
router.include_router(analytics_router)  # Has its own prefix /analytics
router.include_router(subscription_accounting_router)  # /analytics/costs/accounting, /analytics/subscriptions/*
router.include_router(cost_ingest_router)  # POST /analytics/costs/ingest (external metered spend)
router.include_router(dashboard_stats_router)  # Has its own prefix /dashboard
router.include_router(access_control_router)  # Has its own prefix /access-control and tags
router.include_router(admin_router)  # Has its own prefix /admin and tags
router.include_router(auth_router)  # /auth/me for the dashboard proxy
router.include_router(automations_router)
router.include_router(db_router)  # Has its own prefix /admin/db and tags
router.include_router(complete_router, tags=["completions"])
router.include_router(credentials_router, tags=["credentials"])
router.include_router(lab_credentials_router, tags=["lab-credentials"])  # Owner-only agent logins
router.include_router(remote_hosts_router, tags=["remote-hosts"])  # Owner-only hosts and tool credential map
router.include_router(host_credentials_router, tags=["remote-hosts"])  # Host-token credential fetch/push
router.include_router(session_close_settings_router)  # before /sessions/{id}
router.include_router(sessions_router, tags=["sessions"])
router.include_router(session_stream_router, tags=["sessions"])
router.include_router(events_router, tags=["events"])
router.include_router(api_keys_router)  # Has its own tags
router.include_router(image_router, tags=["image"])
router.include_router(orchestration_router)  # Has its own prefix /orchestration and tags
router.include_router(memory_router)  # Has its own prefix /memory and tags
router.include_router(agents_router)  # Has its own prefix /agents and tags
router.include_router(models_router, tags=["models"])
router.include_router(narration_router)  # Has its own prefix /narration and tags
router.include_router(preferences_router, tags=["preferences"])
router.include_router(prompts_router)  # Has its own prefix /prompts and tags
router.include_router(voice_router, prefix="/voice", tags=["voice"])
router.include_router(oauth_router)  # Has its own prefix /oauth and tags
router.include_router(ownership_router)
router.include_router(providers_router)  # Has its own prefix /providers and tags
router.include_router(project_permissions_router)  # Has its own prefix /projects and tags
router.include_router(project_agent_context_router)  # GET /projects/{id}/agent-context (read-only)
router.include_router(runtime_context_router)
router.include_router(session_ingestion_router)
router.include_router(tasks_router)
router.include_router(workflow_runs_router)  # Has its own prefix /workflow-runs

__all__ = ["router"]
