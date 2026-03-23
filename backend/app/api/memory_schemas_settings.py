"""Memory API schemas - Settings and Budget."""

from pydantic import BaseModel, Field

from app.services.memory.variants import MemoryVariant


class SettingsResponse(BaseModel):
    """Response schema for memory settings."""

    enabled: bool = Field(..., description="Kill switch for memory injection (False = no memories)")
    continuity_enabled: bool = Field(True, description="Include Recent Activity block")
    continuity_max_sessions: int = Field(5, description="Max sessions in Recent Activity")
    active_variant: MemoryVariant | None = Field(
        None,
        description="Production default memory variant (null falls back to deterministic assignment)",
    )


class SettingsUpdateRequest(BaseModel):
    """Request schema for updating memory settings."""

    enabled: bool | None = Field(None, description="Kill switch for memory injection")
    continuity_enabled: bool | None = Field(None, description="Include Recent Activity block")
    continuity_max_sessions: int | None = Field(
        None, ge=1, le=20, description="Max sessions in Recent Activity"
    )
    active_variant: MemoryVariant | None = Field(
        None,
        description="Production default memory variant. Send null to clear.",
    )


class BudgetUsageResponse(BaseModel):
    """Response schema for rendered memory usage statistics."""

    mandates_tokens: int = Field(..., description="Tokens used by mandates")
    guardrails_tokens: int = Field(..., description="Tokens used by guardrails")
    reference_tokens: int = Field(..., description="Tokens used by reference")
    continuity_tokens: int = Field(0, description="Tokens used by session continuity")
    total_tokens: int = Field(..., description="Total tokens used")
    # Count fields for coverage tracking
    mandates_injected: int = Field(0, description="Number of mandates injected")
    mandates_total: int = Field(0, description="Total mandates in memory")
    guardrails_injected: int = Field(0, description="Number of guardrails injected")
    guardrails_total: int = Field(0, description="Total guardrails in memory")
    reference_injected: int = Field(0, description="Number of reference items injected")
    reference_total: int = Field(0, description="Total reference items in memory")
