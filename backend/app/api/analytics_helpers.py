"""Helper models, enums, and dispatch functions for analytics API endpoints."""

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.analytics_service import (
    CostAggregation,
    CostFilters,
    TruncationAggregation,
    TruncationFilters,
    aggregate_costs_by_agent,
    aggregate_costs_by_external_id,
    aggregate_costs_by_model,
    aggregate_costs_by_project,
    aggregate_costs_by_session_type,
    aggregate_costs_by_time,
    aggregate_costs_total,
    aggregate_truncations_by_model,
    aggregate_truncations_by_time,
    aggregate_truncations_total,
)


class GroupBy(StrEnum):
    """Grouping options for cost aggregation."""

    project = "project"
    model = "model"
    agent_slug = "agent_slug"
    session_type = "session_type"
    external_id = "external_id"
    day = "day"
    week = "week"
    month = "month"
    none = "none"


class CostAggregationResponse(BaseModel):
    """Response for cost aggregation endpoint."""

    aggregations: list[CostAggregation] = Field(..., description="Aggregated cost data")
    total_cost_usd: float = Field(..., description="Grand total cost")
    total_tokens: int = Field(..., description="Grand total tokens")
    total_requests: int = Field(..., description="Total request count")


class TruncationMetricsResponse(BaseModel):
    """Response for truncation metrics endpoint."""

    aggregations: list[TruncationAggregation] = Field(..., description="Aggregated truncation data")
    total_truncations: int = Field(..., description="Total truncation event count")
    truncation_rate: float = Field(
        ..., description="Truncation rate (truncations / total requests)"
    )
    recent_events: list[dict[str, Any]] = Field(default=[], description="Recent truncation events")


async def dispatch_cost_aggregation(
    db: AsyncSession, group_by: GroupBy, filters: CostFilters
) -> list[CostAggregation]:
    """Dispatch to the appropriate cost aggregation function based on group_by."""
    if group_by == GroupBy.project:
        return await aggregate_costs_by_project(db, filters)
    if group_by == GroupBy.agent_slug:
        return await aggregate_costs_by_agent(db, filters)
    if group_by == GroupBy.session_type:
        return await aggregate_costs_by_session_type(db, filters)
    if group_by == GroupBy.external_id:
        return await aggregate_costs_by_external_id(db, filters)
    if group_by == GroupBy.model:
        return await aggregate_costs_by_model(db, filters)
    if group_by in (GroupBy.day, GroupBy.week, GroupBy.month):
        return await aggregate_costs_by_time(db, filters, group_by.value)
    return await aggregate_costs_total(db, filters)


async def dispatch_truncation_aggregation(
    db: AsyncSession, group_by: GroupBy, filters: TruncationFilters
) -> list[TruncationAggregation]:
    """Dispatch to the appropriate truncation aggregation function based on group_by."""
    if group_by == GroupBy.model:
        return await aggregate_truncations_by_model(db, filters)
    if group_by in (GroupBy.day, GroupBy.week, GroupBy.month):
        return await aggregate_truncations_by_time(db, filters, group_by.value)
    return await aggregate_truncations_total(db, filters)
