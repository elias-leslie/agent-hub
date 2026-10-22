"""Sync one native Pi session through canonical ingestion; no model calls."""

from __future__ import annotations

import asyncio

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Session

from .adapters.pi import pi_header
from .models import SessionHeartbeatRequest, SessionUpsertRequest, TranscriptIngestRequest
from .service import heartbeat_session, ingest_transcript_events, upsert_session


async def sync_pi_session(db: AsyncSession, *, session_id: str, transcript: str,
                          project_id: str, cwd: str, provider: str, model: str,
                          phase: str = "idle", aico_session_id: str | None = None,
                          work_role: dict[str, str] | None = None) -> dict:
    path, header = await asyncio.to_thread(pi_header, transcript, session_id)
    existing = (await db.execute(select(Session).where(Session.id == session_id))).scalar_one_or_none()
    if existing is not None:
        metadata = existing.provider_metadata or {}
        if existing.session_type != "pi" or metadata.get("transcript_path") != str(path):
            raise ValueError("Pi sync cannot replace another native session or transcript")
    session, _ = await upsert_session(db, SessionUpsertRequest(
        session_id=session_id, project_id=project_id, provider=provider,
        model=existing.model if existing is not None else f"{provider}/unknown",
        session_type="pi", cwd=cwd, request_source="pi-extension",
        provider_metadata={
            **({"work_role": work_role} if work_role is not None else {}),
            "transcript_path": str(path), "harness": "pi", "native_session_id": session_id,
            "aico_session_id": aico_session_id, "cwd": header.get("cwd", cwd),
            "pi_selection": {"provider": provider, "model": model},
        },
    ))
    result = await ingest_transcript_events(db, session.id,
        TranscriptIngestRequest(provider="pi", transcript_path=str(path)), session=session)
    await heartbeat_session(db, session.id, SessionHeartbeatRequest(
        cwd=cwd, phase=phase, status="completed" if phase == "shutdown" else "active",
        request_source="pi-extension"), session=session)
    return {"session_id": session.id, "events_appended": result.events_appended,
            "events_skipped": result.events_skipped, "phase": phase}
