"""Persona improvement dashboard schemas."""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.api.persona.schema_automations import PersonaImprovementScheduleResponse


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
