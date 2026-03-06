"""Provider-agnostic session ingestion models."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class SessionUpsertRequest(BaseModel):
    """Canonical request for creating or updating a session."""

    session_id: str | None = Field(default=None, description="Stable session identifier")
    project_id: str = Field(..., description="Project identifier")
    provider: str = Field(..., description="Provider slug")
    model: str = Field(..., description="Model identifier")
    session_type: str = Field(default="completion", description="Logical session type")
    agent_slug: str | None = Field(default=None, description="Optional agent slug")
    external_id: str | None = Field(default=None, description="Caller-defined correlation ID")
    client_id: str | None = Field(default=None, description="Authenticated client ID")
    request_source: str | None = Field(default=None, description="Request source header")
    current_branch: str | None = Field(default=None, description="Git branch at session start")
    cwd: str | None = Field(default=None, description="Provider working directory")
    provider_metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Provider-specific metadata merged onto the session row",
    )


class SessionUpsertResult(BaseModel):
    """Outcome of upserting a session."""

    session_id: str
    created: bool


class NormalizedEvent(BaseModel):
    """Canonical event shape accepted by ingestion."""

    event_type: str = Field(..., description="Canonical event type")
    turn: int | None = Field(default=None, description="Conversation turn")
    sequence: int | None = Field(default=None, description="Sequence inside turn")
    role: str | None = Field(default=None, description="Message role")
    content: str | None = Field(default=None, description="Text content")
    tool_name: str | None = Field(default=None, description="Tool name")
    tool_input: dict[str, Any] | None = Field(default=None, description="Tool input payload")
    tool_output: dict[str, Any] | None = Field(default=None, description="Tool output payload")
    tokens: int | None = Field(default=None, description="Token count")
    duration_ms: int | None = Field(default=None, description="Duration in milliseconds")
    model_used: str | None = Field(default=None, description="Model used for the event")
    agent_id: str | None = Field(default=None, description="Agent identifier")
    agent_name: str | None = Field(default=None, description="Agent display name")


class AppendNormalizedEventsRequest(BaseModel):
    """Batch append request for normalized session events."""

    events: list[NormalizedEvent] = Field(default_factory=list)


class AppendNormalizedEventsResult(BaseModel):
    """Outcome of appending normalized events."""

    session_id: str
    events_appended: int
    last_turn: int
    last_sequence: int
    event_ids: list[str] = Field(default_factory=list)


class FinalizeSessionRequest(BaseModel):
    """Canonical finalization request."""

    citation_prefixes: list[str] | None = None
    feedback_tags: list[str] | None = None
    summary_tags: list[str] | None = None
    git_context: str | None = None
    branch: str | None = None
    is_worktree: bool = False
    transcript_path: str | None = None


class FinalizeSessionResult(BaseModel):
    """Outcome of finalizing a session."""

    session_id: str
    citations_found: int
    citations_credited: int
    feedback_created: int = 0
    summary_stored: bool = False
