"""Schemas for Access Control API endpoints."""

from datetime import datetime

from pydantic import BaseModel, Field

from app.constants import DEFAULT_RATE_LIMIT_TPM


# Client schemas
class ClientCreateRequest(BaseModel):
    """Request to create a new client."""

    display_name: str = Field(..., min_length=1, max_length=100)
    client_type: str = Field(default="external", pattern="^(internal|external|service)$")
    rate_limit_rpm: int = Field(default=60, ge=1, le=10000)
    rate_limit_tpm: int = Field(default=DEFAULT_RATE_LIMIT_TPM, ge=1000, le=10000000)


class ClientCreateResponse(BaseModel):
    """Response for client creation."""

    client_id: str
    display_name: str
    client_type: str
    status: str
    rate_limit_rpm: int
    rate_limit_tpm: int
    created_at: datetime


class ClientResponse(BaseModel):
    """Response for client details."""

    client_id: str
    display_name: str
    client_type: str
    status: str
    rate_limit_rpm: int
    rate_limit_tpm: int
    allowed_projects: list[str] | None = None  # None = unrestricted
    created_at: datetime
    updated_at: datetime
    last_used_at: datetime | None
    suspended_at: datetime | None
    suspended_by: str | None
    suspension_reason: str | None


class ClientUpdateRequest(BaseModel):
    """Request to update client settings."""

    display_name: str | None = Field(default=None, min_length=1, max_length=100)
    rate_limit_rpm: int | None = Field(default=None, ge=1, le=10000)
    rate_limit_tpm: int | None = Field(default=None, ge=1000, le=10000000)
    allowed_projects: list[str] | None = Field(
        default=None,
        description="List of allowed project_ids. Empty list = no projects allowed. Omit/null to keep unchanged.",
    )


class ClientListResponse(BaseModel):
    """Response for listing clients."""

    clients: list[ClientResponse]
    total: int


class ClientStatsResponse(BaseModel):
    """Response for client statistics."""

    total_clients: int
    active_clients: int
    suspended_clients: int
    blocked_clients: int
    blocked_requests_today: int
    total_requests_today: int


class SuspendRequest(BaseModel):
    """Request to suspend a client."""

    reason: str = Field(..., min_length=1, max_length=500)
    suspended_by: str = Field(default="admin", max_length=100)


class BlockRequest(BaseModel):
    """Request to permanently block a client."""

    reason: str = Field(..., min_length=1, max_length=500)
    blocked_by: str = Field(default="admin", max_length=100)


# Request log schemas
class RequestLogEntry(BaseModel):
    """A request log entry."""

    id: int
    client_id: str | None
    client_display_name: str | None
    request_source: str | None
    endpoint: str
    method: str
    status_code: int
    rejection_reason: str | None
    tokens_in: int | None
    tokens_out: int | None
    latency_ms: int | None
    model: str | None
    agent_slug: str | None
    tool_type: str | None
    tool_name: str | None
    source_path: str | None
    created_at: datetime


class RequestLogResponse(BaseModel):
    """Response for request log listing."""

    requests: list[RequestLogEntry]
    total: int


# Metrics schemas
class ToolTypeSummary(BaseModel):
    """Summary by tool type."""

    tool_type: str
    count: int


class ToolNameSummary(BaseModel):
    """Summary by tool name."""

    tool_name: str
    count: int
    avg_latency_ms: float
    success_rate: float


class EndpointSummary(BaseModel):
    """Summary by endpoint."""

    endpoint: str
    count: int
    avg_latency_ms: float
    success_rate: float


class RequestMetricsSummary(BaseModel):
    """Aggregated request metrics."""

    total_requests: int
    avg_latency_ms: float
    success_rate: float


class RequestMetricsResponse(BaseModel):
    """Response for request metrics endpoint."""

    summary: RequestMetricsSummary
    by_tool_type: list[ToolTypeSummary]
    by_tool_name: list[ToolNameSummary]
    by_endpoint: list[EndpointSummary]
