"""Session-related models for Agent Hub client."""

from datetime import datetime

from pydantic import BaseModel, Field

from agent_hub.models.content import Message
from agent_hub.models.usage import ContextUsage


class SessionCreate(BaseModel):
    """Request to create a new session."""

    project_id: str = Field(..., description="Project identifier")
    provider: str = Field(..., description="Provider: claude or gemini")
    model: str = Field(..., description="Model identifier")


class SessionResponse(BaseModel):
    """Response from session operations."""

    id: str
    project_id: str
    provider: str
    model: str
    status: str
    created_at: datetime
    updated_at: datetime
    messages: list[Message] = Field(default_factory=list)
    context_usage: ContextUsage | None = Field(default=None)


class SessionListItem(BaseModel):
    """Session item in list response."""

    id: str
    project_id: str
    provider: str
    model: str
    status: str
    message_count: int
    created_at: datetime
    updated_at: datetime


class SessionListResponse(BaseModel):
    """Response from listing sessions."""

    sessions: list[SessionListItem]
    total: int
    page: int
    page_size: int
