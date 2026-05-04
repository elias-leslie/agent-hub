"""Session management for completion API."""

from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.base import Message
from app.models import Session as DBSession
from app.models import SessionEventType
from app.services.event_storage import store_child_session_lifecycle_event
from app.services.session_ingestion import SessionUpsertRequest, upsert_session

from ._session_helpers import load_session, maybe_reset_persona_session, merge_cache_metrics

logger = logging.getLogger(__name__)

_SessionResult = tuple[DBSession, list[Message], bool]


async def _create_session(
    db: AsyncSession,
    session_id: str | None,
    project_id: str,
    provider: str,
    model: str,
    session_type: str,
    external_id: str | None,
    client_id: str | None,
    request_source: str | None,
    agent_slug: str | None,
    current_branch: str | None,
    working_dir: str | None,
    parent_session_id: str | None,
    requested_provider: str | None = None,
    requested_model: str | None = None,
    trace_id: str | None = None,
) -> _SessionResult:
    session, _ = await upsert_session(
        db=db,
        request=SessionUpsertRequest(
            session_id=session_id,
            project_id=project_id,
            provider=requested_provider or provider,
            model=requested_model or model,
            session_type=session_type,
            external_id=external_id,
            client_id=client_id,
            request_source=request_source,
            agent_slug=agent_slug,
            current_branch=current_branch,
            cwd=working_dir,
            parent_session_id=parent_session_id,
        ),
    )
    _apply_trace_id_metadata(session, trace_id)
    if parent_session_id:
        await store_child_session_lifecycle_event(
            db,
            session,
            SessionEventType.CHILD_SESSION_STARTED,
        )
    return session, [], True


async def _validate_project(project_id: str) -> None:
    """Ensure project_id is known, refreshing the cache if stale."""
    from app.constants import VALID_PROJECT_IDS
    from app.constants.projects import is_cache_stale, refresh_project_ids_cache

    if is_cache_stale():
        await refresh_project_ids_cache()
    if project_id not in VALID_PROJECT_IDS:
        raise ValueError(
            f"Unknown project_id '{project_id}'. Valid projects: {sorted(VALID_PROJECT_IDS)}"
        )


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
) -> _SessionResult:
    """Get existing session or create new one. Returns (session, messages, is_new)."""
    await _validate_project(project_id)

    if session_id:
        existing = await load_session(
            db,
            session_id,
            provider,
            model,
            agent_slug,
            requested_model=requested_model,
            requested_provider=requested_provider,
        )
        if existing is not None:
            if agent_slug == "persona" and await maybe_reset_persona_session(db, existing):
                return await _create_session(
                    db, None, project_id, provider, model, session_type,
                    external_id, client_id, request_source, "persona", current_branch,
                    working_dir,
                    parent_session_id,
                    requested_provider=requested_provider,
                    requested_model=requested_model,
                    trace_id=trace_id,
                )
            _apply_trace_id_metadata(existing[0], trace_id)
            return existing

    return await _create_session(
        db, session_id, project_id, provider, model, session_type,
        external_id, client_id, request_source, agent_slug, current_branch,
        working_dir,
        parent_session_id,
        requested_provider=requested_provider,
        requested_model=requested_model,
        trace_id=trace_id,
    )


def _apply_trace_id_metadata(session: DBSession, trace_id: str | None) -> None:
    """Persist trace correlation into session metadata when supplied by the caller."""
    if not trace_id:
        return
    metadata: dict[str, object] = session.provider_metadata or {}
    metadata["trace_id"] = trace_id
    session.provider_metadata = metadata


async def update_provider_metadata(
    db: AsyncSession, session: DBSession, cache_metrics: dict[str, int] | None
) -> None:
    """Update session with provider-specific metadata like cache info."""
    if not cache_metrics:
        return
    existing: dict[str, object] = session.provider_metadata or {}
    session.provider_metadata = merge_cache_metrics(existing, cache_metrics)
    await db.commit()


def apply_execution_metadata(
    session: DBSession,
    *,
    requested_model: str,
    effective_model: str,
    fallback_used: bool,
    fallback_reason: str | None = None,
) -> None:
    """Align session row and provider metadata with the actual execution path."""
    from app.services.agent_routing import get_provider_for_model

    requested_provider = get_provider_for_model(requested_model)
    effective_provider = get_provider_for_model(effective_model)

    models_used: list[str] = session.models_used or []
    providers_used: list[str] = session.providers_used or []
    if requested_model not in models_used:
        models_used = [*models_used, requested_model]
    if effective_model not in models_used:
        models_used = [*models_used, effective_model]
    if requested_provider not in providers_used:
        providers_used = [*providers_used, requested_provider]
    if effective_provider not in providers_used:
        providers_used = [*providers_used, effective_provider]

    metadata: dict[str, object] = session.provider_metadata or {}
    metadata.update(
        {
            "requested_model": requested_model,
            "requested_provider": requested_provider,
            "effective_model": effective_model,
            "effective_provider": effective_provider,
            "fallback_used": fallback_used,
        }
    )
    if fallback_reason:
        metadata["fallback_reason"] = fallback_reason

    session.model = effective_model
    session.provider = effective_provider
    session.models_used = models_used
    session.providers_used = providers_used
    session.provider_metadata = metadata
