"""Pydantic schemas for the persona API."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Core persona schemas
# ---------------------------------------------------------------------------


class PersonaUserProfile(BaseModel):
    """Structured user-profile fields Jenny can rely on at runtime."""

    user_identity: str | None = Field(default=None, max_length=2000)
    work_context: str | None = Field(default=None, max_length=2000)
    communication_style: str | None = Field(default=None, max_length=1000)
    autonomy_level: str | None = Field(default=None, max_length=500)
    notification_preferences: str | None = Field(default=None, max_length=1000)
    timezone: str | None = Field(default=None, max_length=100)
    working_schedule: str | None = Field(default=None, max_length=1000)
    priorities_values: str | None = Field(default=None, max_length=2000)
    tools_and_integrations: str | None = Field(default=None, max_length=2000)
    boundaries_and_escalation: str | None = Field(default=None, max_length=2000)


class PersonaResponse(BaseModel):
    """Full persona representation."""

    id: int
    name: str
    personality: str | None = None
    user_profile: PersonaUserProfile | None = None
    heartbeat_instructions: str | None = None
    user_context: str | None = None
    voice_id: str = "en-US-AriaNeural"
    voice_enabled: bool = False
    heartbeat_interval_minutes: int = 60
    execution_state: str = "active"
    avatar_url: str | None = None
    greeting: str | None = None
    onboarding_complete: bool = False
    onboarding_phase: str = "not_started"
    session_reset_mode: str = "off"
    session_reset_hour: int = 9
    session_reset_idle_minutes: int = 120
    limits: dict | None = None
    agent_slug: str = "persona"
    version: int = 1
    updated_at: str | None = None


class PersonaUpdate(BaseModel):
    """Partial update for persona fields."""

    name: str | None = Field(default=None, max_length=100)
    personality: str | None = Field(default=None, max_length=50000)
    user_profile: PersonaUserProfile | None = None
    heartbeat_instructions: str | None = Field(default=None, max_length=10000)
    user_context: str | None = Field(default=None, max_length=10000)
    voice_id: str | None = Field(default=None, max_length=200)
    voice_enabled: bool | None = None
    heartbeat_interval_minutes: int | None = Field(default=None, ge=0, le=1440)
    execution_state: str | None = Field(default=None, pattern="^(active|paused)$")
    avatar_url: str | None = Field(default=None, max_length=500)
    greeting: str | None = Field(default=None, max_length=2000)
    session_reset_mode: str | None = Field(default=None, pattern="^(off|daily|idle)$")
    session_reset_hour: int | None = Field(default=None, ge=0, le=23)
    session_reset_idle_minutes: int | None = Field(default=None, ge=5, le=1440)
    limits: dict | None = None


# ---------------------------------------------------------------------------
# Personality sub-resource schemas
# ---------------------------------------------------------------------------


class PersonaPersonalityResponse(BaseModel):
    """Just the personality text."""

    personality: str | None = None
    version: int = 1


class PersonaPersonalityUpdate(BaseModel):
    """Update the personality document."""

    personality: str = Field(max_length=50000, description="The new personality document (markdown)")
    reason: str = Field(
        default="",
        max_length=500,
        description="Why the personality is being updated (for audit trail)",
    )



# ---------------------------------------------------------------------------
# Activity timeline schemas
# ---------------------------------------------------------------------------


class ActivityEventPreview(BaseModel):
    """Minimal event for collapsed session cards."""

    event_type: str
    tool_name: str | None = None
    content_preview: str | None = None


class ActivitySession(BaseModel):
    """A session in the activity timeline."""

    id: str
    session_type: str
    summary_oneliner: str | None = None
    status: str
    message_count: int
    created_at: datetime
    updated_at: datetime
    events_preview: list[ActivityEventPreview] = Field(default_factory=list)


class ActivityResponse(BaseModel):
    """Chronological list of persona sessions."""

    sessions: list[ActivitySession]
    total: int
    page: int
    page_size: int


class PersonaStreamEntry(BaseModel):
    """Single item in Jenny's unified chronological stream."""

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
    current_branch: str | None = None
    external_id: str | None = None
    model: str | None = None
    live_summary: str | None = None
    live_status: str | None = None
    message_count: int = 0
    tool_count: int = 0
    event_previews: list[PersonaStreamEventPreview] = Field(default_factory=list)
    issue_markers: list[PersonaIssueMarker] = Field(default_factory=list)
    pulse_tags: list[str] = Field(default_factory=list)
    primary_pulse_tag: str | None = None
    root_causes: list[str] = Field(default_factory=list)
    primary_root_cause: str | None = None
    pulse_summary: str | None = None


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


class PersonaStreamResponse(BaseModel):
    """Unified timeline response for the persona workspace."""

    entries: list[PersonaStreamEntry]
    total: int
    page: int
    page_size: int
    matches: list[PersonaStreamMatch] = Field(default_factory=list)
    match_count: int = 0
    pulse: PersonaPulseSummary = Field(default_factory=lambda: PersonaPulseSummary())


class PersonaStreamMatch(BaseModel):
    """Search match metadata for jumping through Jenny history."""

    entry_id: str
    session_id: str
    entry_type: str
    timestamp: datetime
    snippet: str


class PersonaPulseMetric(BaseModel):
    """Single metric shown in Jenny's pulse strip."""

    key: str
    label: str
    count: int
    description: str


class PersonaIssueGroup(BaseModel):
    """Repeated issue fingerprint aggregated across Jenny sessions."""

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
    """Pulse snapshot for the current Jenny history window."""

    metrics: list[PersonaPulseMetric] = Field(default_factory=list)
    issue_groups: list[PersonaIssueGroup] = Field(default_factory=list)
    agent_scorecards: list[PersonaAgentScorecard] = Field(default_factory=list)
