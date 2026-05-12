"""Feedback API endpoints for agent-sourced issues, ideas, and voting."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.feedback._validators import (
    HIGH_VOTE_THRESHOLD,
    VALID_STATUSES,
    log_vote_threshold,
    resolve_item,
    validate_component_id,
    validate_feedback_type,
    validate_list_params,
    validate_severity,
)
from app.api.schemas.feedback import (
    ComponentFeedbackResponse,
    FeedbackCreateResponse,
    FeedbackItemCreate,
    FeedbackItemResponse,
    FeedbackItemWithVotes,
    FeedbackListResponse,
    FeedbackMergeRequest,
    FeedbackStatusUpdate,
    FeedbackSummaryResponse,
    FeedbackVoteCreate,
    FeedbackVoteResponse,
)
from app.db import get_db
from app.services import feedback_storage

router = APIRouter(prefix="/feedback", tags=["feedback"])


@router.post("", response_model=FeedbackCreateResponse)
async def create_feedback(
    body: FeedbackItemCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> FeedbackCreateResponse:
    """Create a new feedback item; returns duplicate_candidates if similar open items exist."""
    validate_feedback_type(body.feedback_type)
    validate_component_id(body.component_id)
    validate_severity(body.severity)
    candidates = await feedback_storage.find_duplicate_candidates(
        db,
        component_id=body.component_id,
        feedback_type=body.feedback_type,
        project_id=body.project_id,
        title=body.title,
    )
    if body.vote_if_duplicate and candidates:
        canonical = candidates[0]
        vote = None
        if body.session_id:
            vote = await feedback_storage.vote_on_item(
                db,
                item_id=str(canonical.id),
                session_id=body.session_id,
                comment=body.description,
                agent_slug=body.agent_slug,
                model_used=body.model_used,
            )
            await db.commit()
            await db.refresh(canonical)
        return FeedbackCreateResponse(
            item=FeedbackItemResponse.model_validate(canonical),
            created=False,
            duplicate_candidates=[FeedbackItemResponse.model_validate(c) for c in candidates],
            voted=vote is not None,
        )
    item = await feedback_storage.create_feedback_item(
        db,
        component_id=body.component_id,
        feedback_type=body.feedback_type,
        title=body.title,
        description=body.description,
        severity=body.severity,
        project_id=body.project_id,
        session_id=body.session_id,
        agent_slug=body.agent_slug,
        model_used=body.model_used,
        session_type=body.session_type,
    )
    await db.commit()
    await db.refresh(item)
    return FeedbackCreateResponse(
        item=FeedbackItemResponse.model_validate(item),
        created=True,
        duplicate_candidates=[FeedbackItemResponse.model_validate(c) for c in candidates],
        voted=False,
    )


@router.get("", response_model=FeedbackListResponse)
async def list_feedback(
    db: Annotated[AsyncSession, Depends(get_db)],
    query: str | None = Query(default=None, description="Full-text search query"),
    component_id: str | None = Query(default=None, description="Filter by component"),
    feedback_type: str | None = Query(default=None, description="Filter by type"),
    status: str | None = Query(default=None, description="Filter by status"),
    project_id: str | None = Query(default=None, description="Filter by project"),
    sort: str = Query(default="votes", description="Sort: votes, newest, oldest"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> FeedbackListResponse:
    """List/search feedback items with filters."""
    validate_list_params(feedback_type, status, sort)
    filters = dict(query=query, component_id=component_id, feedback_type=feedback_type,
                   status=status, project_id=project_id)
    items = await feedback_storage.search_feedback_items(
        db, **filters, sort=sort, limit=limit, offset=offset
    )
    total = await feedback_storage.count_feedback_items(db, **filters)
    return FeedbackListResponse(
        items=[FeedbackItemResponse.model_validate(i) for i in items], total=total
    )


@router.get("/summary", response_model=FeedbackSummaryResponse)
async def get_summary(
    db: Annotated[AsyncSession, Depends(get_db)],
    project_id: str | None = Query(default=None),
    days: int = Query(default=30, ge=1, le=365),
) -> FeedbackSummaryResponse:
    """Get aggregated feedback summary."""
    summary = await feedback_storage.get_feedback_summary(db, project_id=project_id, days=days)
    return FeedbackSummaryResponse(**summary)


@router.get("/components/{component_id}", response_model=ComponentFeedbackResponse)
async def get_component_feedback(
    component_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    days: int = Query(default=30, ge=1, le=365),
    limit: int = Query(default=50, ge=1, le=200),
) -> ComponentFeedbackResponse:
    """Get feedback for a specific component."""
    validate_component_id(component_id)
    result = await feedback_storage.get_component_feedback(db, component_id, days=days, limit=limit)
    return ComponentFeedbackResponse(
        component_id=result["component_id"],
        stats=result["stats"],
        items=[FeedbackItemResponse.model_validate(i) for i in result["items"]],
    )


@router.get("/{item_id}", response_model=FeedbackItemWithVotes)
async def get_feedback_item(
    item_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> FeedbackItemWithVotes:
    """Get a feedback item with all votes."""
    item_id = await resolve_item(db, item_id)
    item = await feedback_storage.get_feedback_item(db, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Feedback item not found")
    votes = await feedback_storage.get_feedback_votes(db, item_id)
    item_data = FeedbackItemResponse.model_validate(item).model_dump()
    item_data["votes"] = [FeedbackVoteResponse.model_validate(v) for v in votes]
    return FeedbackItemWithVotes(**item_data)


@router.post("/{item_id}/vote", response_model=FeedbackVoteResponse | dict)
async def vote_on_feedback(
    item_id: str,
    body: FeedbackVoteCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> FeedbackVoteResponse | dict:
    """Vote on a feedback item. Idempotent per session."""
    item_id = await resolve_item(db, item_id)
    item = await feedback_storage.get_feedback_item(db, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Feedback item not found")
    vote = await feedback_storage.vote_on_item(
        db, item_id=item_id, session_id=body.session_id,
        comment=body.comment, agent_slug=body.agent_slug, model_used=body.model_used,
    )
    if vote is None:
        return {"message": "Already voted", "item_id": item_id, "session_id": body.session_id}
    await db.commit()
    await db.refresh(vote)
    await db.refresh(item)
    if item.vote_count >= HIGH_VOTE_THRESHOLD and item.linked_task_id is None:
        log_vote_threshold(item_id, item)
    return FeedbackVoteResponse.model_validate(vote)


@router.delete("/{item_id}")
async def delete_feedback(
    item_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    """Delete a feedback item and all its votes.

    Internal-only endpoint. Not exposed to agent clients — intended for
    admin tooling and test teardown only.
    """
    item_id = await resolve_item(db, item_id)
    deleted = await feedback_storage.delete_feedback_item(db, item_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Feedback item not found")
    await db.commit()
    return {"deleted": True, "id": item_id}


@router.post("/{item_id}/merge", response_model=FeedbackItemResponse)
async def merge_feedback(
    item_id: str,
    body: FeedbackMergeRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> FeedbackItemResponse:
    """Merge a duplicate feedback item into a canonical feedback item."""
    source_item_id = await resolve_item(db, item_id)
    target_item_id = await resolve_item(db, body.target_item_id)
    try:
        item = await feedback_storage.merge_feedback_items(
            db,
            source_item_id=source_item_id,
            target_item_id=target_item_id,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    if not item:
        raise HTTPException(status_code=404, detail="Feedback item not found")
    await db.commit()
    await db.refresh(item)
    return FeedbackItemResponse.model_validate(item)


@router.patch("/{item_id}", response_model=FeedbackItemResponse)
async def update_feedback(
    item_id: str,
    body: FeedbackStatusUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> FeedbackItemResponse:
    """Update feedback item status, resolution note, or linked task."""
    item_id = await resolve_item(db, item_id)
    if body.status and body.status not in VALID_STATUSES:
        raise HTTPException(status_code=422, detail=f"Invalid status '{body.status}'")
    item = await feedback_storage.update_feedback_status(
        db, item_id, status=body.status,
        resolution_note=body.resolution_note, linked_task_id=body.linked_task_id,
    )
    if not item:
        raise HTTPException(status_code=404, detail="Feedback item not found")
    await db.commit()
    await db.refresh(item)
    return FeedbackItemResponse.model_validate(item)
