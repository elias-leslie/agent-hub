"""Feedback API schemas - Request/Response models."""

from datetime import datetime

from pydantic import BaseModel, Field, field_validator


class FeedbackOccurrenceFields(BaseModel):
    """Caller supplies one stable identity per observation, reused for retries/relays.

    References must point to sanitized evidence; raw logs and secrets do not belong here.
    Distinct run references expose breadth, rather than attesting independence.
    """
    occurrence_id: str | None = Field(default=None, min_length=1, max_length=160)
    source_project_id: str | None = Field(default=None, max_length=50)
    run_ref: str | None = Field(default=None, max_length=200)
    role: str | None = Field(default=None, max_length=100)
    occurred_at: datetime | None = None
    consequence: str | None = Field(default=None, max_length=4000)
    workaround: str | None = Field(default=None, max_length=4000)
    evidence_refs: list[str] = Field(default_factory=list, max_length=50)

    @field_validator("occurrence_id", "source_project_id", "run_ref", "role")
    @classmethod
    def nonblank_identity(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("Identity fields cannot be blank")
        return value

    @field_validator("occurred_at")
    @classmethod
    def aware_timestamp(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("occurred_at must include a timezone")
        return value

    @field_validator("evidence_refs")
    @classmethod
    def bounded_references(cls, value: list[str]) -> list[str]:
        if any(not ref.strip() or len(ref) > 500 for ref in value):
            raise ValueError("Evidence references must be nonblank and at most 500 characters")
        return value


class FeedbackItemCreate(FeedbackOccurrenceFields):
    """Request body for creating a feedback item."""

    component_id: str = Field(..., description="Component ID (e.g. 'sf.cli', 'ah.memory')")
    feedback_type: str = Field(
        ..., description="Type: friction, idea, improvement, praise"
    )
    title: str = Field(..., max_length=200, description="Short descriptive title")

    @field_validator("title")
    @classmethod
    def title_not_placeholder(cls, v: str) -> str:
        stripped = v.strip().strip(".")
        if not stripped or len(stripped) < 3:
            raise ValueError("Title must be descriptive (at least 3 non-dot characters)")
        return v
    description: str | None = Field(
        default=None, description="Detailed description of the feedback"
    )
    severity: str | None = Field(
        default=None, description="Severity for friction: low, medium, high"
    )
    project_id: str = Field(..., description="Project this feedback relates to")
    session_id: str | None = Field(
        default=None, description="Session that created this feedback"
    )
    agent_slug: str | None = Field(default=None, description="Agent that reported this")
    model_used: str | None = Field(default=None, description="Model used by the agent")
    session_type: str | None = Field(default=None, description="Session type")
    vote_if_duplicate: bool = Field(
        default=False,
        description="Vote on the strongest duplicate match instead of creating a new row",
    )


class FeedbackVoteCreate(FeedbackOccurrenceFields):
    """Request body for voting on a feedback item."""

    session_id: str | None = Field(default=None, description="Optional session attribution")
    comment: str | None = Field(
        default=None, description="Optional 'me too' context"
    )
    agent_slug: str | None = Field(default=None, description="Agent casting the vote")
    model_used: str | None = Field(default=None, description="Model used by the agent")


class FeedbackStatusUpdate(BaseModel):
    """Request body for updating feedback item status."""

    status: str | None = Field(
        default=None, description="New status: open, acknowledged, resolved, wont_fix, archived"
    )
    resolution_note: str | None = Field(
        default=None, description="Note explaining the resolution"
    )
    linked_task_id: str | None = Field(
        default=None, description="SummitFlow task ID linked to this feedback"
    )


class FeedbackVoteResponse(BaseModel):
    """Response for a single vote."""

    id: str
    feedback_item_id: str
    occurrence_id: str
    source_project_id: str | None
    run_ref: str | None
    role: str | None
    occurred_at: datetime
    consequence: str | None
    workaround: str | None
    evidence_refs: list[str]
    source_kind: str
    session_id: str | None
    comment: str | None
    agent_slug: str | None
    model_used: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class FeedbackItemResponse(BaseModel):
    """Response for a single feedback item."""

    id: str
    component_id: str
    feedback_type: str
    title: str
    description: str | None
    severity: str | None
    status: str
    project_id: str
    created_by_session_id: str | None
    agent_slug: str | None
    model_used: str | None
    session_type: str | None
    resolved_at: datetime | None
    resolution_note: str | None
    vote_count: int
    occurrence_count: int
    independent_run_count: int
    affected_roles: list[str]
    affected_projects: list[str]
    last_seen_at: datetime
    linked_task_id: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class FeedbackItemWithVotes(FeedbackItemResponse):
    """Feedback item with its votes included."""

    votes: list[FeedbackVoteResponse] = Field(default_factory=list)
    occurrences: list[FeedbackVoteResponse] = Field(default_factory=list)


class FeedbackCreateResponse(BaseModel):
    """Response for creating a feedback item, includes dedup candidates."""

    item: FeedbackItemResponse
    occurrence_id: str | None = None
    created: bool = Field(description="True if new item created")
    duplicate_candidates: list[FeedbackItemResponse] = Field(
        default_factory=list,
        description="Similar existing open items — caller should search and vote instead of creating duplicates",
    )
    voted: bool = Field(
        default=False,
        description="True when the request voted on an existing duplicate instead of creating a new item",
    )


class FeedbackOccurrenceReference(BaseModel):
    """Compact canonical reference used to reconcile one retained occurrence."""

    feedback_item_id: str
    occurrence_id: str
    run_ref: str
    role: str | None
    source_project_id: str | None
    component_id: str
    feedback_type: str
    status: str
    title: str
    occurred_at: datetime
    item_updated_at: datetime


class FeedbackOccurrenceReferenceList(BaseModel):
    """Bounded references for exact run identities; never a feedback event feed."""

    references: list[FeedbackOccurrenceReference]
    count: int


class FeedbackMergeRequest(BaseModel):
    """Request body for merging a duplicate feedback item into a canonical item."""

    target_item_id: str = Field(..., description="Canonical feedback item ID or prefix")


class FeedbackListResponse(BaseModel):
    """Response for listing feedback items."""

    items: list[FeedbackItemResponse]
    total: int = Field(description="Total items matching filters (for pagination)")


class FeedbackSummaryResponse(BaseModel):
    """Aggregated feedback summary."""

    total_items: int
    counts_by_type_status: list[dict]
    top_unresolved: list[dict]
    by_component: list[dict]


class ComponentFeedbackResponse(BaseModel):
    """Per-component feedback view."""

    component_id: str
    stats: dict
    items: list[FeedbackItemResponse]
