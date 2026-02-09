"""Schema models for agent memory tools.

Request and response models for recording learnings during execution.
"""

from pydantic import BaseModel, Field

from .service import MemoryCategory, MemoryScope, MemorySearchResult


class RecordDiscoveryRequest(BaseModel):
    """Request to record a codebase discovery."""

    file_path: str = Field(..., description="File path where discovery was made")
    description: str = Field(..., description="Description of the discovery")
    category: MemoryCategory = Field(
        default=MemoryCategory.REFERENCE,
        description="Category of the discovery (mandate, guardrail, reference)",
    )
    scope: MemoryScope = Field(
        default=MemoryScope.PROJECT,
        description="Scope for this discovery",
    )
    scope_id: str | None = Field(
        default=None,
        description="Project or task ID for scoping",
    )


class RecordGotchaRequest(BaseModel):
    """Request to record a gotcha/pitfall."""

    gotcha: str = Field(..., description="The gotcha or pitfall encountered")
    context: str = Field(..., description="Context in which the gotcha was found")
    solution: str | None = Field(
        default=None,
        description="Solution or workaround if known",
    )
    scope: MemoryScope = Field(
        default=MemoryScope.PROJECT,
        description="Scope for this gotcha",
    )
    scope_id: str | None = Field(
        default=None,
        description="Project or task ID for scoping",
    )


class RecordPatternRequest(BaseModel):
    """Request to record a coding pattern."""

    pattern: str = Field(..., description="Description of the pattern")
    applies_to: str = Field(..., description="Where/when this pattern applies")
    example: str | None = Field(
        default=None,
        description="Example of the pattern in use",
    )
    scope: MemoryScope = Field(
        default=MemoryScope.PROJECT,
        description="Scope for this pattern",
    )
    scope_id: str | None = Field(
        default=None,
        description="Project or task ID for scoping",
    )


class RecordResponse(BaseModel):
    """Response from a record operation."""

    success: bool
    episode_uuid: str
    message: str


class SessionContextResponse(BaseModel):
    """Response containing accumulated session context."""

    discoveries: list[MemorySearchResult] = []
    gotchas: list[MemorySearchResult] = []
    patterns: list[MemorySearchResult] = []
    session_count: int = 0
