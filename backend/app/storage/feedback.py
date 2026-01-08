"""Storage functions for message feedback."""

from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import MessageFeedback


async def store_feedback_async(
    db: AsyncSession,
    message_id: str,
    feedback_type: str,
    session_id: Optional[str] = None,
    category: Optional[str] = None,
    details: Optional[str] = None,
) -> MessageFeedback:
    """Store user feedback for a message."""
    # Check if feedback already exists for this message
    existing = await get_feedback_by_message_async(db, message_id)
    if existing:
        # Update existing feedback
        existing.feedback_type = feedback_type
        existing.category = category
        existing.details = details
        await db.commit()
        await db.refresh(existing)
        return existing

    feedback = MessageFeedback(
        message_id=message_id,
        session_id=session_id,
        feedback_type=feedback_type,
        category=category,
        details=details,
    )
    db.add(feedback)
    await db.commit()
    await db.refresh(feedback)
    return feedback


async def get_feedback_by_message_async(
    db: AsyncSession,
    message_id: str,
) -> Optional[MessageFeedback]:
    """Get feedback for a specific message."""
    result = await db.execute(
        select(MessageFeedback).where(MessageFeedback.message_id == message_id)
    )
    return result.scalar_one_or_none()


async def get_feedback_stats_async(
    db: AsyncSession,
    session_id: Optional[str] = None,
    days: Optional[int] = None,
) -> dict:
    """Get aggregated feedback statistics."""
    query = select(MessageFeedback)

    if session_id:
        query = query.where(MessageFeedback.session_id == session_id)

    if days:
        cutoff = datetime.utcnow() - timedelta(days=days)
        query = query.where(MessageFeedback.created_at >= cutoff)

    result = await db.execute(query)
    feedbacks = result.scalars().all()

    total = len(feedbacks)
    positive_count = sum(1 for f in feedbacks if f.feedback_type == "positive")
    negative_count = sum(1 for f in feedbacks if f.feedback_type == "negative")

    # Count categories for negative feedback
    categories: dict[str, int] = {}
    for f in feedbacks:
        if f.category:
            categories[f.category] = categories.get(f.category, 0) + 1

    return {
        "total_feedback": total,
        "positive_count": positive_count,
        "negative_count": negative_count,
        "positive_rate": positive_count / total if total > 0 else 0.0,
        "categories": categories,
    }


async def list_feedback_async(
    db: AsyncSession,
    session_id: Optional[str] = None,
    feedback_type: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
) -> list[MessageFeedback]:
    """List feedback with optional filters."""
    query = select(MessageFeedback).order_by(MessageFeedback.created_at.desc())

    if session_id:
        query = query.where(MessageFeedback.session_id == session_id)

    if feedback_type:
        query = query.where(MessageFeedback.feedback_type == feedback_type)

    query = query.limit(limit).offset(offset)
    result = await db.execute(query)
    return list(result.scalars().all())
