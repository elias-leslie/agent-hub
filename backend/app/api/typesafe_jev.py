"""Project-scoped API for the bounded TypeSafe Jev evaluation pilot."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.access_control_helpers import require_project_access
from app.api.typesafe_jev_schemas import TypeSafeJevRequest, TypeSafeJevResult
from app.db import get_db
from app.services.api_key_auth import AuthenticatedKey, require_api_key
from app.services.typesafe_jev import TypeSafeJevError, dispatch_typesafe_jev

router = APIRouter(prefix="/neri/jev", tags=["neri-jev"])
_PROJECT_ID = "security-research"


@router.post("/evaluate", response_model=TypeSafeJevResult)
async def evaluate(
    request: TypeSafeJevRequest,
    http_request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    _auth: Annotated[AuthenticatedKey | None, Depends(require_api_key)] = None,
) -> TypeSafeJevResult:
    """Dry-run or execute one typed Jev evaluation under the shared pilot ceiling."""
    require_project_access(http_request, _PROJECT_ID)
    try:
        return await dispatch_typesafe_jev(request, db)
    except TypeSafeJevError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={"error": exc.kind, "message": exc.detail},
        ) from exc


__all__ = ["router"]
