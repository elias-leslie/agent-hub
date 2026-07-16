"""Session repository — collapsed helper layer for the completion API.

Phase 3.2 of the convergence refactor (see
``backend/tasks/agent-framework-convergence/CONTINUATION.md``).
Collapses ``session_manager.py`` + ``_session_helpers.py`` +
``session_setup.py`` per convergence-map.md C1. DB models stay in
``app.models``; the actual upsert is in ``app.services.session_ingestion``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import Session as DBSession
from app.models import SessionEventType
from app.services.event_storage import get_sequencer, store_child_session_lifecycle_event
from app.services.events import publish_session_start
from app.services.llm_messages import Message
from app.services.session_ingestion import SessionUpsertRequest, upsert_session
from app.services.session_live_activity import (
    mark_session_completed,
    mark_session_execution_start,
)

if TYPE_CHECKING:
    from app.llm.types import Message as UniversalMessage

logger = logging.getLogger(__name__)

SessionResult = tuple[DBSession, list[Message], bool]
_CTX_EVENTS = (
    SessionEventType.USER_MESSAGE,
    SessionEventType.ASSISTANT_MESSAGE,
    SessionEventType.SYSTEM_MESSAGE,
)


@dataclass(slots=True)
class SessionRequest:
    session_id: str | None
    project_id: str
    provider: str
    model: str
    session_type: str = "completion"
    external_id: str | None = None
    client_id: str | None = None
    request_source: str | None = None
    agent_slug: str | None = None
    current_branch: str | None = None
    working_dir: str | None = None
    parent_session_id: str | None = None
    requested_provider: str | None = None
    requested_model: str | None = None
    trace_id: str | None = None


async def _validate_project(project_id: str) -> None:
    from app.constants.projects import validate_project_id

    await validate_project_id(project_id)


def _apply_trace_id(session: DBSession, trace_id: str | None) -> None:
    if not trace_id:
        return
    metadata: dict[str, object] = session.provider_metadata or {}
    metadata["trace_id"] = trace_id
    session.provider_metadata = metadata


def _context_messages(session: DBSession) -> list[Message]:
    return [
        Message(role=e.role, content=e.content)
        for e in sorted(session.events, key=lambda x: (x.turn, x.sequence))
        if e.event_type in _CTX_EVENTS and e.role and e.content
    ]


def _sync_sequencer(session: DBSession) -> None:
    max_turn = max((e.turn for e in session.events), default=0)
    if not max_turn:
        return
    next_turn = max_turn + 1
    max_seq = max((e.sequence for e in session.events if e.turn == next_turn), default=0)
    get_sequencer().set_turn(session.id, next_turn, max_seq)


async def _update_metadata(db: AsyncSession, session: DBSession, req: SessionRequest) -> None:
    existing = session.provider_metadata if isinstance(session.provider_metadata, dict) else {}
    rm, rp = req.requested_model or req.model, req.requested_provider or req.provider
    if "requested_model" not in existing and (session.model != rm or session.provider != rp):
        existing = {**existing, "requested_model": rm, "requested_provider": rp}
    session.provider_metadata = {
        **existing,
        "requested_model": rm,
        "requested_provider": rp,
        "effective_model": req.model,
        "effective_provider": req.provider,
        "fallback_used": rm != req.model,
    }
    models_used: list[str] = session.models_used or []
    providers_used: list[str] = session.providers_used or []
    if req.model not in models_used:
        session.models_used = [*models_used, req.model]
    if req.provider not in providers_used:
        session.providers_used = [*providers_used, req.provider]
    session.model, session.provider = req.model, req.provider
    if req.agent_slug and not session.agent_slug:
        session.agent_slug = req.agent_slug
    await db.flush()


async def update_session_metadata(
    db: AsyncSession,
    session: DBSession,
    provider: str,
    model: str,
    agent_slug: str | None,
    requested_model: str | None = None,
    requested_provider: str | None = None,
) -> None:
    """Update models/providers used and agent_slug on an existing session."""
    await _update_metadata(
        db,
        session,
        SessionRequest(
            session_id=None, project_id="", provider=provider, model=model,
            agent_slug=agent_slug, requested_model=requested_model,
            requested_provider=requested_provider,
        ),
    )


async def _maybe_reset_persona(db: AsyncSession, session: DBSession) -> bool:
    from app.services.persona_service import should_reset_persona_session

    if not await should_reset_persona_session(db, session):
        return False
    mark_session_completed(
        session, summary="Persona session auto-reset", termination_reason="persona_session_reset"
    )
    await db.commit()
    logger.info("Persona session %s auto-reset", session.id)
    return True


async def _create(db: AsyncSession, req: SessionRequest) -> SessionResult:
    session, _ = await upsert_session(
        db=db,
        request=SessionUpsertRequest(
            session_id=req.session_id,
            project_id=req.project_id,
            provider=req.requested_provider or req.provider,
            model=req.requested_model or req.model,
            session_type=req.session_type,
            external_id=req.external_id,
            client_id=req.client_id,
            request_source=req.request_source,
            agent_slug=req.agent_slug,
            current_branch=req.current_branch,
            cwd=req.working_dir,
            parent_session_id=req.parent_session_id,
        ),
    )
    _apply_trace_id(session, req.trace_id)
    if req.parent_session_id:
        await store_child_session_lifecycle_event(
            db, session, SessionEventType.CHILD_SESSION_STARTED
        )
    return session, [], True


async def get_or_create_session(
    db: AsyncSession,
    session_id: str | None,
    project_id: str,
    provider: str,
    model: str,
    session_type: str = "completion",
    external_id: str | None = None,
    client_id: str | None = None,
    request_source: str | None = None,
    agent_slug: str | None = None,
    current_branch: str | None = None,
    working_dir: str | None = None,
    parent_session_id: str | None = None,
    requested_provider: str | None = None,
    requested_model: str | None = None,
    trace_id: str | None = None,
) -> SessionResult:
    """Get existing session or create new one. Returns (session, messages, is_new)."""
    req = SessionRequest(
        session_id, project_id, provider, model, session_type, external_id, client_id,
        request_source, agent_slug, current_branch, working_dir, parent_session_id,
        requested_provider, requested_model, trace_id,
    )
    await _validate_project(req.project_id)
    if req.session_id:
        result = await db.execute(
            select(DBSession).options(selectinload(DBSession.events))
            .where(DBSession.id == req.session_id)
        )
        session = result.scalar_one_or_none()
        if session is not None:
            if req.agent_slug == "persona" and await _maybe_reset_persona(db, session):
                return await _create(db, replace(req, session_id=None, agent_slug="persona"))
            await _update_metadata(db, session, req)
            _sync_sequencer(session)
            _apply_trace_id(session, req.trace_id)
            return session, _context_messages(session), False
    return await _create(db, req)


async def setup_completion_session(
    db: AsyncSession,
    session_id: str | None,
    project_id: str,
    provider: str,
    model: str,
    external_id: str | None,
    client_id: str | None,
    request_source: str | None,
    agent_slug: str | None,
    current_branch: str | None,
    working_dir: str | None,
    parent_session_id: str | None,
    messages: list[dict[str, Any]],
    requested_provider: str | None = None,
    requested_model: str | None = None,
    trace_id: str | None = None,
) -> tuple[DBSession, str, bool, list[dict[str, Any]]]:
    """Setup session and prepend its existing context to the incoming messages."""
    session, ctx, is_new = await get_or_create_session(
        db, session_id, project_id, provider, model,
        external_id=external_id, client_id=client_id, request_source=request_source,
        agent_slug=agent_slug, current_branch=current_branch, working_dir=working_dir,
        parent_session_id=parent_session_id, requested_provider=requested_provider,
        requested_model=requested_model, trace_id=trace_id,
    )
    mark_session_execution_start(session)
    if is_new:
        await publish_session_start(session.id, model, project_id)
    await db.commit()
    merged = [{"role": m.role, "content": m.content} for m in ctx] + list(messages) if ctx else list(messages)
    return session, session.id, is_new, merged


def _prev_total(cache: object, key: str) -> int:
    if not isinstance(cache, dict):
        return 0
    val = cache.get(key)
    return int(val) if isinstance(val, (int, float)) else 0


def merge_cache_metrics(existing: dict[str, object], metrics: dict[str, int]) -> dict[str, object]:
    creation = metrics.get("cache_creation_input_tokens", 0)
    read = metrics.get("cache_read_input_tokens", 0)
    prev = existing.get("cache")
    return {
        **existing,
        "cache": {
            "last_cache_creation_tokens": creation,
            "last_cache_read_tokens": read,
            "total_cache_creation_tokens": _prev_total(prev, "total_cache_creation_tokens") + creation,
            "total_cache_read_tokens": _prev_total(prev, "total_cache_read_tokens") + read,
        },
    }


async def update_provider_metadata(
    db: AsyncSession, session: DBSession, cache_metrics: dict[str, int] | None
) -> None:
    if not cache_metrics:
        return
    session.provider_metadata = merge_cache_metrics(session.provider_metadata or {}, cache_metrics)
    await db.commit()


def apply_execution_metadata(
    session: DBSession,
    *,
    requested_model: str,
    effective_model: str,
    fallback_used: bool,
    fallback_reason: str | None = None,
) -> None:
    """Align session row + provider metadata with the actual execution path."""
    from app.services.agent_routing import get_provider_for_model

    rp = get_provider_for_model(requested_model)
    ep = get_provider_for_model(effective_model)
    models_used: list[str] = list(session.models_used or [])
    providers_used: list[str] = list(session.providers_used or [])
    for m in (requested_model, effective_model):
        if m not in models_used:
            models_used.append(m)
    for p in (rp, ep):
        if p not in providers_used:
            providers_used.append(p)
    metadata: dict[str, object] = session.provider_metadata or {}
    metadata.update(
        requested_model=requested_model,
        requested_provider=rp,
        effective_model=effective_model,
        effective_provider=ep,
        fallback_used=fallback_used,
    )
    if fallback_reason:
        metadata["fallback_reason"] = fallback_reason
    session.model = effective_model
    session.provider = ep
    session.models_used = models_used
    session.providers_used = providers_used
    session.provider_metadata = metadata


def load_universal_history(session: DBSession) -> list[UniversalMessage]:
    """Session history as pi-mono ``app.llm.types.Message`` (new pipeline).

    Reconstructs replayed turns from DB events. AssistantMessage required
    fields (api/provider/model/usage/stop_reason) are filled from
    session-row provenance + sensible defaults — the orchestrator never
    re-emits these into the wire response.
    """
    from app.llm.types import AssistantMessage, TextContent, Usage, UserMessage

    provider = session.provider or ""
    model = session.model or ""
    history: list[UniversalMessage] = []
    for event in sorted(session.events, key=lambda x: (x.turn, x.sequence)):
        if not event.role or not event.content:
            continue
        text = event.content if isinstance(event.content, str) else str(event.content)
        ts = int(event.created_at.timestamp() * 1000) if event.created_at else 0
        if event.event_type == SessionEventType.USER_MESSAGE:
            history.append(UserMessage(content=text, timestamp=ts))
        elif event.event_type == SessionEventType.ASSISTANT_MESSAGE:
            history.append(
                AssistantMessage(
                    content=[TextContent(text=text)],
                    api="",
                    provider=provider,
                    model=model,
                    usage=Usage(),
                    stop_reason="stop",
                    timestamp=ts,
                )
            )
    return history


__all__ = [
    "SessionRequest",
    "SessionResult",
    "apply_execution_metadata",
    "get_or_create_session",
    "load_universal_history",
    "merge_cache_metrics",
    "setup_completion_session",
    "update_provider_metadata",
    "update_session_metadata",
]
