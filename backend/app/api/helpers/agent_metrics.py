"""Agent metrics computation helper functions."""

from collections.abc import Iterable
from datetime import UTC, datetime, timedelta

from sqlalchemy import DateTime, case, func, literal, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas.agent_schemas import AgentMetrics
from app.models import CostLog, RequestLog, Session

_HOURS = 24


async def _fetch_aggregate_metrics(
    db: AsyncSession, agent_slugs: list[str], cutoff: datetime
) -> dict[str, tuple[int, float, int, int]]:
    """Fetch 24h aggregate request metrics per agent.

    Returns:
        Map of slug to (total_requests, avg_latency_ms, success_count, tokens_24h)
    """
    agg_query = (
        select(
            RequestLog.agent_slug,
            func.count(RequestLog.id).label("total_requests"),
            func.avg(RequestLog.latency_ms).label("avg_latency"),
            func.sum(case((RequestLog.status_code < 400, 1), else_=0)).label("success_count"),
            func.coalesce(func.sum(RequestLog.tokens_in), 0).label("tokens_in"),
            func.coalesce(func.sum(RequestLog.tokens_out), 0).label("tokens_out"),
        )
        .where(
            RequestLog.agent_slug.in_(agent_slugs),
            RequestLog.created_at >= cutoff,
        )
        .group_by(RequestLog.agent_slug)
    )

    result = await db.execute(agg_query)
    return {
        row.agent_slug: (
            row.total_requests or 0,
            float(row.avg_latency or 0),
            row.success_count or 0,
            (row.tokens_in or 0) + (row.tokens_out or 0),
        )
        for row in result
    }


async def _fetch_cost_24h(
    db: AsyncSession, agent_slugs: list[str], cutoff: datetime
) -> dict[str, float]:
    """Fetch total cost in USD per agent over the last 24h."""
    cost_query = (
        select(Session.agent_slug, func.coalesce(func.sum(CostLog.cost_usd), 0.0))
        .join(Session, Session.id == CostLog.session_id)
        .where(
            Session.agent_slug.in_(agent_slugs),
            CostLog.created_at >= cutoff,
        )
        .group_by(Session.agent_slug)
    )
    cost_result = await db.execute(cost_query)
    return {slug: float(cost or 0.0) for slug, cost in cost_result}


async def _fetch_hourly_trends(
    db: AsyncSession, agent_slugs: list[str], now: datetime
) -> dict[str, tuple[list[float], list[float]]]:
    """Fetch hourly latency and success-rate sparkline data (24 buckets, oldest first) per agent.

    Bucket ``h`` hours back covers [now - (h+1)h, now - h h), so a row exactly on a
    boundary belongs to the newer hour: ceil(age / 1h) - 1.
    """
    now_param = literal(now, DateTime(timezone=True))
    hours_back = (func.ceil(func.extract("epoch", now_param - RequestLog.created_at) / 3600) - 1).label("hours_back")
    hourly_query = (
        select(
            RequestLog.agent_slug,
            hours_back,
            func.avg(RequestLog.latency_ms).label("avg_latency"),
            func.count(RequestLog.id).label("total"),
            func.sum(case((RequestLog.status_code < 400, 1), else_=0)).label("success"),
        )
        .where(
            RequestLog.agent_slug.in_(agent_slugs),
            RequestLog.created_at >= now - timedelta(hours=_HOURS),
            RequestLog.created_at < now,
        )
        .group_by(RequestLog.agent_slug, hours_back)
    )

    trends = {slug: ([0.0] * _HOURS, [0.0] * _HOURS) for slug in agent_slugs}
    for row in await db.execute(hourly_query):
        index = _HOURS - 1 - int(row.hours_back)
        latency_trend, success_trend = trends[row.agent_slug]
        latency_trend[index] = float(row.avg_latency or 0)
        hourly_total = row.total or 0
        hourly_success = row.success or 0
        success_trend[index] = (hourly_success / hourly_total * 100) if hourly_total > 0 else 0.0
    return trends


async def compute_agents_metrics(db: AsyncSession, agent_slugs: Iterable[str]) -> dict[str, AgentMetrics]:
    """Compute real metrics for agents from request_logs, three queries for any number of agents.

    Returns:
        Map of slug to AgentMetrics with 24h aggregated data and hourly trends
    """
    slugs = list(dict.fromkeys(agent_slugs))
    if not slugs:
        return {}
    now = datetime.now(UTC)
    cutoff_24h = now - timedelta(hours=_HOURS)

    aggregates = await _fetch_aggregate_metrics(db, slugs, cutoff_24h)
    costs = await _fetch_cost_24h(db, slugs, cutoff_24h)
    trends = await _fetch_hourly_trends(db, slugs, now)

    metrics: dict[str, AgentMetrics] = {}
    for slug in slugs:
        total_requests, avg_latency, success_count, tokens_24h = aggregates.get(slug, (0, 0.0, 0, 0))
        latency_trend, success_trend = trends[slug]
        metrics[slug] = AgentMetrics(
            slug=slug,
            requests_24h=total_requests,
            avg_latency_ms=avg_latency,
            success_rate=(success_count / total_requests * 100) if total_requests > 0 else 0.0,
            tokens_24h=tokens_24h,
            cost_24h_usd=costs.get(slug, 0.0),
            latency_trend=latency_trend,
            success_trend=success_trend,
        )
    return metrics


async def compute_agent_metrics(db: AsyncSession, agent_slug: str) -> AgentMetrics:
    """Compute real metrics for one agent from request_logs."""
    return (await compute_agents_metrics(db, [agent_slug]))[agent_slug]
