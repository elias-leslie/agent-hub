"""Sync one native Pi session through canonical ingestion; no model calls."""

from __future__ import annotations

import asyncio
import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Session

from .adapters.pi import pi_header
from .models import SessionHeartbeatRequest, SessionUpsertRequest, TranscriptIngestRequest
from .pi_errors import pi_request_errors
from .service import heartbeat_session, ingest_transcript_events, upsert_session


def canonical_pi_model(model: str | None, provider: str, models_used: list[str] | None = None) -> str:
    """Labels from other writers may be bare; Pi rows carry provider/model, preferring the transcript's provider."""
    if not model or model == f"{provider}/unknown":
        return f"{provider}/unknown"
    if "/" in model:
        return model
    seen = [used for used in models_used or [] if isinstance(used, str) and used.endswith(f"/{model}")]
    return seen[-1] if seen else f"{provider}/{model}"


def _drop_bare_duplicates(models: list[str] | None) -> list[str]:
    values = list(models or [])
    qualified = {value.rsplit("/", 1)[-1] for value in values if "/" in value}
    return [value for value in values if "/" in value or value not in qualified]


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
        model=canonical_pi_model(existing.model if existing is not None else None, provider,
                           existing.models_used if existing is not None else None),
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
    latest.model = canonical_pi_model(latest.model, provider, latest.models_used)
    latest.models_used = _drop_bare_duplicates(latest.models_used)
    await db.flush()
    request_errors = await pi_request_errors(db, session.id)
    retired = retired_by_tether or (latest.provider_metadata or {}).get("tether_retired") is True
    final_phase = "shutdown" if retired else phase
    await heartbeat_session(db, session.id, SessionHeartbeatRequest(
        cwd=cwd, phase=final_phase, status="completed" if final_phase == "shutdown" else "active",
        provider_metadata={**({"tether_retired": True} if retired_by_tether else {}),
                           **({"request_errors": request_errors} if request_errors else {})},
        request_source="pi-extension"), session=latest)
    return {"session_id": session.id, "events_appended": result.events_appended,
            "events_skipped": result.events_skipped, "phase": final_phase,
            "request_errors": (request_errors or {}).get("count", 0)}


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
    unavailable: list[str] = []
    for session in sessions:
        metadata = session.provider_metadata or {}
        if metadata.get("tether_retired") is True:
            continue
        selection = metadata.get("pi_selection")
        if (not isinstance(selection, dict)
                or not all(isinstance(selection.get(key), str) and selection[key] for key in ("provider", "model"))
                or not all(isinstance(metadata.get(key), str) and metadata[key] for key in ("transcript_path", "cwd"))):
            unavailable.append(session.id)
            continue
        await sync_pi_session(db, session_id=session.id, transcript=metadata["transcript_path"],
            project_id=session.project_id, cwd=metadata["cwd"],
            provider=selection["provider"], model=selection["model"], phase="shutdown",
            aico_session_id=aico_session_id, retired_by_tether=True)
        closed.append(session.id)
    return {"aico_session_id": aico_session_id, "closed_session_ids": closed,
            "unavailable_session_ids": unavailable}
