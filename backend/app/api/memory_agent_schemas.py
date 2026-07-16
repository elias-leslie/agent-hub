"""Pydantic schemas for memory agent tools endpoints."""

from typing import Any, Literal

from pydantic import BaseModel, Field

from app.services.memory.memory_models import (
    InjectionTier,
    MemoryApplicability,
    MemoryContextKind,
)

from .memory_schemas import BudgetUsageResponse


class ProgressiveContextBlock(BaseModel):
    """A single block of progressive context."""

    items: list[str] = Field(..., description="List of memory items in this block")
    count: int = Field(..., description="Number of items")


class ScoringBreakdown(BaseModel):
    """Scoring breakdown for a single memory item."""

    uuid: str = Field(..., description="Memory UUID (first 8 chars)")
    score: float = Field(..., description="Final score after multipliers")
    semantic: float = Field(..., description="Semantic similarity component")
    content_preview: str = Field(..., description="First 60 chars of content")


class ProgressiveContextFailure(BaseModel):
    """Failure details for fail-closed progressive-context delivery."""

    operation: str = Field(..., description="Failed operation name")
    attempts: int = Field(..., description="Number of attempts performed")
    error_type: str = Field(..., description="Exception type from the final failure")
    error_message: str = Field(..., description="Final error message")
    latency_ms: int = Field(..., description="End-to-end latency across all attempts")


class ProgressiveContextResponse(BaseModel):
    """Response with 3-block progressive disclosure context."""

    mandates: ProgressiveContextBlock = Field(..., description="Always-inject golden standards")
    guardrails: ProgressiveContextBlock = Field(..., description="Type-filtered anti-patterns")
    reference: ProgressiveContextBlock = Field(..., description="Semantic search patterns")
    total_tokens: int = Field(..., description="Estimated total tokens")
    formatted: str = Field(..., description="Pre-formatted context for injection")
    variant: str = Field(..., description="A/B variant used for this request")
    debug: dict[str, Any] | None = Field(None, description="Debug info when debug=True")
    scoring_breakdown: list[ScoringBreakdown] | None = Field(
        None, description="Scoring breakdown when debug=True"
    )
    budget_usage: BudgetUsageResponse | None = Field(
        None, description="Token budget usage tracking"
    )
    status: str = Field("ok", description="Delivery status: ok or failed")
    failure: ProgressiveContextFailure | None = Field(
        None, description="Failure details when delivery fails closed"
    )
    attempts: int = Field(1, description="Number of attempts used for this response")
    latency_ms: int = Field(0, description="End-to-end response latency in milliseconds")
    canonical_context: dict[str, Any] | None = Field(
        None,
        description="Version/hash/block identity from the canonical delivery contract",
    )


class CanonicalContextRequest(BaseModel):
    """Request for canonical context retrieval."""

    query: str = Field(..., description="Query to find relevant context")
    max_facts: int = Field(10, ge=1, le=50, description="Maximum facts to return")
    include_provisional: bool = Field(False, description="Whether to include provisional learnings")


class CanonicalContextResponse(BaseModel):
    """Response with canonical context."""

    facts: list[str]
    count: int


class SaveLearningRequest(BaseModel):
    """Request to save a learning from a session."""

    content: str = Field(..., description="The learning content")
    summary: str = Field(
        ..., description="REQUIRED: Short action phrase (~20 chars) for TOON index"
    )
    injection_tier: InjectionTier = Field(
        InjectionTier.REFERENCE,
        description="Injection tier (mandate, guardrail, reference, archive)",
    )
    confidence: int = Field(
        80,
        ge=0,
        le=100,
        description="Confidence level (0-100). 70+ is provisional, 90+ is canonical.",
    )
    context: str | None = Field(None, description="Optional context about the learning source")
    pinned: bool = Field(
        False,
        description=(
            "Pin episode (always include when memory and this episode's category are enabled, "
            "regardless of budget)"
        ),
    )
    trigger_task_types: list[str] | None = Field(
        None, description="Task types that trigger this reference (e.g., ['database', 'memory'])"
    )
    trigger_phases: list[str] | None = Field(
        None, description="Subtask phases that trigger this memory"
    )
    context_kind: MemoryContextKind | None = Field(
        None,
        description="Semantic channel for this memory (policy, reference, capability, continuity, signal)",
    )
    applicability: MemoryApplicability | None = Field(
        None,
        description="Audience targeting rules for this memory",
    )
    render_mode: Literal["full", "compact", "summary"] | None = Field(
        None,
        description=(
            "Per-memory render expansion preference. 'full'/'compact'/'summary' force "
            "the corresponding tier across all profiles; null = auto."
        ),
    )
    change_reason: str | None = Field(None, description="Why this learning is being recorded")
    bypass_compactness: bool = Field(
        False,
        description=(
            "Override: skip the strict-Caveman compactness gate. Use only when one "
            "combined memory is more token-efficient than splitting into atomic rules."
        ),
    )


class SaveLearningResponse(BaseModel):
    """Response from save_learning endpoint."""

    uuid: str | None = Field(None, description="UUID of the created learning")
    status: str = Field(..., description="provisional or canonical based on confidence")
    is_duplicate: bool = Field(False, description="True if similar learning exists")
    reinforced_uuid: str | None = Field(
        None, description="UUID of reinforced learning if duplicate"
    )
    message: str
