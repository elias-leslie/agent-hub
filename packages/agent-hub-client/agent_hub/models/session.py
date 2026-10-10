"""Session-related models for Agent Hub client."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from agent_hub.models.content import Message
from agent_hub.models.usage import ContextUsage


class SessionModelEvidence(BaseModel):
    """Native current-turn request and independently observed response model."""

    session_id: str
    native_thread_id: str | None = None
    transcript_runtime_session_id: str | None = None
    native_session_id: str | None = None
    turn_id: str | None = None
    source: Literal["codex_transcript"] = "codex_transcript"
    source_path: str | None = None
    source_generation: str | None = None
    source_line: int | None = None
    source_timestamp: datetime | None = None
    requested_model: str | None = None
    requested_reasoning_effort: str | None = None
    observed_model: str | None = None
    observed_source: Literal["codex.response_item.model", "codex.token_usage_record.model"] | None = None
    observed_source_line: int | None = None
    observed_source_timestamp: datetime | None = None


class SessionCreate(BaseModel):
    """Request to create a new session."""

    project_id: str = Field(..., description="Project identifier")
    provider: str = Field(..., description="Provider: claude or gemini")
    model: str = Field(..., description="Model identifier")


class _SessionFields(BaseModel):
    """Routing, workspace and live-activity fields shared by session responses.

    Fields the server adds later are kept rather than dropped, so a caller
    passing a session on loses nothing.
    """

    model_config = ConfigDict(extra="allow")

    requested_provider: str | None = None
    effective_provider: str | None = None
    fallback_used: bool | None = None
    fallback_reason: str | None = None
    external_id: str | None = None
    current_branch: str | None = None
    working_dir: str | None = None
    workstream_status: str | None = None
    live_activity: dict[str, Any] | None = None


class SessionResponse(_SessionFields):
    """Response from session operations."""

    id: str
    project_id: str
    provider: str
    model: str
    model_evidence: SessionModelEvidence | None = None
    requested_model: str | None = None
    effective_model: str | None = None
    parent_session_id: str | None = None
    status: str
    agent_slug: str | None = None
    session_type: str | None = None
    client_id: str | None = None
    request_source: str | None = None
    source_client: str | None = None
    source_path: str | None = None
    created_at: datetime
    updated_at: datetime
    messages: list[Message] = Field(default_factory=list)
    context_usage: ContextUsage | None = Field(default=None)


class SessionListItem(_SessionFields):
    """Session item in list response."""

    id: str
    project_id: str
    provider: str
    model: str
    model_evidence: SessionModelEvidence | None = None
    requested_model: str | None = None
    effective_model: str | None = None
    parent_session_id: str | None = None
    status: str
    agent_slug: str | None = None
    session_type: str | None = None
    client_id: str | None = None
    request_source: str | None = None
    source_client: str | None = None
    source_path: str | None = None
    message_count: int
    created_at: datetime
    updated_at: datetime


class SessionListResponse(BaseModel):
    """Response from listing sessions."""

    sessions: list[SessionListItem]
    total: int
    page: int
    page_size: int
