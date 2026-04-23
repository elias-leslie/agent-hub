from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.services.telegram_config_service import get_telegram_status, update_telegram_config

router = APIRouter(prefix="/admin/telegram", tags=["admin", "telegram"])


class TelegramStatusResponse(BaseModel):
    configured: bool
    bot_token_source: str | None = None
    bot_username: str | None = None
    allowed_chat_ids: list[str]
    allowed_chat_ids_source: str | None = None
    report_chat_id: str | None = None
    report_chat_id_source: str | None = None
    runner_status: str
    last_poll_at: str | None = None
    last_error: str | None = None


class TelegramConfigUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bot_token: str | None = None
    allowed_chat_ids: list[str | int] | None = None
    report_chat_id: str | int | None = None


@router.get("/status", response_model=TelegramStatusResponse)
async def telegram_status(
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TelegramStatusResponse:
    payload = await get_telegram_status(db)
    return TelegramStatusResponse.model_validate(payload)


@router.put("/config", response_model=TelegramStatusResponse)
async def put_telegram_config(
    payload: TelegramConfigUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TelegramStatusResponse:
    try:
        result = await update_telegram_config(db, payload.model_dump(exclude_unset=True))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return TelegramStatusResponse.model_validate(result)
