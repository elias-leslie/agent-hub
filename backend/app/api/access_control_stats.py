"""Statistics endpoints for Access Control API."""

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.access_control_schemas import ClientStatsResponse
from app.db import get_db
from app.models import Client, RequestLog

router = APIRouter()


@router.get("/stats", response_model=ClientStatsResponse)
async def get_stats(
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ClientStatsResponse:
    """Get access control statistics for dashboard."""
    # Count clients by status
    total_result = await db.execute(select(func.count()).select_from(Client))
    total_clients = total_result.scalar() or 0

    active_result = await db.execute(
        select(func.count()).select_from(Client).where(Client.status == "active")
    )
    active_clients = active_result.scalar() or 0

    suspended_result = await db.execute(
        select(func.count()).select_from(Client).where(Client.status == "suspended")
    )
    suspended_clients = suspended_result.scalar() or 0

    blocked_result = await db.execute(
        select(func.count()).select_from(Client).where(Client.status == "blocked")
    )
    blocked_clients = blocked_result.scalar() or 0

    # Count requests today
    today_start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)

    total_requests_result = await db.execute(
        select(func.count()).select_from(RequestLog).where(RequestLog.created_at >= today_start)
    )
    total_requests_today = total_requests_result.scalar() or 0

    blocked_requests_result = await db.execute(
        select(func.count())
        .select_from(RequestLog)
        .where(
            RequestLog.created_at >= today_start,
            RequestLog.rejection_reason.isnot(None),
        )
    )
    blocked_requests_today = blocked_requests_result.scalar() or 0

    return ClientStatsResponse(
        total_clients=total_clients,
        active_clients=active_clients,
        suspended_clients=suspended_clients,
        blocked_clients=blocked_clients,
        blocked_requests_today=blocked_requests_today,
        total_requests_today=total_requests_today,
    )
