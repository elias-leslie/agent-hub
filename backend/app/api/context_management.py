"""Context management shares runtime assembly and authenticated dashboard access."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.services.api_key_auth import AuthenticatedKey, require_api_key
from app.services.context_governance import (
    ContextDraft,
    ContextFeedback,
    apply_draft,
    history,
    inventory,
    preview_draft,
    record,
    record_feedback,
    undo_change,
)
from app.services.context_maintenance_actions import MaintenanceRequest, handle_maintenance
from app.services.context_review import ContextReviewRequest, run_review
from app.services.runtime_context import CanonicalContextDeliveryRequest

router = APIRouter(prefix="/manage")
DB = Annotated[AsyncSession, Depends(get_db)]
Auth = Annotated[AuthenticatedKey | None, Depends(require_api_key)]


def actor(auth: AuthenticatedKey | None) -> str:
    return f"api:{auth.key_id}" if auth else "dashboard:operator"


@router.post("/inventory")
async def get_inventory(context: CanonicalContextDeliveryRequest, db: DB, auth: Auth = None):
    return await inventory(db, context)


@router.post("/preview")
async def preview(request: ContextDraft, db: DB, auth: Auth = None):
    return await preview_draft(db, request)


@router.post("/save")
async def save(request: ContextDraft, db: DB, auth: Auth = None):
    try:
        result = await apply_draft(db, request, actor(auth), preview=False)
        await db.commit()
        return result
    except Exception:
        await db.rollback()
        raise


@router.get("/history")
async def get_history(db: DB, source_id: str | None = None, auth: Auth = None):
    return await history(db, source_id)


@router.post("/changes/{change_id}/undo")
async def undo(change_id: str, db: DB, auth: Auth = None):
    try:
        result = await undo_change(db, change_id, actor(auth))
        await db.commit()
        return result
    except Exception:
        await db.rollback()
        raise


class WorkflowActivation(BaseModel):
    consumer_surface: str = Field(min_length=1)
    session_id: str = Field(min_length=1)
    workflow_ids: list[str]


@router.post("/workflows")
async def activate_workflow(request: WorkflowActivation, db: DB, auth: Auth = None):
    from app.services.memory.applicability import normalize_consumer_surface
    payload = request.model_dump()
    payload["consumer_surface"] = normalize_consumer_surface(request.consumer_surface)
    key = await record(db, "workflow", actor(auth), payload)
    await db.commit()
    return {"id": key, "state": "saved", "delivery": "takes effect on next supported context generation; existing native messages are unchanged"}


@router.post("/feedback")
async def feedback(request: ContextFeedback, db: DB, auth: Auth = None):
    return await record_feedback(db, request, actor(auth))


@router.post("/review")
async def review(request: ContextReviewRequest, db: DB, auth: Auth = None):
    return await run_review(db, request, actor(auth))


@router.post("/maintenance")
async def maintenance(request: MaintenanceRequest, http_request: Request, db: DB, auth: Auth = None):
    try:
        service_client = None
        if request.action == "verify_work":
            from app.middleware.access_control_auth import require_service_client

            service_client = await require_service_client(http_request)
        return await handle_maintenance(
            db,
            request,
            actor(auth),
            operator=auth is None,
            caller_service_client=service_client,
        )
    except Exception:
        await db.rollback()
        raise
