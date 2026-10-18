"""Session close settings.

GET /sessions/close-settings  current thresholds (also read by the host Codex collector)
PUT /sessions/close-settings  change some of them; the reapers and live classification use them at once
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.services import session_close_settings as service

router = APIRouter(prefix="/sessions/close-settings", tags=["sessions"])

_DAY = 24 * 60
_WEEK = 7 * _DAY


class SessionCloseSettingsResponse(BaseModel):
    dead_candidate_after_minutes: int
    reapable_after_minutes: int
    zero_event_close_after_minutes: int
    transcript_sync_close_after_minutes: int
    completion_close_after_minutes: int
    any_session_close_after_minutes: int
    codex_close_inactive_enabled: bool
    codex_scan_hours: int
    updated_by: str | None = None


class SessionCloseSettingsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dead_candidate_after_minutes: int | None = Field(None, ge=5, le=_DAY)
    reapable_after_minutes: int | None = Field(None, ge=15, le=_WEEK)
    zero_event_close_after_minutes: int | None = Field(None, ge=15, le=_WEEK)
    transcript_sync_close_after_minutes: int | None = Field(None, ge=15, le=_WEEK)
    completion_close_after_minutes: int | None = Field(None, ge=15, le=_WEEK)
    any_session_close_after_minutes: int | None = Field(None, ge=60, le=4 * _WEEK)
    codex_close_inactive_enabled: bool | None = None
    codex_scan_hours: int | None = Field(None, ge=1, le=24 * 14)


def _response(values: service.SessionCloseThresholds) -> SessionCloseSettingsResponse:
    return SessionCloseSettingsResponse(**values.as_dict())


@router.get("", response_model=SessionCloseSettingsResponse)
async def get_close_settings(db: Annotated[AsyncSession, Depends(get_db)]) -> SessionCloseSettingsResponse:
    return _response(await service.load(db))


@router.put("", response_model=SessionCloseSettingsResponse)
async def update_close_settings(
    body: SessionCloseSettingsUpdate,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SessionCloseSettingsResponse:
    changes = body.model_dump(exclude_unset=True, exclude_none=True)
    actor = str(getattr(request.state, "request_source", None) or "sessions-api")
    try:
        values = await service.update(db, changes, updated_by=actor)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _response(values)
