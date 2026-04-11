"""Admin API schemas for request/response models."""

from datetime import datetime

from pydantic import BaseModel, Field


class ClientControlResponse(BaseModel):
    """Response for client control status."""

    client_name: str
    enabled: bool
    disabled_at: datetime | None
    disabled_by: str | None
    reason: str | None
    created_at: datetime
    updated_at: datetime


class DisableRequest(BaseModel):
    """Request to disable a client."""

    reason: str | None = Field(default=None, max_length=500, description="Reason for disabling")
    disabled_by: str | None = Field(
        default=None, max_length=100, description="User/admin who disabled"
    )


class ClientListResponse(BaseModel):
    """Response for listing clients."""

    clients: list[ClientControlResponse]
    total: int


class BlockedRequestLog(BaseModel):
    """A log entry for a blocked request."""

    timestamp: datetime
    client_name: str | None
    source_path: str | None
    block_reason: str
    endpoint: str


class BlockedRequestsResponse(BaseModel):
    """Response for blocked requests log."""

    requests: list[BlockedRequestLog]
    total: int


class RequestAuditLog(BaseModel):
    """A log entry for any API request (for visibility)."""

    timestamp: datetime
    endpoint: str
    method: str
    client_name: str | None
    source_path: str | None
    user_agent: str | None
    referer: str | None
    client_ip: str | None
    status: str  # "allowed", "blocked", "unknown_client"


class RequestAuditResponse(BaseModel):
    """Response for request audit log."""

    requests: list[RequestAuditLog]
    total: int


class UnknownCallerStats(BaseModel):
    """Stats for an unknown caller (no X-Source-Client)."""

    fingerprint: str
    count: int
    first_seen: datetime | None
    last_seen: datetime | None
    endpoints: list[str]
    user_agents: list[str]


class UnknownCallersResponse(BaseModel):
    """Response for unknown callers list."""

    callers: list[UnknownCallerStats]
    total: int
    total_requests: int


class WorkflowScheduleResponse(BaseModel):
    """Admin-facing static workflow schedule state."""

    schedule_id: str
    label: str
    description: str
    cron: str
    category: str
    default_enabled: bool
    enabled: bool
    notes: str | None
    updated_by: str | None


class WorkflowScheduleUpdate(BaseModel):
    """Enable/disable payload for a static workflow schedule."""

    enabled: bool
    updated_by: str | None = Field(default=None, max_length=100)


class HotspotTotals(BaseModel):
    """Top-line hotspot metrics for the selected window."""

    sessions: int
    input_tokens: int
    output_tokens: int
    total_cost_usd: float
    active_sessions: int
    zero_event_active_sessions: int
    rate_limit_fallback_sessions: int
    missing_attribution_sessions: int


class HotspotBreakdownRow(BaseModel):
    """Grouped hotspot breakdown row."""

    kind: str
    label: str
    sessions: int
    input_tokens: int
    output_tokens: int
    total_cost_usd: float


class RepeatedWorkloadRow(BaseModel):
    """Repeated workload group for the hotspot panel."""

    workload_key: str
    label: str
    detail: str | None
    project_id: str
    agent_slug: str | None
    sessions: int
    input_tokens: int
    output_tokens: int
    total_cost_usd: float


class LowYieldSessionRow(BaseModel):
    """Session with high input and low output."""

    session_id: str
    project_id: str
    agent_slug: str | None
    status: str
    model: str
    label: str
    input_tokens: int
    output_tokens: int
    total_cost_usd: float
    attribution_label: str | None
    efficiency_ratio: float


class ZeroEventActiveSessionRow(BaseModel):
    """Currently active session with no event trail."""

    session_id: str
    project_id: str
    agent_slug: str | None
    request_source: str | None
    quiet_for_seconds: int
    lifecycle_state: str | None


class SessionHotspotsResponse(BaseModel):
    """Admin hotspot snapshot for recent session churn."""

    generated_at: datetime
    window_hours: int
    totals: HotspotTotals
    attribution_breakdown: list[HotspotBreakdownRow]
    repeated_workloads: list[RepeatedWorkloadRow]
    low_yield_sessions: list[LowYieldSessionRow]
    zero_event_active_sessions: list[ZeroEventActiveSessionRow]
