"""Sync one native Pi session through canonical ingestion; no model calls."""

from __future__ import annotations

import asyncio
import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Session

from .adapters.pi import pi_header
from .models import SessionHeartbeatRequest, SessionUpsertRequest, TranscriptIngestRequest
from .service import heartbeat_session, ingest_transcript_events, upsert_session


async def sync_pi_session(db: AsyncSession, *, session_id: str, transcript: str,
                          project_id: str, cwd: str, provider: str, model: str,
                          phase: str = "idle", aico_session_id: str | None = None,
                          work_role: dict[str, str] | None = None,
                          retired_by_tether: bool = False) -> dict:
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
            "aico_session_id": aico_session_id or ((existing.provider_metadata or {}).get("aico_session_id") if existing else None),
            "cwd": header.get("cwd", cwd),
            "pi_selection": {"provider": provider, "model": model},
        },
    ))
    result = await ingest_transcript_events(db, session.id,
        TranscriptIngestRequest(provider="pi", transcript_path=str(path)), session=session)
    # Serialize retirement with late extension syncs, which must never reopen
    # a conversation after Tether has stopped its exact owned workload.
    latest = (await db.execute(select(Session).where(Session.id == session.id).with_for_update()
                              .execution_options(populate_existing=True))).scalar_one_or_none()
    if latest is None:
        raise ValueError("Pi session disappeared before heartbeat")
    retired = retired_by_tether or (latest.provider_metadata or {}).get("tether_retired") is True
    final_phase = "shutdown" if retired else phase
    await heartbeat_session(db, session.id, SessionHeartbeatRequest(
        cwd=cwd, phase=final_phase, status="completed" if final_phase == "shutdown" else "active",
        provider_metadata={"tether_retired": True} if retired_by_tether else {},
        request_source="pi-extension"), session=latest)
    return {"session_id": session.id, "events_appended": result.events_appended,
            "events_skipped": result.events_skipped, "phase": final_phase}


async def retire_pi_sessions(db: AsyncSession, aico_session_id: str) -> dict:
    """Finalize retained transcripts after Tether retires this exact workload."""
    if not re.fullmatch(r"aico-widget-[0-9a-f]{8}", aico_session_id):
        raise ValueError("An exact Tether ownership ID is required")
    sessions = (await db.execute(select(Session).where(
        Session.session_type == "pi",
        Session.provider_metadata["harness"].as_string() == "pi",
        Session.provider_metadata["aico_session_id"].as_string() == aico_session_id,
    ))).scalars().all()
    closed: list[str] = []
    for session in sessions:
        metadata = session.provider_metadata or {}
        if metadata.get("tether_retired") is True:
            continue
        selection = metadata["pi_selection"]
        await sync_pi_session(db, session_id=session.id, transcript=metadata["transcript_path"],
            project_id=session.project_id, cwd=metadata["cwd"],
            provider=selection["provider"], model=selection["model"], phase="shutdown",
            aico_session_id=aico_session_id, retired_by_tether=True)
        closed.append(session.id)
    return {"aico_session_id": aico_session_id, "closed_session_ids": closed}
