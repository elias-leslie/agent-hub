"""Session management for completion API."""

from __future__ import annotations

import logging
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.base import Message
from app.models import Session as DBSession

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
) -> _SessionResult:
    session = DBSession(
        id=session_id or str(uuid.uuid4()),
        project_id=project_id,
        provider=provider,
        model=model,
        status="active",
        session_type=session_type,
        external_id=external_id,
        client_id=client_id,
        request_source=request_source,
        agent_slug=agent_slug,
        current_branch=current_branch,
        models_used=[model],
        providers_used=[provider],
    )
    db.add(session)
    await db.commit()
    await db.refresh(session)
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
) -> _SessionResult:
    """Get existing session or create new one. Returns (session, messages, is_new)."""
    from app.constants import VALID_PROJECT_IDS
    from app.constants.projects import is_cache_stale, refresh_project_ids_cache

    if is_cache_stale():
        await refresh_project_ids_cache()
    if project_id not in VALID_PROJECT_IDS:
        raise ValueError(
            f"Unknown project_id '{project_id}'. Valid projects: {sorted(VALID_PROJECT_IDS)}"
        )

    if session_id:
        existing = await load_session(db, session_id, provider, model, agent_slug)
        if existing is not None:
            if agent_slug == "persona" and await maybe_reset_persona_session(db, existing):
                return await _create_session(
                    db, None, project_id, provider, model, session_type,
                    external_id, client_id, request_source, "persona", current_branch,
                )
            return existing

    return await _create_session(
        db, session_id, project_id, provider, model, session_type,
        external_id, client_id, request_source, agent_slug, current_branch,
    )


async def update_provider_metadata(
    db: AsyncSession, session: DBSession, cache_metrics: dict[str, int] | None
) -> None:
    """Update session with provider-specific metadata like cache info."""
    if not cache_metrics:
        return
    existing: dict[str, object] = session.provider_metadata or {}
    session.provider_metadata = merge_cache_metrics(existing, cache_metrics)
    await db.commit()
