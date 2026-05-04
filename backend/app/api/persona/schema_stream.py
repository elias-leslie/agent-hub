"""Persona stream and pulse schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class PersonaStreamEventPreview(BaseModel):
    """Compact event preview for expandable stream cards."""

    id: str
    event_type: str
    created_at: datetime
    role: str | None = None
    tool_name: str | None = None
    content_preview: str | None = None
    tool_input_preview: str | None = None
    tool_output_preview: str | None = None
    duration_ms: int | None = None
    model_used: str | None = None


class PersonaIssueMarker(BaseModel):
    """Human-readable issue marker for a specific session event or synthetic issue."""

    event_id: str
    event_type: str
    created_at: datetime
    tool_name: str | None = None
    tags: list[str] = Field(default_factory=list)
    primary_tag: str
    root_causes: list[str] = Field(default_factory=list)
    primary_root_cause: str | None = None
    title: str
    summary: str
    detail: str | None = None
    fingerprint: str | None = None


class PersonaPulseMetric(BaseModel):
    """Single metric shown in the persona pulse strip."""

    key: str
    label: str
    count: int
    description: str


class PersonaIssueGroup(BaseModel):
    """Repeated issue fingerprint aggregated across persona sessions."""

    fingerprint: str
    title: str
    summary: str
    count: int
    primary_tag: str
    root_cause: str | None = None
    agent_slugs: list[str] = Field(default_factory=list)
    latest_entry_id: str | None = None
    latest_session_id: str | None = None
    latest_timestamp: datetime | None = None


class PersonaAgentScorecard(BaseModel):
    """Per-agent health summary for the selected timeline window."""

    agent_slug: str
    label: str
    session_count: int
    success_count: int
    friction_count: int
    error_count: int
    recovered_count: int
    stalled_count: int
    instruction_drift_count: int
    tool_friction_count: int
    median_runtime_seconds: int | None = None
    top_issue: str | None = None
    top_root_cause: str | None = None


class PersonaPulseSummary(BaseModel):
    """Pulse snapshot for the current persona history window."""

    metrics: list[PersonaPulseMetric] = Field(default_factory=list)
    issue_groups: list[PersonaIssueGroup] = Field(default_factory=list)
    agent_scorecards: list[PersonaAgentScorecard] = Field(default_factory=list)


class PersonaStreamEntry(BaseModel):
    """Single item in the persona's unified chronological stream."""

    id: str
    entry_type: str
    timestamp: datetime
    session_id: str
    parent_session_id: str | None = None
    project_id: str
    agent_slug: str | None = None
    session_type: str
    status: str
    role: str | None = None
    content: str | None = None
    summary_oneliner: str | None = None
    display_summary: str | None = None
    current_branch: str | None = None
    external_id: str | None = None
    model: str | None = None
    live_summary: str | None = None
    live_status: str | None = None
    live_topic: str | None = None
    message_count: int = 0
    tool_count: int = 0
    event_previews: list[PersonaStreamEventPreview] = Field(default_factory=list)
    issue_markers: list[PersonaIssueMarker] = Field(default_factory=list)
    pulse_tags: list[str] = Field(default_factory=list)
    primary_pulse_tag: str | None = None
    root_causes: list[str] = Field(default_factory=list)
    primary_root_cause: str | None = None
    pulse_summary: str | None = None


class PersonaStreamMatch(BaseModel):
    """Search match metadata for jumping through persona history."""

    entry_id: str
    session_id: str
    entry_type: str
    timestamp: datetime
    snippet: str


class PersonaStreamResponse(BaseModel):
    """Unified timeline response for the persona workspace."""

    entries: list[PersonaStreamEntry]
    total: int
    page: int
    page_size: int
    matches: list[PersonaStreamMatch] = Field(default_factory=list)
    match_count: int = 0
    pulse: PersonaPulseSummary = Field(default_factory=PersonaPulseSummary)
