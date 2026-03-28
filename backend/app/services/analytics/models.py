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


class CostLogExportFilters(BaseModel):
    """Filters for raw cost-log export."""

    project_id: str | None = None
    after_id: int | None = None
    limit: int = 100
    external_id: str | None = None
    session_id: str | None = None
    created_after: datetime | None = None
    created_before: datetime | None = None


class CostLogExportRow(BaseModel):
    """Raw cost-log row with joined session metadata for finance sync."""

    id: int = Field(..., description="Immutable cost-log row ID")
    session_id: str = Field(..., description="Owning session ID")
    project_id: str = Field(..., description="Execution project ID")
    agent_slug: str | None = Field(default=None, description="Agent slug if set on the session")
    external_id: str | None = Field(default=None, description="Caller-defined external identifier")
    trace_id: str | None = Field(default=None, description="Execution correlation ID if present")
    client_id: str | None = Field(default=None, description="Calling client ID")
    request_source: str | None = Field(default=None, description="Caller attribution header value")
    session_type: str = Field(..., description="Session category")
    provider: str = Field(..., description="Provider recorded on the session")
    model: str = Field(..., description="Model recorded on the cost log")
    input_tokens: int = Field(..., description="Input tokens for this row")
    output_tokens: int = Field(..., description="Output tokens for this row")
    cost_usd: float = Field(..., description="Estimated USD cost for this row")
    created_at: datetime = Field(..., description="Creation timestamp")


class TruncationFilters(BaseModel):
    """Filters for truncation aggregation queries."""

    model: str | None = None
    project_id: str | None = None
    start_date: datetime | None = None
    end_date: datetime | None = None
