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
    is_active: bool = True
    is_coding_agent: bool = False
    tool_permissions: PermissionConfigSchema | None = None


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
    is_active: bool | None = None
    is_coding_agent: bool | None = None
    tool_permissions: PermissionConfigSchema | None = None
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
    is_active: bool
    is_coding_agent: bool
    tool_permissions: dict[str, Any] | None
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
            is_active=dto.is_active,
            is_coding_agent=dto.is_coding_agent,
            tool_permissions=dto.tool_permissions,
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
    success_rate: float = 100.0
    tokens_24h: int = 0
    cost_24h_usd: float = 0.0
    # Sparkline data (last 24 hours, 1 point per hour)
    latency_trend: list[float] = Field(default_factory=list)
    success_trend: list[float] = Field(default_factory=list)


class AgentMetricsListResponse(BaseModel):
    """Response for agent metrics list."""

    metrics: dict[str, AgentMetrics]
