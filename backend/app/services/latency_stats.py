"""Per-model latency statistics from request_logs."""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.telemetry import RequestLog

logger = logging.getLogger(__name__)


async def get_model_latency_stats(
    db: AsyncSession,
    days: int = 7,
    min_samples: int = 10,
) -> list[dict[str, Any]]:
    """Query per-model latency percentiles from request_logs.

    Returns:
        List of dicts with model, sample_count, p50_ms, p95_ms, p99_ms.
    """
    from datetime import UTC, datetime, timedelta

    cutoff = datetime.now(UTC) - timedelta(days=days)

    # Subquery to get models with enough samples
    model_counts = (
        select(
            RequestLog.model.label("model"),
            func.count(RequestLog.id).label("sample_count"),
        )
        .where(
            RequestLog.created_at >= cutoff,
            RequestLog.latency_ms.isnot(None),
            RequestLog.model.isnot(None),
            RequestLog.status_code < 400,
        )
        .group_by(RequestLog.model)
        .having(func.count(RequestLog.id) >= min_samples)
        .subquery()
    )

    # Main query with percentiles
    query = select(
        model_counts.c.model,
        model_counts.c.sample_count,
    ).order_by(model_counts.c.sample_count.desc())

    result = await db.execute(query)
    rows = result.all()

    stats: list[dict[str, Any]] = []
    for row in rows:
        # Get percentiles per model (PostgreSQL specific)
        perc_query = select(
            func.percentile_cont(0.50).within_group(RequestLog.latency_ms).label("p50"),
            func.percentile_cont(0.95).within_group(RequestLog.latency_ms).label("p95"),
            func.percentile_cont(0.99).within_group(RequestLog.latency_ms).label("p99"),
        ).where(
            RequestLog.created_at >= cutoff,
            RequestLog.latency_ms.isnot(None),
            RequestLog.model == row.model,
            RequestLog.status_code < 400,
        )
        perc_result = await db.execute(perc_query)
        perc_row = perc_result.one()

        stats.append({
            "model": row.model,
            "sample_count": row.sample_count,
            "p50_ms": round(float(perc_row.p50 or 0), 1),
            "p95_ms": round(float(perc_row.p95 or 0), 1),
            "p99_ms": round(float(perc_row.p99 or 0), 1),
        })

    return stats
