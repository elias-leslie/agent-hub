"""Session records for agents on remote agent hosts.

A host has no Agent Hub database, and its native transcripts are on its own disk.
Its `agent-hub-context` sends each transcript's new bytes here. Agent Hub keeps them
in the host's native home (``app.utils.native_homes``), at the path the host uses
under its own home, and ingests them through the same services as a local
transcript: canonical upsert, transcript ingestion, Pi sync, work-role binding,
finalize and close. Secret redaction applies where events are stored, as for local
sessions. Every session a host writes records the host's name, and a host may only
write its own sessions.
"""

from __future__ import annotations

import asyncio
import fcntl
import os
import re
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Session
from app.services.runtime_context import (
    CanonicalContextDeliveryRequest,
    _resolve_canonical_project_id,
)
from app.services.session_ingestion import (
    FinalizeSessionRequest,
    SessionUpsertRequest,
    TranscriptIngestRequest,
    finalize_session,
    ingest_transcript_events,
    upsert_session,
)
from app.services.session_ingestion.adapters.transcript_parsers import transcript_session_metadata
from app.services.session_ingestion.native_work_role import bind_native_work_role
from app.services.session_ingestion.pi_sync import retire_pi_sessions, sync_pi_session
from app.services.session_operations import close_session_if_active
from app.services.session_roles import WorkRoleDeclaration
from app.utils.native_homes import host_homes_root

Surface = Literal["claude_code", "codex", "pi"]
# Where each harness keeps its transcripts under a home, on the host and in its native home here.
SURFACE_ROOTS: dict[str, tuple[str, ...]] = {
    "claude_code": (".claude", "projects"),
    "codex": (".codex", "sessions"),
    "pi": (".pi", "agent", "sessions"),
}
_UUID = re.compile(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}")
_SEGMENT = re.compile(r"[A-Za-z0-9_.@+=-]{1,255}")
_MAX_DEPTH = 4  # Codex: YYYY/MM/DD/rollout-...jsonl


class HostSessionRefused(ValueError):
    """A host request this host may not make; fixed text, nothing of the request echoed."""

    def __init__(self, code: str, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.status = status


class TranscriptOffsetMismatch(ValueError):
    """The host's offset is not where Agent Hub's copy ends; it resends from ``size``."""

    def __init__(self, size: int) -> None:
        super().__init__("The transcript copy ends at another offset.")
        self.size = size


def host_metadata(host: str) -> dict[str, str]:
    # `host` is the session field every reader shows; `remote_host` scopes the session to its host.
    return {"host": host, "remote_host": host}


def transcript_file(host: str, surface: str, session_id: str, relative: str) -> Path:
    """The copy of a host transcript: ``<host home>/<surface root>/<relative>``, named for its session."""
    if surface not in SURFACE_ROOTS:
        raise HostSessionRefused("unknown_surface", "Unknown transcript surface.")
    if not _UUID.fullmatch(session_id):
        raise HostSessionRefused("invalid_session", "A native session UUID is required.")
    parts = relative.split("/")
    if (not 1 <= len(parts) <= _MAX_DEPTH
            or any(part in {".", ".."} or not _SEGMENT.fullmatch(part) for part in parts)
            or not parts[-1].endswith(".jsonl") or session_id not in parts[-1]):
        raise HostSessionRefused("invalid_path", "The transcript path is not a native transcript of this session.")
    return host_homes_root().joinpath(host, *SURFACE_ROOTS[surface], *parts)


def _contained(path: Path, host: str) -> None:
    home = host_homes_root() / host
    if not path.resolve().is_relative_to(home.resolve()):
        raise HostSessionRefused("invalid_path", "The transcript path leaves the host's home.")


def _private_dirs(directory: Path) -> None:
    # mkdir(parents=True) gives only the leaf its mode; every level of a copy stays owner-only.
    missing: list[Path] = []
    while not directory.exists():
        missing.append(directory)
        directory = directory.parent
    for level in reversed(missing):
        try:
            level.mkdir(mode=0o700)
        except FileExistsError:
            continue


def transcript_size(host: str, surface: str, session_id: str, relative: str) -> int:
    path = transcript_file(host, surface, session_id, relative)
    try:
        _contained(path, host)
        return path.stat().st_size
    except FileNotFoundError:
        return 0


def append_transcript(host: str, surface: str, session_id: str, relative: str,
                      offset: int, data: bytes, *, max_bytes: int) -> int:
    """Append ``data`` at ``offset`` of the copy; returns its new size. Blocking: run in a thread."""
    path = transcript_file(host, surface, session_id, relative)
    _private_dirs(path.parent)
    _contained(path.parent, host)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "ab") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)  # one writer per copy; released on close
        size = os.fstat(fd).st_size
        if offset != size:
            raise TranscriptOffsetMismatch(size)
        if size + len(data) > max_bytes:
            raise HostSessionRefused("transcript_too_large", "The transcript exceeds the host transcript limit.", 413)
        handle.write(data)
        return size + len(data)


class HostSessionSync(BaseModel):
    """What a host knows about one native session; Agent Hub reads the rest from the transcript."""

    surface: Surface
    session_id: str = Field(max_length=36)
    path: str = Field(max_length=1024, description="Transcript path under the surface's root on the host")
    cwd: str = Field(min_length=1, max_length=4096)
    project: str | None = Field(default=None, max_length=200)
    provider: str | None = Field(default=None, max_length=200)
    model: str | None = Field(default=None, max_length=200)
    branch: str | None = Field(default=None, max_length=500)
    repo_root: str | None = Field(default=None, max_length=4096)
    transport_variant: str | None = Field(default=None, max_length=200)
    git_context: str | None = Field(default=None, max_length=20_000)
    phase: Literal["idle", "working", "shutdown"] = "idle"
    aico_session_id: str | None = Field(default=None, max_length=200)
    aico_widget_id: str | None = Field(default=None, max_length=200)
    aico_project_id: str | None = Field(default=None, max_length=200)
    work_role: WorkRoleDeclaration | None = None
    finalize: bool = Field(default=False, description="Finalize and close after ingesting, as a Stop hook does")


class HostWorkRoleBinding(BaseModel):
    surface: Literal["claude_code", "codex"]
    session_id: str = Field(max_length=36)
    cwd: str = Field(min_length=1, max_length=4096)
    project: str | None = Field(default=None, max_length=200)
    model: str | None = Field(default=None, max_length=200)
    work_role: WorkRoleDeclaration


async def _own_session(db: AsyncSession, host: str, session_id: str) -> Session | None:
    existing = (await db.execute(select(Session).where(Session.id == session_id))).scalar_one_or_none()
    if existing is not None and (existing.provider_metadata or {}).get("remote_host") != host:
        raise HostSessionRefused("session_not_on_host", "This session was not recorded from this host.", 403)
    return existing


async def _project_id(surface: str, project: str | None, cwd: str) -> str:
    project_id = await _resolve_canonical_project_id(CanonicalContextDeliveryRequest(
        consumer_surface=surface, project_id=project, cwd=cwd))
    if not project_id:
        raise HostSessionRefused("unregistered_cwd", "The session's working directory is outside registered projects.")
    return project_id


def _codex_lineage(native: dict[str, Any]) -> tuple[str | None, str | None]:
    """The native parent thread and agent path, as ``validate_native_provenance`` reads them."""
    spawn: Any = native.get("source")
    for key in ("subagent", "thread_spawn"):
        spawn = spawn.get(key) if isinstance(spawn, dict) else None
    spawn = spawn if isinstance(spawn, dict) else {}
    parent = native.get("parent_thread_id", spawn.get("parent_thread_id"))
    agent_path = native.get("agent_path", spawn.get("agent_path"))
    return parent, agent_path if agent_path or parent else "/root"


async def sync_host_session(db: AsyncSession, host: str, request: HostSessionSync) -> dict[str, Any]:
    """Record a host session from its transcript copy, the way its local path records it."""
    path = transcript_file(host, request.surface, request.session_id, request.path)
    if not await asyncio.to_thread(path.is_file):
        raise HostSessionRefused("transcript_missing", "Send the transcript before syncing its session.", 409)
    await _own_session(db, host, request.session_id)
    project_id = await _project_id(request.surface, request.project, request.cwd)
    meta = host_metadata(host)
    if request.surface == "pi":
        if not request.provider or not request.model:
            raise HostSessionRefused("pi_model_required", "A Pi sync names its provider and model.")
        return await sync_pi_session(
            db, session_id=request.session_id, transcript=str(path), project_id=project_id, cwd=request.cwd,
            provider=request.provider, model=request.model, phase=request.phase,
            aico_session_id=request.aico_session_id,
            work_role=request.work_role.model_dump(exclude_none=True) if request.work_role else None,
            extra_metadata=meta)

    if request.surface == "codex":
        native = await asyncio.to_thread(transcript_session_metadata, str(path))
        if native is None or native.get("id") != request.session_id:
            raise HostSessionRefused("transcript_identity", "The transcript does not belong to this session.", 409)
        parent, agent_path = _codex_lineage(native)
        if parent is not None:
            await _own_session(db, host, parent)
        if request.aico_project_id and request.aico_project_id != project_id:
            raise HostSessionRefused("project_mismatch", "The Aico project and the working directory disagree.", 409)
        upsert = SessionUpsertRequest(
            session_id=request.session_id, project_id=project_id, provider="codex",
            model=request.model or "codex/unknown", session_type="agent", cwd=request.cwd,
            current_branch=request.branch, parent_session_id=parent, scope_confidence="unknown",
            request_source="codex-transcript-sync",
            provider_metadata={**meta, "harness": "codex_cli", "transcript_path": str(path), "cwd": request.cwd,
                "native_session_id": native.get("session_id") or native.get("id"),
                **({"repo_root": request.repo_root} if request.repo_root else {}),
                "external_identity": {
                    "harness": "codex", "launcher": "aico" if request.aico_session_id else "direct",
                    "display_identity": native.get("agent_nickname") or "codex",
                    "runtime_session_id": request.session_id, "agent_path": agent_path,
                    "aico_session_id": request.aico_session_id, "aico_widget_id": request.aico_widget_id,
                    "aico_project_id": request.aico_project_id,
                    "project_mapping_state": "matched" if request.aico_project_id else "git_only",
                }})
    else:
        provider = request.provider or "anthropic"
        upsert = SessionUpsertRequest(
            session_id=request.session_id, project_id=project_id, provider=provider,
            model=request.model or f"{provider}/unknown", session_type="claude_code", cwd=request.cwd,
            current_branch=request.branch, request_source="hook",
            provider_metadata={**meta, "harness": "claude_code", "transcript_path": str(path),
                **({"repo_root": request.repo_root} if request.repo_root else {}),
                **({"transport_variant": request.transport_variant} if request.transport_variant else {}),
                **({"aico_session_id": request.aico_session_id} if request.aico_session_id else {})})
    session, _ = await upsert_session(db, upsert)
    result = await ingest_transcript_events(db, session.id, TranscriptIngestRequest(
        provider="codex" if request.surface == "codex" else "claude_code", transcript_path=str(path)),
        session=session)
    status = session.status
    if request.finalize:
        await finalize_session(session.id, FinalizeSessionRequest(branch=request.branch,
                                                                  git_context=request.git_context))
        await db.refresh(session)
        status, _message = await close_session_if_active(db, session)
    return {"session_id": session.id, "events_appended": result.events_appended,
            "events_skipped": result.events_skipped, "status": status}


async def bind_host_work_role(db: AsyncSession, host: str, request: HostWorkRoleBinding) -> None:
    await _own_session(db, host, request.session_id)
    project_id = await _project_id(request.surface, request.project, request.cwd)
    await bind_native_work_role(
        db, surface=request.surface, session_id=request.session_id, project_id=project_id, cwd=request.cwd,
        model=request.model, work_role=request.work_role.model_dump(exclude_none=True),
        extra_metadata=host_metadata(host))


async def retire_host_pi_sessions(db: AsyncSession, host: str, aico_session_id: str) -> dict[str, Any]:
    return await retire_pi_sessions(db, aico_session_id, remote_host=host)
