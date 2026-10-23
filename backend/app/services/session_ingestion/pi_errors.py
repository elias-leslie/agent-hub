"""Failed Pi requests: Pi exits 0 on request failure, so the transcript's error records are the only signal."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import SessionEvent
from app.services.secret_redaction import redact_text

_POLICY: dict[str, Any] = json.loads(Path(__file__).with_name("pi_error_categories.json").read_text())


def classify_pi_error(message: str) -> str:
    lowered = message.lower()
    for category in _POLICY["categories"]:
        if any(needle in lowered for needle in category["contains"]):
            return category["id"]
    return _POLICY["fallback"]


def summarize_pi_errors(count: int, last_message: str | None) -> dict[str, Any] | None:
    """Content-free summary: count, last category, and a short redacted provider message."""
    if count <= 0:
        return None
    message = (redact_text(re.sub(r"\s+", " ", last_message or "")) or "").strip()
    return {"count": count, "last_category": classify_pi_error(message),
            "last_message": message[: _POLICY["message_limit"]]}


async def pi_request_errors(db: AsyncSession, session_id: str) -> dict[str, Any] | None:
    """Derived from retained error events, so replay and re-sync never change the count."""
    where = (SessionEvent.session_id == session_id, SessionEvent.event_type == "error")
    count = (await db.execute(select(func.count()).select_from(SessionEvent).where(*where))).scalar_one()
    if not count:
        return None
    last = (await db.execute(select(SessionEvent.content).where(*where)
                             .order_by(SessionEvent.turn.desc(), SessionEvent.sequence.desc()).limit(1))).scalar_one_or_none()
    return summarize_pi_errors(int(count), last)
