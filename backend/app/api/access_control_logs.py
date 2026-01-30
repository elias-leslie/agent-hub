"""Request log endpoints for Access Control API."""

from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.access_control_schemas import RequestLogEntry, RequestLogResponse
from app.db import get_db
from app.models import Client, RequestLog

router = APIRouter()


@router.get("/request-log", response_model=RequestLogResponse)
async def get_request_log(
    db: Annotated[AsyncSession, Depends(get_db)],
    client_id: str | None = Query(default=None, description="Filter by client ID"),
    status_code: int | None = Query(default=None, description="Filter by status code"),
    rejected_only: bool = Query(default=False, description="Show only rejected requests"),
    tool_type: str | None = Query(default=None, description="Filter by tool type (api/cli/sdk)"),
    agent_slug: str | None = Query(default=None, description="Filter by agent slug"),
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    days: int = Query(default=30, ge=1, le=30, description="Days of history (max 30)"),
) -> RequestLogResponse:
    """Get request log with filtering. Automatically respects 30-day retention."""
    # Calculate retention cutoff
    cutoff = datetime.now(UTC) - timedelta(days=days)

    query = select(RequestLog).where(RequestLog.created_at >= cutoff)

    if client_id:
        query = query.where(RequestLog.client_id == client_id)
    if status_code:
        query = query.where(RequestLog.status_code == status_code)
    if rejected_only:
        query = query.where(RequestLog.rejection_reason.isnot(None))
    if tool_type:
        query = query.where(RequestLog.tool_type == tool_type)
    if agent_slug:
        query = query.where(RequestLog.agent_slug.ilike(f"%{agent_slug}%"))

    # Get total count for pagination
    count_query = select(func.count()).select_from(query.subquery())
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    # Apply ordering and pagination
    query = query.order_by(RequestLog.created_at.desc()).offset(offset).limit(limit)
    result = await db.execute(query)
    logs = result.scalars().all()

    # Get client display names
    client_names: dict[str, str] = {}
    client_ids = {log.client_id for log in logs if log.client_id}
    if client_ids:
        clients_result = await db.execute(select(Client).where(Client.id.in_(client_ids)))
        for client in clients_result.scalars():
            client_names[client.id] = client.display_name

    return RequestLogResponse(
        requests=[
            RequestLogEntry(
                id=log.id,
                client_id=log.client_id,
                client_display_name=client_names.get(log.client_id) if log.client_id else None,
                request_source=log.request_source,
                endpoint=log.endpoint,
                method=log.method,
                status_code=log.status_code,
                rejection_reason=log.rejection_reason,
                tokens_in=log.tokens_in,
                tokens_out=log.tokens_out,
                latency_ms=log.latency_ms,
                model=log.model,
                agent_slug=log.agent_slug,
                tool_type=log.tool_type,
                tool_name=log.tool_name,
                source_path=log.source_path,
                created_at=log.created_at,
            )
            for log in logs
        ],
        total=total,
    )
