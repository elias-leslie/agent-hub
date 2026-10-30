"""Bind an explicit launch work role to its native Claude Code or Codex session."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Session

from .models import SessionUpsertRequest
from .service import upsert_session


async def bind_native_work_role(
    db: AsyncSession, *, surface: str, session_id: str, project_id: str, cwd: str,
    model: str | None, work_role: dict[str, Any], extra_metadata: dict[str, Any] | None = None,
) -> None:
    # A supported native hook supplies the actual UUID. Correlation labels
    # (including AICO_SESSION_ID) are never accepted as session subjects.
    if str(uuid.UUID(session_id)) != session_id:
        raise ValueError("Expected exact native UUID")
    existing = (await db.execute(select(Session).where(Session.id == session_id))).scalar_one_or_none()
    if existing is not None and existing.parent_session_id is not None:
        return  # A native child never inherits its launcher's declaration.
    # Preserve the native producer's provider/model and existing identity.
    # Role immutability and provenance are enforced by canonical upsert.
    provider = existing.provider if existing else ("codex" if surface == "codex" else "anthropic")
    await upsert_session(db, SessionUpsertRequest(
        session_id=session_id, project_id=project_id, provider=provider,
        model=existing.model if existing else (model or f"{provider}/unknown"),
        session_type=existing.session_type if existing else ("agent" if surface == "codex" else "claude_code"),
        parent_session_id=existing.parent_session_id if existing else None,
        cwd=cwd, request_source="native-session-start",
        provider_metadata={**(extra_metadata or {}), "work_role": work_role,
                           "harness": "codex_cli" if surface == "codex" else "claude_code"},
    ))
