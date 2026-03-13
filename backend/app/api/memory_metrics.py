"""Memory metrics endpoints for injection monitoring."""

import logging
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query

from app.services.memory.analytics_models import InjectionMetricsSummary
from app.services.memory.analytics_service import get_injection_metrics_summary

from .memory_lookback import parse_memory_lookback

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/metrics", response_model=InjectionMetricsSummary)
async def get_memory_metrics(
    days: Annotated[int, Query(ge=1, le=90, description="Days to look back")] = 7,
    lookback: Annotated[
        str | None,
        Query(description="Compact lookback window: 1h, 1d, 7d, 14d, 30d"),
    ] = None,
    period: Annotated[
        str,
        Query(description="Aggregation period: hour, day (default), week"),
    ] = "day",
    variant_filter: Annotated[
        str | None,
        Query(description="Filter by variant (BASELINE, ENHANCED, MINIMAL, AGGRESSIVE)"),
    ] = None,
    project_id_filter: Annotated[
        str | None,
        Query(description="Filter by project_id"),
    ] = None,
) -> InjectionMetricsSummary:
    """Return injection metrics for the requested time window."""
    try:
        lookback_delta, _ = parse_memory_lookback(lookback, fallback_days=days)
        return await get_injection_metrics_summary(
            lookback_delta,
            period=period,
            variant_filter=variant_filter,
            project_id_filter=project_id_filter,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        logger.exception("Failed to get injection metrics")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get metrics: {e}",
        ) from e
