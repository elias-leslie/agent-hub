"""Validation helpers and shared utilities for feedback API endpoints."""

import logging

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.services import feedback_storage
from app.services.memory.scorecard_component_map import is_valid_component_id

logger = logging.getLogger(__name__)

VALID_FEEDBACK_TYPES = {"friction", "idea", "improvement", "praise"}
VALID_STATUSES = {"open", "acknowledged", "resolved", "wont_fix", "archived"}
VALID_FILTER_STATUSES = VALID_STATUSES | {"active"}
VALID_SEVERITIES = {"low", "medium", "high"}
VALID_SORT_OPTIONS = {"votes", "newest", "oldest"}

HIGH_VOTE_THRESHOLD = 5


async def resolve_item(db: AsyncSession, item_id: str) -> str:
    """Resolve a full or prefix ID, raising HTTPException on not-found or ambiguity."""
    try:
        full_id = await feedback_storage.resolve_feedback_id(db, item_id)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    if not full_id:
        raise HTTPException(status_code=404, detail="Feedback item not found")
    return full_id


def validate_feedback_type(feedback_type: str) -> None:
    if feedback_type not in VALID_FEEDBACK_TYPES:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid feedback_type '{feedback_type}'. Valid: {', '.join(sorted(VALID_FEEDBACK_TYPES))}",
        )


def validate_component_id(component_id: str) -> None:
    if is_valid_component_id(component_id):
        return
    from app.services.memory.scorecard_component_map import get_all_component_ids

    all_ids = get_all_component_ids()
    suggestions = [cid for cid in all_ids if cid.startswith(component_id.split(".")[0] + ".")]
    detail = f"Unknown component '{component_id}'."
    if suggestions:
        detail += f" Did you mean: {', '.join(suggestions[:5])}?"
    else:
        detail += f" Valid components: {', '.join(all_ids[:10])}..."
    raise HTTPException(status_code=422, detail=detail)


def validate_severity(severity: str | None) -> None:
    if severity and severity not in VALID_SEVERITIES:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid severity '{severity}'. Valid: low, medium, high",
        )


def validate_list_params(feedback_type: str | None, status: str | None, sort: str) -> None:
    if feedback_type and feedback_type not in VALID_FEEDBACK_TYPES:
        raise HTTPException(status_code=422, detail=f"Invalid feedback_type '{feedback_type}'")
    if status and status not in VALID_FILTER_STATUSES:
        raise HTTPException(status_code=422, detail=f"Invalid status '{status}'")
    if sort not in VALID_SORT_OPTIONS:
        raise HTTPException(status_code=422, detail=f"Invalid sort '{sort}'")


def log_vote_threshold(item_id: str, item: object) -> None:
    """Log when a feedback item crosses the high-vote threshold."""
    logger.info(
        "Feedback item crossed vote threshold",
        extra={
            "item_id": item_id,
            "vote_count": getattr(item, "vote_count", None),
            "component_id": getattr(item, "component_id", None),
            "feedback_type": getattr(item, "feedback_type", None),
            "title": getattr(item, "title", None),
            "threshold": HIGH_VOTE_THRESHOLD,
        },
    )
