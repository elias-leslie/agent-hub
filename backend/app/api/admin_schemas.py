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
