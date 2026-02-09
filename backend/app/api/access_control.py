"""Access Control API endpoints for client management and request logging.

Replaces the old kill switch admin endpoints with cryptographic client auth.

This module serves as the main router orchestration layer, delegating to:
- access_control_clients: Client CRUD operations
- access_control_stats: Statistics and dashboard data
- access_control_logs: Request logging endpoints
- access_control_metrics: Aggregated metrics and analytics
"""

from fastapi import APIRouter

from app.api.access_control_clients import router as clients_router
from app.api.access_control_logs import router as logs_router
from app.api.access_control_metrics import router as metrics_router
from app.api.access_control_stats import router as stats_router

router = APIRouter(prefix="/access-control", tags=["access-control"])

# Include all sub-routers
router.include_router(clients_router)
router.include_router(stats_router)
router.include_router(logs_router)
router.include_router(metrics_router)
