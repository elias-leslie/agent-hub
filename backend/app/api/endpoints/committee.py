"""Committee roundtable orchestration endpoint."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.orchestration_models import CommitteeRoundtableRequest, CommitteeRoundtableResponse
from app.db import get_db
from app.services.committee_roundtable_service import CommitteeRoundtableService

router = APIRouter()


@router.post("/committee", response_model=CommitteeRoundtableResponse)
async def run_committee_roundtable(
    request: CommitteeRoundtableRequest,
    http_request: Request,
    db: Annotated[AsyncSession | None, Depends(get_db)] = None,
) -> CommitteeRoundtableResponse:
    service = CommitteeRoundtableService()
    payload = await service.run_roundtable(request, http_request, db)
    return CommitteeRoundtableResponse.model_validate(payload)
