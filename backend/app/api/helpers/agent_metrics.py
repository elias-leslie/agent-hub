"""Agent metrics computation helper functions."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas.agent_schemas import AgentMetrics
from app.models import RequestLog


async def compute_agent_metrics(db: AsyncSession, agent_slug: str) -> AgentMetrics:
    """Compute real metrics for an agent from request_logs.

    Args:
        db: Database session
        agent_slug: Agent slug to compute metrics for

    Returns:
        AgentMetrics with 24h aggregated data and hourly trends
    """
    now = datetime.now(UTC)
    cutoff_24h = now - timedelta(hours=24)

    # Aggregate metrics for last 24h
    agg_query = select(
        func.count(RequestLog.id).label("total_requests"),
        func.avg(RequestLog.latency_ms).label("avg_latency"),
        func.sum(case((RequestLog.status_code < 400, 1), else_=0)).label("success_count"),
        func.coalesce(func.sum(RequestLog.tokens_in), 0).label("tokens_in"),
        func.coalesce(func.sum(RequestLog.tokens_out), 0).label("tokens_out"),
    ).where(
        RequestLog.agent_slug == agent_slug,
        RequestLog.created_at >= cutoff_24h,
    )

    result = await db.execute(agg_query)
    row = result.one()

    total_requests = row.total_requests or 0
    avg_latency = float(row.avg_latency or 0)
    success_count = row.success_count or 0
    tokens_24h = (row.tokens_in or 0) + (row.tokens_out or 0)

    success_rate = (success_count / total_requests * 100) if total_requests > 0 else 100.0

    # Hourly sparkline data (24 buckets)
    latency_trend: list[float] = []
    success_trend: list[float] = []

    for hour_offset in range(23, -1, -1):
        hour_start = now - timedelta(hours=hour_offset + 1)
        hour_end = now - timedelta(hours=hour_offset)

        hourly_query = select(
            func.avg(RequestLog.latency_ms).label("avg_latency"),
            func.count(RequestLog.id).label("total"),
            func.sum(case((RequestLog.status_code < 400, 1), else_=0)).label("success"),
        ).where(
            RequestLog.agent_slug == agent_slug,
            RequestLog.created_at >= hour_start,
            RequestLog.created_at < hour_end,
        )

        hourly_result = await db.execute(hourly_query)
        hourly_row = hourly_result.one()

        latency_trend.append(float(hourly_row.avg_latency or 0))
        hourly_total = hourly_row.total or 0
        hourly_success = hourly_row.success or 0
        success_trend.append((hourly_success / hourly_total * 100) if hourly_total > 0 else 100.0)

    return AgentMetrics(
        slug=agent_slug,
        requests_24h=total_requests,
        avg_latency_ms=avg_latency,
        success_rate=success_rate,
        tokens_24h=tokens_24h,
        cost_24h_usd=0.0,  # TODO: Join with cost_logs if needed
        latency_trend=latency_trend,
        success_trend=success_trend,
    )
