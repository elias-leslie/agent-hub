"""Session records for remote agent hosts, authenticated with the host's bearer token.

The host's `agent-hub-context` sends native transcripts here in pieces and asks
for them to be recorded (see app/services/remote_host_sessions.py). A host only
reads and writes its own transcripts and sessions. Like the other host routes,
these are exempt from request logging: their bodies are transcripts.
"""

from __future__ import annotations

import asyncio
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.remote_hosts import require_host
from app.config import settings
from app.db import get_db
from app.services.remote_host_sessions import (
    HostSessionRefused,
    HostSessionSync,
    HostWorkRoleBinding,
    TranscriptOffsetMismatch,
    append_transcript,
    bind_host_work_role,
    retire_host_pi_sessions,
    sync_host_session,
    transcript_size,
)
from app.services.session_ingestion.service import SessionIngestionConflict
from app.services.session_roles import WorkRoleConflict
from app.storage.remote_hosts import HostIdentity

router = APIRouter(prefix="/host-sessions", tags=["remote-hosts"])
Host = Annotated[HostIdentity, Depends(require_host)]
Db = Annotated[AsyncSession, Depends(get_db)]
TranscriptPath = Annotated[str, Query(max_length=1024, description="Path under the surface's transcript root")]


class TranscriptSize(BaseModel):
    size: int


class PiRetirement(BaseModel):
    aico_session_id: str = Field(max_length=200)


def _refusal(exc: Exception) -> HTTPException:
    # The app's HTTPException handler answers {"error": code, "message", "details"}.
    if isinstance(exc, HostSessionRefused):
        return HTTPException(status_code=exc.status, detail={"error": exc.code, "message": str(exc)})
    if isinstance(exc, TranscriptOffsetMismatch):
        return HTTPException(status_code=409, detail={"error": "offset_mismatch", "message": str(exc),
                                                      "details": [{"size": exc.size}]})
    if isinstance(exc, SessionIngestionConflict | WorkRoleConflict):
        return HTTPException(status_code=409, detail={"error": exc.code, "message": str(exc)})
    return HTTPException(status_code=400, detail={"error": "invalid", "message": str(exc)})


async def _bounded_body(request: Request, limit: int) -> bytes:
    declared = request.headers.get("content-length")
    if declared is not None and (not declared.isdigit() or int(declared) > limit):
        raise HTTPException(status_code=413, detail={"error": "chunk_too_large", "message": "Send smaller pieces."})
    chunks: list[bytes] = []
    received = 0
    async for chunk in request.stream():
        received += len(chunk)
        if received > limit:
            raise HTTPException(status_code=413, detail={"error": "chunk_too_large", "message": "Send smaller pieces."})
        chunks.append(chunk)
    return b"".join(chunks)


@router.get("/transcripts/{surface}/{session_id}", response_model=TranscriptSize)
async def get_transcript_size(surface: str, session_id: str, path: TranscriptPath, host: Host) -> TranscriptSize:
    """How much of this transcript Agent Hub already has; the host sends the rest."""
    try:
        return TranscriptSize(size=await asyncio.to_thread(transcript_size, host.name, surface, session_id, path))
    except ValueError as exc:
        raise _refusal(exc) from exc


@router.post("/transcripts/{surface}/{session_id}", response_model=TranscriptSize)
async def append_transcript_bytes(
    surface: str, session_id: str, path: TranscriptPath, request: Request, host: Host,
    offset: Annotated[int, Query(ge=0)],
) -> TranscriptSize:
    """Append the raw bytes in the body at ``offset``; a wrong offset answers 409 with the copy's size."""
    data = await _bounded_body(request, settings.host_transcript_chunk_max_bytes)
    try:
        size = await asyncio.to_thread(append_transcript, host.name, surface, session_id, path, offset, data,
                                       max_bytes=settings.host_transcript_max_bytes)
    except ValueError as exc:
        raise _refusal(exc) from exc
    return TranscriptSize(size=size)


@router.post("/sync")
async def sync_session(body: HostSessionSync, host: Host, db: Db) -> dict[str, Any]:
    """Record the session from the transcript copy: upsert, ingest, and for a Stop hook finalize and close."""
    try:
        return await sync_host_session(db, host.name, body)
    except ValueError as exc:
        raise _refusal(exc) from exc


@router.post("/work-role", status_code=204)
async def bind_work_role(body: HostWorkRoleBinding, host: Host, db: Db) -> None:
    """Bind a Tether launch's work role to its native Claude Code or Codex session."""
    try:
        await bind_host_work_role(db, host.name, body)
    except ValueError as exc:
        raise _refusal(exc) from exc


@router.post("/retire-pi")
async def retire_pi(body: PiRetirement, host: Host, db: Db) -> dict[str, Any]:
    """Finalize this host's Pi sessions for a retired Tether workload."""
    try:
        return await retire_host_pi_sessions(db, host.name, body.aico_session_id)
    except ValueError as exc:
        raise _refusal(exc) from exc
