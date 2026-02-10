"""API key management schemas."""

from datetime import datetime

from pydantic import BaseModel, Field


class APIKeyCreate(BaseModel):
    """Request to create a new API key."""

    name: str | None = Field(default=None, max_length=100, description="Friendly name for the key")
    project_id: str = Field(default="default", description="Project ID for cost tracking")
    rate_limit_rpm: int = Field(default=60, ge=1, le=1000, description="Requests per minute limit")
    rate_limit_tpm: int = Field(
        default=100000, ge=1000, le=10000000, description="Tokens per minute limit"
    )
    expires_in_days: int | None = Field(
        default=None, ge=1, le=365, description="Expiration in days"
    )


class APIKeyCreateResponse(BaseModel):
    """Response when creating an API key. Contains the full key (shown once)."""

    id: int
    key: str = Field(..., description="Full API key - save this, it won't be shown again!")
    key_prefix: str = Field(..., description="Key prefix for identification")
    name: str | None
    project_id: str
    rate_limit_rpm: int
    rate_limit_tpm: int
    created_at: datetime
    expires_at: datetime | None


class APIKeyResponse(BaseModel):
    """Response for API key info (no full key)."""

    id: int
    key_prefix: str
    name: str | None
    project_id: str
    rate_limit_rpm: int
    rate_limit_tpm: int
    is_active: bool
    last_used_at: datetime | None
    created_at: datetime
    expires_at: datetime | None


class APIKeyListResponse(BaseModel):
    """Response for listing API keys."""

    keys: list[APIKeyResponse]
    total: int


class APIKeyUpdate(BaseModel):
    """Request to update an API key."""

    name: str | None = Field(default=None, max_length=100)
    rate_limit_rpm: int | None = Field(default=None, ge=1, le=1000)
    rate_limit_tpm: int | None = Field(default=None, ge=1000, le=10000000)
