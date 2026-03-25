"""Schemas for the Arena system overview surface."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ArenaScheduledJobSummary(BaseModel):
    id: str
    name: str
    payload_type: str
    enabled: bool
    last_run_at: str | None = None
    next_run_at: str | None = None
    run_count: int = 0


class ArenaAgentSignalVolume(BaseModel):
    agent_slug: str
    friction: int = 0
    improvement: int = 0
    idea: int = 0
    praise: int = 0
    system: int = 0


class ArenaRepeatedIssue(BaseModel):
    agent_slug: str
    feedback_type: str | None = None
    content: str
    count: int
    latest_at: str | None = None


class ArenaBenchmarkExperimentSignal(BaseModel):
    suite_id: str
    decision: str
    decision_reason: str | None = None
    score_delta: float = 0.0
    pass_rate_delta: float = 0.0


class ArenaOpenRegressionSignal(BaseModel):
    case_id: str
    occurrence_count: int
    failure_detail: str
    failure_kind: str | None = None
    failure_category: str | None = None
    last_seen_at: str | None = None


class ArenaMemoryUtilizationSummary(BaseModel):
    injection_sessions: int = 0
    citation_sessions: int = 0
    lookup_after_injection_sessions: int = 0
    citation_session_rate: float = 0.0
    assistant_citation_rate: float = 0.0
    selected_reference_citation_rate: float = 0.0
    memory_search_calls: int = 0
    memory_get_calls: int = 0
    memory_debug_coverage_rate: float = 0.0


class ArenaMemoryGovernanceIssueSample(BaseModel):
    uuid: str
    label: str
    details: str | None = None
    load_count: int = 0
    invalid_types: list[str] = Field(default_factory=list)


class ArenaMemoryGovernanceSummary(BaseModel):
    active_count: int = 0
    active_agent_count: int = 0
    health_status: str = "healthy"
    by_context_kind: dict[str, int] = Field(default_factory=dict)
    targeted_count: int = 0
    explicit_exclusion_count: int = 0
    untargeted_reference_count: int = 0
    untargeted_reference_samples: list[ArenaMemoryGovernanceIssueSample] = Field(
        default_factory=list
    )
    policy_with_targeting_count: int = 0
    missing_reference_summary_count: int = 0
    missing_capability_summary_count: int = 0
    oversized_policy_count: int = 0
    oversized_policy_samples: list[ArenaMemoryGovernanceIssueSample] = Field(
        default_factory=list
    )
    alias_trigger_task_type_count: int = 0
    startup_profile_agent_target_count: int = 0
    startup_profile_agent_target_samples: list[ArenaMemoryGovernanceIssueSample] = Field(
        default_factory=list
    )
    invalid_trigger_task_type_count: int = 0
    invalid_trigger_task_type_samples: list[ArenaMemoryGovernanceIssueSample] = Field(
        default_factory=list
    )
    custom_memory_config_agent_count: int = 0
    project_index_disabled_agent_count: int = 0
    tool_capabilities_disabled_agent_count: int = 0
    reference_index_disabled_agent_count: int = 0
    memory_exclusion_agent_count: int = 0
    excluded_memory_uuid_count: int = 0
    hard_issue_count: int = 0
    soft_issue_count: int = 0
    soft_limit_breach_count: int = 0
    issue_count: int = 0


class ArenaReferenceYieldSummary(BaseModel):
    uuid: str
    label: str
    selected: int
    cited: int
    citation_rate: float
    tags: list[str] = Field(default_factory=list)


class ArenaAgentBenchmarkSummary(BaseModel):
    total_runs: int = 0
    avg_score: float | None = None
    pass_rate: float | None = None
    open_regressions: int = 0
    latest_completed_at: str | None = None


class ArenaAgentSummary(BaseModel):
    slug: str
    name: str
    description: str | None = None
    benchmark: ArenaAgentBenchmarkSummary
    signal_volume: ArenaAgentSignalVolume | None = None
    top_issue: ArenaRepeatedIssue | None = None


class ArenaSystemSummary(BaseModel):
    total_agents: int = 0
    agents_with_history: int = 0
    total_runs: int = 0
    avg_score: float | None = None
    avg_pass_rate: float | None = None
    total_regressions: int = 0
    regressions_by_category: dict[str, int] = {}


class ArenaOverviewResponse(BaseModel):
    generated_at: str
    project_id: str | None = None
    primary_agent_slug: str
    days: int
    system: ArenaSystemSummary
    scheduled_jobs: list[ArenaScheduledJobSummary] = Field(default_factory=list)
    agent_signal_volume: list[ArenaAgentSignalVolume] = Field(default_factory=list)
    repeated_issues: list[ArenaRepeatedIssue] = Field(default_factory=list)
    recent_benchmark_experiments: list[ArenaBenchmarkExperimentSignal] = Field(default_factory=list)
    open_regression_clusters: list[ArenaOpenRegressionSignal] = Field(default_factory=list)
    memory_utilization: ArenaMemoryUtilizationSummary
    memory_governance: ArenaMemoryGovernanceSummary
    low_yield_references: list[ArenaReferenceYieldSummary] = Field(default_factory=list)
    agents: list[ArenaAgentSummary] = Field(default_factory=list)
