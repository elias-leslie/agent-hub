"""
Data models for analytics service.

Defines filters and aggregation models for cost and truncation analytics.
"""

from datetime import datetime

from pydantic import BaseModel, Field


class CostAggregation(BaseModel):
    """Aggregated cost data for a group."""

    group_key: str = Field(..., description="Group identifier")
    total_tokens: int = Field(..., description="Total tokens (input + output)")
    input_tokens: int = Field(..., description="Total input tokens")
    output_tokens: int = Field(..., description="Total output tokens")
    total_cost_usd: float = Field(..., description="Total estimated cost in USD")
    request_count: int = Field(..., description="Number of requests")


class TruncationAggregation(BaseModel):
    """Aggregated truncation data for a group."""

    group_key: str = Field(..., description="Group identifier (model, day, etc.)")
    truncation_count: int = Field(..., description="Number of truncation events")
    avg_output_tokens: float = Field(..., description="Average output tokens when truncated")
    avg_max_tokens: float = Field(..., description="Average max_tokens requested")
    capped_count: int = Field(..., description="Events where max_tokens was capped to model limit")


class CostFilters(BaseModel):
    """Filters for cost aggregation queries."""

    project_id: str | None = None
    model: str | None = None
    agent_slug: str | None = None
    session_type: str | None = None
    external_id: str | None = None
    start_date: datetime | None = None
    end_date: datetime | None = None


class TruncationFilters(BaseModel):
    """Filters for truncation aggregation queries."""

    model: str | None = None
    project_id: str | None = None
    start_date: datetime | None = None
    end_date: datetime | None = None
