"""Memory API schemas - Settings and Budget."""

from pydantic import BaseModel, Field


class SettingsResponse(BaseModel):
    """Response schema for memory settings."""

    enabled: bool = Field(..., description="Kill switch for memory injection (False = no memories)")
    budget_enabled: bool = Field(..., description="Budget enforcement toggle")
    total_budget: int = Field(..., description="Total token budget when budget_enabled=True")
    max_mandates: int = Field(0, description="Max mandates to inject (0 = unlimited)")
    max_guardrails: int = Field(0, description="Max guardrails to inject (0 = unlimited)")
    reference_index_enabled: bool = Field(
        True, description="Include TOON reference index for discoverability"
    )
    continuity_enabled: bool = Field(True, description="Include Recent Activity block")
    continuity_max_sessions: int = Field(5, description="Max sessions in Recent Activity")


class SettingsUpdateRequest(BaseModel):
    """Request schema for updating memory settings."""

    enabled: bool | None = Field(None, description="Kill switch for memory injection")
    budget_enabled: bool | None = Field(None, description="Budget enforcement toggle")
    total_budget: int | None = Field(None, ge=100, le=100000, description="Total token budget")
    max_mandates: int | None = Field(None, ge=0, le=100, description="Max mandates (0 = unlimited)")
    max_guardrails: int | None = Field(
        None, ge=0, le=100, description="Max guardrails (0 = unlimited)"
    )
    reference_index_enabled: bool | None = Field(None, description="Include TOON reference index")
    continuity_enabled: bool | None = Field(None, description="Include Recent Activity block")
    continuity_max_sessions: int | None = Field(
        None, ge=1, le=20, description="Max sessions in Recent Activity"
    )


class BudgetUsageResponse(BaseModel):
    """Response schema for budget usage statistics."""

    mandates_tokens: int = Field(..., description="Tokens used by mandates")
    guardrails_tokens: int = Field(..., description="Tokens used by guardrails")
    reference_tokens: int = Field(..., description="Tokens used by reference")
    continuity_tokens: int = Field(0, description="Tokens used by session continuity")
    total_tokens: int = Field(..., description="Total tokens used")
    total_budget: int = Field(..., description="Configured budget limit")
    remaining: int = Field(..., description="Tokens remaining in budget")
    hit_limit: bool = Field(..., description="Whether budget limit was reached")
    # Count fields for coverage tracking
    mandates_injected: int = Field(0, description="Number of mandates injected")
    mandates_total: int = Field(0, description="Total mandates in memory")
    guardrails_injected: int = Field(0, description="Number of guardrails injected")
    guardrails_total: int = Field(0, description="Total guardrails in memory")
    reference_injected: int = Field(0, description="Number of reference items injected")
    reference_total: int = Field(0, description="Total reference items in memory")
