"""Provider-agnostic session ingestion models."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.models.field_lengths import EXTERNAL_ID_MAX_LENGTH


class SessionUpsertRequest(BaseModel):
    """Canonical request for creating or updating a session."""

    session_id: str | None = Field(default=None, description="Stable session identifier")
    project_id: str = Field(..., description="Project identifier")
    provider: str = Field(..., description="Provider slug")
    model: str = Field(..., description="Model identifier")
    session_type: str = Field(default="completion", description="Logical session type")
    agent_slug: str | None = Field(default=None, description="Optional agent slug")
    external_id: str | None = Field(
        default=None,
        max_length=EXTERNAL_ID_MAX_LENGTH,
        description="Caller-defined correlation ID",
    )
    client_id: str | None = Field(default=None, description="Authenticated client ID")
    request_source: str | None = Field(default=None, description="Request source header")
    current_branch: str | None = Field(default=None, description="Git branch at session start")
    parent_session_id: str | None = Field(
        default=None,
        description="Optional parent session for dispatched or branched work",
    )
    cwd: str | None = Field(default=None, description="Provider working directory")
    declared_scope_paths: list[str] = Field(
        default_factory=list,
        description="Explicit file/path scope declared for this session",
    )
    observed_read_paths: list[str] = Field(
        default_factory=list,
        description="Observed read paths captured during registration",
    )
    observed_write_paths: list[str] = Field(
        default_factory=list,
        description="Observed write paths captured during registration",
    )
    scope_confidence: str | None = Field(
        default=None,
        description="declared | observed_write | observed_read | unknown",
    )
    provider_metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Provider-specific metadata merged onto the session row",
    )


class SessionUpsertResult(BaseModel):
    """Outcome of upserting a session."""

    session_id: str
    created: bool


class SessionHeartbeatRequest(BaseModel):
    """Canonical heartbeat request for live session/process state."""

    client_id: str | None = Field(default=None, description="Authenticated client ID")
    request_source: str | None = Field(default=None, description="Request source header")
    cwd: str | None = Field(default=None, description="Current working directory")
    current_branch: str | None = Field(default=None, description="Current git branch")
    declared_scope_paths: list[str] = Field(default_factory=list)
    active_read_paths: list[str] = Field(default_factory=list)
    active_write_paths: list[str] = Field(default_factory=list)
    scope_confidence: str | None = Field(default=None)
    phase: str | None = Field(default=None)
    status: str | None = Field(default=None)
    summary: str | None = Field(default=None)
    current_tool_name: str | None = Field(default=None)
    current_command: str | None = Field(default=None)
    last_event_type: str | None = Field(default=None)
    heartbeat_at: datetime | None = Field(default=None, description="Explicit heartbeat timestamp")
    provider_metadata: dict[str, Any] = Field(default_factory=dict)


class SessionHeartbeatResult(BaseModel):
    """Outcome of applying a session heartbeat."""

    session_id: str
    updated: bool = True


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
    transport: str | None = Field(default=None, description="Transport source such as web or telegram")
    surface: str | None = Field(default=None, description="UI surface that created the event")
    chat_id: str | None = Field(default=None, description="External chat id for transport correlation")
    message_id: str | None = Field(default=None, description="External message id for transport correlation")
    pane_id: str | None = Field(default=None, description="Work Chats pane id")
    source_client: str | None = Field(default=None, description="Logical caller identifier")


class AppendNormalizedEventsRequest(BaseModel):
    """Batch append request for normalized session events."""

    events: list[NormalizedEvent] = Field(default_factory=list)


class AppendNormalizedEventsResult(BaseModel):
    """Outcome of appending normalized events."""

    session_id: str
    events_appended: int
    events_skipped: int = 0
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
    transcript_path: str | None = None


class FinalizeSessionResult(BaseModel):
    """Outcome of finalizing a session."""

    session_id: str
    citations_found: int
    citations_credited: int
    feedback_created: int = 0
    summary_stored: bool = False


class TranscriptIngestRequest(BaseModel):
    """Ingest a provider transcript into normalized session events."""

    provider: str
    transcript_path: str
    checkpoint: str | None = None


class TranscriptIngestResult(BaseModel):
    """Outcome of ingesting transcript-backed events."""

    session_id: str
    provider: str
    transcript_path: str
    events_appended: int
    events_skipped: int = 0
    last_turn: int
    last_sequence: int
    event_ids: list[str] = Field(default_factory=list)
    next_checkpoint: str | None = None
    boundaries: list[str] = Field(default_factory=list)
