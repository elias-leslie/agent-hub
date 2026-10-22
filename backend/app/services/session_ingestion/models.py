"""Provider-agnostic session ingestion models."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError

from app.models.field_lengths import EXTERNAL_ID_MAX_LENGTH


class SessionModelEvidence(BaseModel):
    """Current native turn routing and independently observed delivery evidence."""

    session_id: str = Field(max_length=512)
    native_thread_id: str | None = Field(default=None, max_length=512)
    transcript_runtime_session_id: str | None = Field(default=None, max_length=512)
    native_session_id: str | None = Field(default=None, max_length=512, description="Legacy transcript runtime alias; never the canonical thread subject")
    turn_id: str | None = Field(default=None, max_length=512)
    source: Literal["codex_transcript"] = "codex_transcript"
    source_path: str | None = Field(default=None, max_length=4096)
    source_generation: str | None = Field(default=None, max_length=512)
    source_line: int | None = Field(default=None, ge=1)
    source_timestamp: datetime | None = None
    requested_model: str | None = Field(default=None, max_length=512)
    requested_reasoning_effort: str | None = Field(default=None, max_length=64)
    observed_model: str | None = Field(default=None, max_length=512)
    observed_source: Literal["codex.response_item.model", "codex.token_usage_record.model"] | None = None
    observed_source_line: int | None = Field(default=None, ge=1)
    observed_source_timestamp: datetime | None = None


def validated_native_model_evidence(
    session_id: str, metadata: dict[str, Any] | None,
) -> SessionModelEvidence | None:
    """Read evidence only when it names this session's committed native source."""
    metadata = metadata or {}
    raw = metadata.get("model_evidence")
    if not isinstance(raw, dict):
        return None
    try:
        evidence = SessionModelEvidence.model_validate({
            **raw, "native_thread_id": raw.get("native_thread_id") or raw.get("session_id"),
            "transcript_runtime_session_id": raw.get("transcript_runtime_session_id") or raw.get("native_session_id"),
        })
    except ValidationError:
        return None
    retained = metadata.get("transcript_ingestion")
    retained = retained if isinstance(retained, dict) else {}
    health = retained.get("source_health")
    health = health if isinstance(health, dict) else {}
    if (
        evidence.session_id != session_id
        or evidence.native_thread_id != session_id
        or (evidence.native_session_id is not None and evidence.transcript_runtime_session_id != evidence.native_session_id)
        or evidence.source_path != metadata.get("transcript_path")
        or not evidence.source_generation
        or evidence.source_generation != health.get("source_generation")
    ):
        return None
    if evidence.observed_model and not (
        evidence.turn_id and evidence.observed_source and evidence.observed_source_line
        and evidence.observed_source_timestamp and evidence.source_timestamp
    ):
        return evidence.model_copy(update={
            "observed_model": None, "observed_source": None,
            "observed_source_line": None, "observed_source_timestamp": None,
        })
    return evidence


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

    native_observation: dict[str, Any] | None = Field(default=None, exclude=True)
    event_type: str = Field(..., description="Canonical event type")
    turn: int | None = Field(default=None, description="Conversation turn")
    sequence: int | None = Field(default=None, description="Sequence inside turn")
    role: str | None = Field(default=None, description="Message role")
    content: str | None = Field(default=None, description="Text content")
    tool_name: str | None = Field(default=None, description="Tool name")
    call_id: str | None = Field(default=None, description="Native tool call/result correlation ID")
    tool_input: dict[str, Any] | None = Field(default=None, description="Tool input payload")
    tool_output: dict[str, Any] | None = Field(default=None, description="Tool output payload")
    tokens: int | None = Field(default=None, description="Token count")
    duration_ms: int | None = Field(default=None, description="Duration in milliseconds")
    model_used: str | None = Field(default=None, description="Model used for the event")
    agent_id: str | None = Field(default=None, description="Agent identifier")
    agent_name: str | None = Field(default=None, description="Agent display name")
    transport: str | None = Field(default=None, description="Transport source such as web or cli")
    surface: str | None = Field(default=None, description="UI surface that created the event")
    chat_id: str | None = Field(default=None, description="External chat id for transport correlation")
    message_id: str | None = Field(default=None, description="External message id for transport correlation")
    pane_id: str | None = Field(default=None, description="Work Chats pane id")
    source_client: str | None = Field(default=None, description="Logical caller identifier")
    source_event_id: str | None = Field(default=None, max_length=255, description="Stable provider event identity")
    source_timestamp: datetime | None = Field(default=None, description="Original provider timestamp")
    usage: dict[str, Any] | None = Field(default=None, description="Native usage with scope and provenance")


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


class TranscriptSourceIssue(BaseModel):
    """Typed source condition that affects transcript completeness."""

    code: str
    count: int = Field(default=1, ge=1)
    blocking: bool = True
    detail: str | None = None


class TranscriptSourceHealth(BaseModel):
    """Observed native transcript extent and committed parser cursor."""

    state: Literal["ready", "incomplete", "blocked"]
    observed_at: datetime
    parser_version: str
    source_generation: str | None = None
    committed_line_count: int = 0
    committed_byte_offset: int = 0
    observed_extent: int | None = None
    pending_bytes: int | None = None
    caught_up: bool = False
    active_call_ids: list[str] = Field(default_factory=list)
    pending_wrapper_call_ids: list[str] = Field(default_factory=list)
    yielded_wrapper_call_ids: list[str] = Field(default_factory=list)
    issues: list[TranscriptSourceIssue] = Field(default_factory=list)


class TranscriptIngestResult(BaseModel):
    """Outcome of ingesting transcript-backed events."""

    session_id: str
    provider: str
    transcript_path: str
    events_appended: int
    events_skipped: int = 0
    events_updated: int = 0
    events_deduplicated: int = 0
    last_turn: int
    last_sequence: int
    event_ids: list[str] = Field(default_factory=list)
    next_checkpoint: str | None = None
    boundaries: list[str] = Field(default_factory=list)
    source_health: TranscriptSourceHealth
    model_evidence: SessionModelEvidence | None = None
