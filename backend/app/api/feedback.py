"""Feedback API - Store and retrieve user feedback on AI responses."""

import logging
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.services.memory import track_success_batch
from app.storage.feedback import (
    get_feedback_by_message_async,
    get_feedback_stats_async,
    store_feedback_async,
)

logger = logging.getLogger(__name__)

router = APIRouter()


# Valid feedback categories
VALID_CATEGORIES = {"incorrect", "unhelpful", "incomplete", "offensive", "other"}


# Request/Response schemas
class FeedbackCreate(BaseModel):
    """Request body for creating feedback."""

    message_id: str = Field(..., min_length=1, description="Message ID from client")
    session_id: str | None = Field(None, description="Optional session ID")
    feedback_type: str = Field(
        ..., pattern="^(positive|negative)$", description="positive or negative"
    )
    category: str | None = Field(None, description="Category for negative feedback")
    details: str | None = Field(None, max_length=500, description="Optional text details")
    memory_uuids: str | None = Field(
        None,
        description="Comma-separated memory rule UUIDs from completion response (for attribution)",
    )


class FeedbackResponse(BaseModel):
    """Response body for feedback operations."""

    id: int
    message_id: str
    session_id: str | None
    feedback_type: str
    category: str | None
    details: str | None
    referenced_rule_uuids: list[str] | None
    created_at: datetime


class FeedbackStatsResponse(BaseModel):
    """Response body for feedback statistics."""

    total_feedback: int
    positive_count: int
    negative_count: int
    positive_rate: float
    categories: dict[str, int]


@router.post("/feedback", response_model=FeedbackResponse, status_code=201)
async def create_feedback(
    request: FeedbackCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> FeedbackResponse:
    """Store user feedback for a message.

    For positive feedback with memory_uuids, also increments success_count
    for the referenced memory rules.
    """
    if request.category and request.category not in VALID_CATEGORIES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid category. Must be one of: {', '.join(VALID_CATEGORIES)}",
        )

    # Parse memory UUIDs from comma-separated string
    rule_uuids: list[str] | None = None
    if request.memory_uuids:
        rule_uuids = [uuid.strip() for uuid in request.memory_uuids.split(",") if uuid.strip()]

    feedback = await store_feedback_async(
        db,
        message_id=request.message_id,
        feedback_type=request.feedback_type,
        session_id=request.session_id,
        category=request.category,
        details=request.details,
        referenced_rule_uuids=rule_uuids,
    )

    # On positive feedback, increment success_count for referenced rules
    if request.feedback_type == "positive" and rule_uuids:
        try:
            await track_success_batch(rule_uuids)
            logger.info(f"Tracked success for {len(rule_uuids)} memory rules")
        except Exception as e:
            logger.warning(f"Failed to track success for memory rules: {e}")

    return FeedbackResponse(
        id=feedback.id,
        message_id=feedback.message_id,
        session_id=feedback.session_id,
        feedback_type=feedback.feedback_type,
        category=feedback.category,
        details=feedback.details,
        referenced_rule_uuids=feedback.referenced_rule_uuids,
        created_at=feedback.created_at,
    )


@router.get("/feedback/message/{message_id}", response_model=FeedbackResponse)
async def get_feedback(
    message_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> FeedbackResponse:
    """Get feedback for a specific message."""
    feedback = await get_feedback_by_message_async(db, message_id)
    if not feedback:
        raise HTTPException(status_code=404, detail="Feedback not found")

    return FeedbackResponse(
        id=feedback.id,
        message_id=feedback.message_id,
        session_id=feedback.session_id,
        feedback_type=feedback.feedback_type,
        category=feedback.category,
        details=feedback.details,
        referenced_rule_uuids=feedback.referenced_rule_uuids,
        created_at=feedback.created_at,
    )


@router.get("/feedback/stats", response_model=FeedbackStatsResponse)
async def get_stats(
    db: Annotated[AsyncSession, Depends(get_db)],
    session_id: Annotated[str | None, Query(description="Filter by session")] = None,
    days: Annotated[int | None, Query(description="Number of days to look back")] = None,
) -> FeedbackStatsResponse:
    """Get aggregated feedback statistics."""
    stats = await get_feedback_stats_async(db, session_id=session_id, days=days)

    return FeedbackStatsResponse(
        total_feedback=stats["total_feedback"],
        positive_count=stats["positive_count"],
        negative_count=stats["negative_count"],
        positive_rate=stats["positive_rate"],
        categories=stats["categories"],
    )
