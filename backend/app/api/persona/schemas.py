"""Pydantic schemas for the persona API."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Core persona schemas
# ---------------------------------------------------------------------------


class PersonaUserProfile(BaseModel):
    """Structured user-profile fields the persona can rely on at runtime."""

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


class PersonaLimits(BaseModel):
    """Validated autonomous-execution limits."""

    max_turns: int | None = Field(default=None, ge=1)

    model_config = {"extra": "forbid"}


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
    limits: PersonaLimits | None = None
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
    limits: PersonaLimits | None = None


class PersonaImprovementScheduleResponse(BaseModel):
    """Current scheduled persona improvement-loop configuration."""

    job_id: str | None = None
    enabled: bool = False
    schedule_type: str = "every"
    schedule_value: str
    schedule_timezone: str = "UTC"
    cadence_minutes: int = 15
    cadence_label: str | None = None
    last_run_at: str | None = None
    next_run_at: str | None = None
    run_count: int = 0


class PersonaAutomationResponse(BaseModel):
    """Persona-owned scheduled automation summary."""

    id: str
    name: str
    schedule_type: str
    schedule_value: str
    schedule_timezone: str = "UTC"
    payload_type: str = "agent_turn"
    payload_message: str
    payload_title: str | None = None
    delivery: str = "none"
    enabled: bool = True
    last_run_at: str | None = None
    next_run_at: str | None = None
    run_count: int = 0
    max_runs: int | None = None
    created_at: str | None = None


class PersonaAutomationCreate(BaseModel):
    """Create one persona-owned scheduled automation."""

    name: str = Field(min_length=1, max_length=200)
    schedule_type: Literal["at", "every", "cron"]
    schedule_value: str = Field(min_length=1, max_length=100)
    schedule_timezone: str = Field(default="UTC", max_length=50)
    payload_type: Literal["agent_turn", "push", "self_honing"] = "agent_turn"
    payload_message: str = Field(min_length=1, max_length=10000)
    payload_title: str | None = Field(default=None, max_length=200)
    delivery: Literal["none", "push"] = "none"
    enabled: bool = True


class PersonaAutomationUpdate(BaseModel):
    """Patch one persona-owned scheduled automation."""

    name: str | None = Field(default=None, min_length=1, max_length=200)
    schedule_type: Literal["at", "every", "cron"] | None = None
    schedule_value: str | None = Field(default=None, min_length=1, max_length=100)
    schedule_timezone: str | None = Field(default=None, max_length=50)
    payload_type: Literal["agent_turn", "push", "self_honing"] | None = None
    payload_message: str | None = Field(default=None, min_length=1, max_length=10000)
    payload_title: str | None = Field(default=None, max_length=200)
    delivery: Literal["none", "push"] | None = None
    enabled: bool | None = None


class PersonaAutomationTriggerResponse(BaseModel):
    """Manual trigger result for one persona-owned automation."""

    job: PersonaAutomationResponse
    output: str
    session_id: str | None = None
    triggered_at: str


class PersonaImprovementScheduleUpdate(BaseModel):
    """Update the scheduled persona improvement loop."""

    enabled: bool
    cadence_minutes: int = Field(default=15, ge=15, le=10080)


class PersonaImprovementOverview(BaseModel):
    """Top-level persona improvement KPIs."""

    total_runs: int = 0
    latest_completed_at: str | None = None
    reliability: float | None = None
    effectiveness: float | None = None
    tokens_per_passed_attempt: float | None = None
    prompt_tokens: float | None = None
    open_regressions: int = 0


class PersonaImprovementTrendPoint(BaseModel):
    """One persona improvement trend point."""

    run_id: str
    completed_at: str | None = None
    run_kind: str
    suite_id: str
    reliability: float | None = None
    effectiveness: float | None = None
    avg_total_tokens: float | None = None
    tokens_per_passed_attempt: float | None = None
    avg_tool_calls: float | None = None
    avg_turns: float | None = None
    prompt_tokens: int | None = None


class PersonaImprovementFamilySummary(BaseModel):
    """Per-family pass-rate summary for one persona improvement run."""

    family: str
    attempts: int = 0
    pass_rate: float = 0.0
    productive_attempts: int = 0


class PersonaImprovementRecentRun(BaseModel):
    """Compact persona improvement run summary for the dashboard."""

    run_id: str
    benchmark_id: str
    suite_id: str
    run_kind: str
    started_at: str
    completed_at: str | None = None
    models: list[str] = Field(default_factory=list)
    case_ids: list[str] = Field(default_factory=list)
    attempt_count: int = 0
    passed_attempt_count: int = 0
    infra_failure_count: int = 0
    reliability: float | None = None
    effectiveness: float | None = None
    avg_total_tokens: float | None = None
    tokens_per_passed_attempt: float | None = None
    avg_tool_calls: float | None = None
    avg_turns: float | None = None
    prompt_tokens: int | None = None
    failure_count: int | None = None
    top_failure_detail: str | None = None
    family_breakdown: list[PersonaImprovementFamilySummary] = Field(default_factory=list)
    experiment_decision: str | None = None
    experiment_decision_reason: str | None = None
    decision_source: str | None = None


class PersonaImprovementOpenRegression(BaseModel):
    """Open persona improvement regression cluster."""

    case_id: str
    failure_detail: str
    occurrence_count: int = 0
    last_seen_at: str | None = None
    latest_avg_score: float | None = None


class PersonaHeartbeatFieldOverview(BaseModel):
    """Scored recent real-heartbeat summary for the persona."""

    total_heartbeats: int = 0
    latest_completed_at: str | None = None
    reliability: float | None = None
    effectiveness: float | None = None
    truth_quality: float | None = None
    tokens_per_healthy_heartbeat: float | None = None
    avg_tool_calls: float | None = None
    avg_turns: float | None = None
    healthy_heartbeats: int = 0
    healthy_rate: float | None = None
    risky_heartbeats: int = 0
    critical_heartbeats: int = 0
    action_heartbeats: int = 0
    action_rate: float | None = None
    ok_heartbeats: int = 0
    ok_rate: float | None = None
    partial_heartbeats: int = 0
    partial_rate: float | None = None
    completed_heartbeats: int = 0
    failed_heartbeats: int = 0
    unknown_heartbeats: int = 0
    top_issue_code: str | None = None
    top_issue_label: str | None = None
    top_issue_count: int = 0


class PersonaHeartbeatFieldTrendPoint(BaseModel):
    """One recent real-heartbeat trend point."""

    session_id: str
    completed_at: str | None = None
    reliability: float | None = None
    effectiveness: float | None = None
    truth_quality: float | None = None
    total_tokens: int = 0
    tool_calls: int = 0
    turns: int = 0
    result_status: str


class PersonaHeartbeatFieldRisk(BaseModel):
    """Recent real-heartbeat risk surfaced into persona analytics."""

    session_id: str
    completed_at: str | None = None
    reliability: float | None = None
    issue_summary: str
    summary_oneliner: str | None = None
    critical: bool = False


class PersonaHeartbeatFieldReviewGate(BaseModel):
    """Aggregate field review decision for recent real heartbeats."""

    needs_review: bool = False
    reason_codes: list[str] = Field(default_factory=list)
    summary: str


class PersonaImprovementScheduleRisk(BaseModel):
    """Schedule-health risk surfaced into persona analytics."""

    kind: str
    summary: str
    detail: str | None = None
    critical: bool = False


class PersonaHeartbeatFieldSession(BaseModel):
    """Compact recent real-heartbeat summary."""

    session_id: str
    completed_at: str
    created_at: str
    status: str
    result_status: str
    summary_oneliner: str | None = None
    reliability: float
    effectiveness: float
    truth_quality: float
    total_tokens: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    tool_calls: int = 0
    turns: int = 0
    issue_codes: list[str] = Field(default_factory=list)
    issue_summary: str
    healthy: bool = False


class PersonaImprovementDashboardResponse(BaseModel):
    """Focused persona improvement dashboard response."""

    generated_at: str
    suite_id: str
    days: int
    schedule: PersonaImprovementScheduleResponse
    overview: PersonaImprovementOverview
    latest_lab_run: PersonaImprovementRecentRun | None = None
    field_overview: PersonaHeartbeatFieldOverview
    field_window_days: int
    field_window_lab_runs: int = 0
    field_review_gate: PersonaHeartbeatFieldReviewGate
    trend: list[PersonaImprovementTrendPoint] = Field(default_factory=list)
    field_trend: list[PersonaHeartbeatFieldTrendPoint] = Field(default_factory=list)
    recent_runs: list[PersonaImprovementRecentRun] = Field(default_factory=list)
    recent_heartbeats: list[PersonaHeartbeatFieldSession] = Field(default_factory=list)
    open_regressions: list[PersonaImprovementOpenRegression] = Field(default_factory=list)
    field_risks: list[PersonaHeartbeatFieldRisk] = Field(default_factory=list)
    schedule_risks: list[PersonaImprovementScheduleRisk] = Field(default_factory=list)


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
    """Search match metadata for jumping through persona history."""

    entry_id: str
    session_id: str
    entry_type: str
    timestamp: datetime
    snippet: str


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
