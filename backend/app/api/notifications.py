"""Telegram notification API — lets sibling projects (portfolio-ai) push to the
household Telegram chat without duplicating bot credentials ([M:6084f2a8]).

Delegates to the same configured-report path Jenny uses
(telegram_delivery.send_configured_report), so token/chat config stays in
agent-hub's DB-backed telegram runtime config.
"""

from __future__ import annotations

import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.services.telegram_delivery import send_configured_report

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/notifications", tags=["notifications"])

DbDep = Annotated[AsyncSession, Depends(get_db)]


class TelegramNotifyRequest(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    body: str = Field(min_length=1, max_length=8000)
    severity: str = "info"  # info | warning | critical — rendered as a prefix
    source: str | None = Field(default=None, max_length=100)


_SEVERITY_PREFIX = {"warning": "⚠️ ", "critical": "🚨 "}


@router.post("/telegram")
async def send_telegram_notification(req: TelegramNotifyRequest, db: DbDep) -> dict[str, Any]:
    """Send a message to the configured household Telegram report chat."""
    title = req.title
    if title:
        title = f"{_SEVERITY_PREFIX.get(req.severity, '')}{title}"
    try:
        sent = await send_configured_report(db=db, title=title, body=req.body)
    except RuntimeError as exc:
        # bot_token / report_chat_id missing — configuration, not request, error
        raise HTTPException(status_code=503, detail=f"Telegram not configured: {exc}") from exc
    logger.info(
        "telegram_notification_sent source=%s severity=%s chunks=%d",
        req.source,
        req.severity,
        sent,
    )
    return {"status": "sent" if sent else "skipped", "chunks": sent}
