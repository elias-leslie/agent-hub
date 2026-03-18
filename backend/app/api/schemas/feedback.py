"""Feedback API schemas - Request/Response models."""

from datetime import datetime

from pydantic import BaseModel, Field, field_validator


class FeedbackItemCreate(BaseModel):
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


class FeedbackVoteCreate(BaseModel):
    """Request body for voting on a feedback item."""

    session_id: str = Field(..., description="Session casting the vote")
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
    session_id: str
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
    linked_task_id: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class FeedbackItemWithVotes(FeedbackItemResponse):
    """Feedback item with its votes included."""

    votes: list[FeedbackVoteResponse] = []


class FeedbackCreateResponse(BaseModel):
    """Response for creating a feedback item, includes dedup candidates."""

    item: FeedbackItemResponse
    created: bool = Field(description="True if new item created")
    duplicate_candidates: list[FeedbackItemResponse] = Field(
        default_factory=list,
        description="Similar existing open items — caller should search and vote instead of creating duplicates",
    )
    voted: bool = Field(
        default=False,
        description="True when the request voted on an existing duplicate instead of creating a new item",
    )


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
