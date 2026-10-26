"""Schemas for agent API endpoints."""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.services.agent_dto import AgentDTO
from app.services.memory.context_builder_settings import normalize_memory_config


class AgentMemoryConfig(BaseModel):
    """Per-agent memory routing and injection config."""

    model_config = ConfigDict(extra="allow")

    injection_enabled: bool | None = None
    project_index_enabled: bool | None = None
    tool_capabilities_enabled: bool | None = None
    include_mandates: bool | None = None
    include_guardrails: bool | None = None
    include_references: bool | None = None
    reference_index_enabled: bool | None = None
    continuity_enabled: bool | None = None
    continuity_max_sessions: int | None = Field(default=None, ge=1)
    audience_tags: list[str] | None = None
    exclude_tags: list[str] | None = None
    exclude_memory_uuids: list[str] | None = None
    consumer_profile: str | None = Field(
        default=None,
        description="Shared memory consumer profile fallback for runtime + preview surfaces.",
    )
    runtime_consumer_profile: str | None = Field(
        default=None,
        description="Runtime-only memory consumer profile override.",
    )
    preview_consumer_profile: str | None = Field(
        default=None,
        description="Preview-only memory consumer profile override.",
    )


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
    memory_config: AgentMemoryConfig | None = None
    max_concurrency: int | None = Field(default=None, ge=1, le=100, description="Max parallel executions")
    max_subagent_concurrency: int | None = Field(
        default=None, ge=1, le=100, description="Max parallel subagent spawns"
    )
    daily_token_budget: int | None = Field(default=None, ge=0, description="Max tokens per day (0=unlimited)")
    hourly_request_limit: int | None = Field(default=None, ge=0, description="Max requests per hour (0=unlimited)")


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
    memory_config: AgentMemoryConfig | None = None
    max_concurrency: int | None = Field(default=None, ge=1, le=100)
    max_subagent_concurrency: int | None = Field(default=None, ge=1, le=100)
    daily_token_budget: int | None = Field(default=None, ge=0)
    hourly_request_limit: int | None = Field(default=None, ge=0)
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
    memory_config: dict[str, Any] | None
    effective_memory_config: dict[str, Any]
    max_concurrency: int | None
    max_subagent_concurrency: int | None
    daily_token_budget: int | None
    hourly_request_limit: int | None
    version: int
    created_at: str
    updated_at: str

    @classmethod
    def from_dto(
        cls,
        dto: AgentDTO,
        *,
        effective_memory_config: dict[str, Any],
    ) -> "AgentResponse":
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
            memory_config=normalize_memory_config(dto.memory_config),
            effective_memory_config=effective_memory_config,
            max_concurrency=dto.max_concurrency,
            max_subagent_concurrency=dto.max_subagent_concurrency,
            daily_token_budget=dto.daily_token_budget,
            hourly_request_limit=dto.hourly_request_limit,
            version=dto.version,
            created_at=dto.created_at.isoformat(),
            updated_at=dto.updated_at.isoformat(),
        )


class AgentListResponse(BaseModel):
    """Response schema for agent list."""

    agents: list[AgentResponse]
    total: int


class AgentPreviewSection(BaseModel):
    """One ordered section in the assembled runtime preview."""

    label: str
    source_kind: str
    source_id: str
    placement: str = "system"
    role: str | None = None
    priority: int | None = None
    updated_at: str | None = None
    content_hash: str
    chars: int
    estimated_tokens: int
    duplicate_of: str | None = None
    content: str


class AgentPreviewResponse(BaseModel):
    """Response schema for agent preview (combined prompt + memory)."""

    slug: str
    name: str
    combined_prompt: str
    full_context: str
    memory_query: str = ""
    memory_debug: dict[str, Any] = Field(default_factory=dict)
    loaded_memory_uuids: list[str] = Field(default_factory=list)
    reference_uuids: list[str] = Field(default_factory=list)
    reference_index_uuids: list[str] = Field(default_factory=list)
    mandate_count: int
    guardrail_count: int
    mandate_uuids: list[str]
    guardrail_uuids: list[str]
    task_type: str | None = None
    phase: str | None = None
    project_id: str | None = None
    task_prompt: str | None = None
    sections: list[AgentPreviewSection] = Field(default_factory=list)
    prompt_budget: dict[str, Any] = Field(default_factory=dict)
    full_context_estimated_tokens: int = 0
    canonical_context: dict[str, Any] | None = Field(
        default=None, description="Public canonical delivery identity, version, hash, and source metadata"
    )


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
