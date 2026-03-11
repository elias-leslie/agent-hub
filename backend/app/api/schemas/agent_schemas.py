"""Schemas for agent API endpoints."""

from typing import Any

from pydantic import BaseModel, Field

from app.services.agent_dto import AgentDTO


class ToolPermissionSchema(BaseModel):
    """Schema for a single tool permission."""

    name: str
    allowed: bool = True
    requires_confirmation: bool = False


class PermissionConfigSchema(BaseModel):
    """Schema for tool permission configuration.

    Matches PermissionConfig.to_dict() output format.
    """

    mode: str = Field(default="yolo", pattern=r"^(yolo|ask|granular)$")
    tool_permissions: dict[str, ToolPermissionSchema] = Field(default_factory=dict)
    allow_list: list[str] = Field(default_factory=list)
    deny_list: list[str] = Field(default_factory=list)


class AgentCreateRequest(BaseModel):
    """Request schema for creating an agent."""

    slug: str = Field(..., min_length=1, max_length=50, pattern=r"^[a-z0-9-]+$")
    name: str = Field(..., min_length=1, max_length=100)
    description: str | None = None
    system_prompt: str = Field(..., min_length=1)
    primary_model_id: str = Field(..., min_length=1)
    fallback_models: list[str] = Field(default_factory=list)
    escalation_model_id: str | None = None
    strategies: dict[str, Any] = Field(default_factory=dict)
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    thinking_level: str | None = Field(default=None, pattern="^(none|minimal|low|medium|high|xhigh)$")
    verbosity_level: str | None = Field(
        default=None, pattern="^(low|medium|high)$",
        description="Response verbosity (Codex/OpenAI Responses API only)",
    )
    is_active: bool = True
    is_coding_agent: bool = False
    tool_permissions: PermissionConfigSchema | None = None
    memory_config: dict[str, Any] | None = None
    max_concurrency: int | None = Field(default=None, ge=1, le=100, description="Max parallel executions")
    max_subagent_concurrency: int | None = Field(
        default=None, ge=1, le=100, description="Max parallel subagent spawns"
    )
    daily_token_budget: int | None = Field(default=None, ge=0, description="Max tokens per day (0=unlimited)")
    hourly_request_limit: int | None = Field(default=None, ge=0, description="Max requests per hour (0=unlimited)")
    timeout_seconds: float | None = Field(default=None, gt=0, le=600)


class AgentUpdateRequest(BaseModel):
    """Request schema for updating an agent."""

    name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = None
    system_prompt: str | None = Field(default=None, min_length=1)
    primary_model_id: str | None = Field(default=None, min_length=1)
    fallback_models: list[str] | None = None
    escalation_model_id: str | None = None
    strategies: dict[str, Any] | None = None
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    thinking_level: str | None = Field(default=None, pattern="^(none|minimal|low|medium|high|xhigh)$")
    verbosity_level: str | None = Field(
        default=None, pattern="^(low|medium|high)$",
        description="Response verbosity (Codex/OpenAI Responses API only)",
    )
    is_active: bool | None = None
    is_coding_agent: bool | None = None
    tool_permissions: PermissionConfigSchema | None = None
    memory_config: dict[str, Any] | None = None
    max_concurrency: int | None = Field(default=None, ge=1, le=100)
    max_subagent_concurrency: int | None = Field(default=None, ge=1, le=100)
    daily_token_budget: int | None = Field(default=None, ge=0)
    hourly_request_limit: int | None = Field(default=None, ge=0)
    timeout_seconds: float | None = Field(default=None, gt=0, le=600)
    change_reason: str | None = None


class AgentResponse(BaseModel):
    """Response schema for agent data."""

    id: int
    slug: str
    name: str
    description: str | None
    system_prompt: str
    primary_model_id: str
    fallback_models: list[str]
    escalation_model_id: str | None
    strategies: dict[str, Any]
    temperature: float
    thinking_level: str | None
    verbosity_level: str | None
    is_active: bool
    is_coding_agent: bool
    tool_permissions: dict[str, Any] | None
    memory_config: dict[str, Any] | None
    max_concurrency: int | None
    max_subagent_concurrency: int | None
    daily_token_budget: int | None
    hourly_request_limit: int | None
    timeout_seconds: float | None
    version: int
    created_at: str
    updated_at: str

    @classmethod
    def from_dto(cls, dto: AgentDTO) -> "AgentResponse":
        """Create response from DTO."""
        return cls(
            id=dto.id,
            slug=dto.slug,
            name=dto.name,
            description=dto.description,
            system_prompt=dto.system_prompt,
            primary_model_id=dto.primary_model_id,
            fallback_models=dto.fallback_models,
            escalation_model_id=dto.escalation_model_id,
            strategies=dto.strategies,
            temperature=dto.temperature,
            thinking_level=dto.thinking_level,
            verbosity_level=dto.verbosity_level,
            is_active=dto.is_active,
            is_coding_agent=dto.is_coding_agent,
            tool_permissions=dto.tool_permissions,
            memory_config=dto.memory_config,
            max_concurrency=dto.max_concurrency,
            max_subagent_concurrency=dto.max_subagent_concurrency,
            daily_token_budget=dto.daily_token_budget,
            hourly_request_limit=dto.hourly_request_limit,
            timeout_seconds=dto.timeout_seconds,
            version=dto.version,
            created_at=dto.created_at.isoformat(),
            updated_at=dto.updated_at.isoformat(),
        )


class AgentListResponse(BaseModel):
    """Response schema for agent list."""

    agents: list[AgentResponse]
    total: int


class AgentPreviewResponse(BaseModel):
    """Response schema for agent preview (combined prompt + memory)."""

    slug: str
    name: str
    combined_prompt: str
    mandate_count: int
    guardrail_count: int
    mandate_uuids: list[str]
    guardrail_uuids: list[str]


class AgentMetrics(BaseModel):
    """24h metrics for an agent."""

    slug: str
    requests_24h: int = 0
    avg_latency_ms: float = 0.0
    success_rate: float = 0.0
    tokens_24h: int = 0
    cost_24h_usd: float = 0.0
    # Sparkline data (last 24 hours, 1 point per hour)
    latency_trend: list[float] = Field(default_factory=list)
    success_trend: list[float] = Field(default_factory=list)


class AgentMetricsListResponse(BaseModel):
    """Response for agent metrics list."""

    metrics: dict[str, AgentMetrics]


class AgentBenchmarkOverview(BaseModel):
    """Top-level benchmark health summary for one agent."""

    total_runs: int = 0
    avg_score: float = 0.0
    pass_rate: float = 0.0
    open_regressions: int = 0
    latest_completed_at: str | None = None
    tracked_models: list[str] = Field(default_factory=list)


class AgentBenchmarkTrendPoint(BaseModel):
    """One benchmark trendline point."""

    run_id: str
    completed_at: str | None = None
    suite_id: str
    run_kind: str
    avg_score: float | None = None
    pass_rate: float | None = None
    attempts: int = 0
    prompt_version: str | None = None


class AgentBenchmarkRunSummary(BaseModel):
    """Recent benchmark run summary row."""

    run_id: str
    benchmark_id: str
    suite_id: str
    run_kind: str
    started_at: str
    completed_at: str | None = None
    avg_score: float | None = None
    pass_rate: float | None = None
    attempt_count: int = 0
    passed_attempt_count: int = 0
    infra_failure_count: int = 0
    models: list[str] = Field(default_factory=list)
    case_ids: list[str] = Field(default_factory=list)
    config_snapshot: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentRegressionClusterSummary(BaseModel):
    """Open or resolved regression cluster summary."""

    regression_key: str
    suite_id: str
    case_id: str
    failure_detail: str
    status: str
    occurrence_count: int = 0
    latest_avg_score: float | None = None
    affected_models: list[str] = Field(default_factory=list)
    opened_at: str | None = None
    last_seen_at: str | None = None
    resolved_at: str | None = None


class AgentBenchmarkModelSummary(BaseModel):
    """Aggregated model performance across persisted benchmark attempts."""

    model_id: str
    attempts: int = 0
    avg_score: float | None = None
    pass_rate: float = 0.0
    avg_latency_ms: float | None = None
    latest_completed_at: str | None = None


class AgentBenchmarkDashboard(BaseModel):
    """Repeatable benchmark, regression, and model tracking for one agent."""

    agent_slug: str
    overview: AgentBenchmarkOverview
    trend: list[AgentBenchmarkTrendPoint] = Field(default_factory=list)
    recent_runs: list[AgentBenchmarkRunSummary] = Field(default_factory=list)
    open_regressions: list[AgentRegressionClusterSummary] = Field(default_factory=list)
    model_performance: list[AgentBenchmarkModelSummary] = Field(default_factory=list)
