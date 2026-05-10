"""Compactness gate threshold API."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.services.api_key_auth import AuthenticatedKey, require_api_key
from app.services.compactness_policy import (
    CompactnessPolicyResponse,
    CompactnessPolicyUpdate,
    get_compactness_policy,
    update_compactness_policy,
)

router = APIRouter(prefix="/compactness", tags=["compactness"])


@router.get("/policy", response_model=CompactnessPolicyResponse)
async def read_compactness_policy(
    db: Annotated[AsyncSession, Depends(get_db)],
    auth: Annotated[AuthenticatedKey | None, Depends(require_api_key)] = None,
) -> CompactnessPolicyResponse:
    return await get_compactness_policy(db)


@router.put("/policy", response_model=CompactnessPolicyResponse)
async def write_compactness_policy(
    payload: CompactnessPolicyUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    auth: Annotated[AuthenticatedKey | None, Depends(require_api_key)] = None,
) -> CompactnessPolicyResponse:
    return await update_compactness_policy(db, payload)
