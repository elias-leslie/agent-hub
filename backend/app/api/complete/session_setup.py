"""Session setup for completion API."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from app.services.events import publish_session_start
from app.services.session_live_activity import mark_session_execution_start

from .session_manager import get_or_create_session

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.models import Session as DBSession

logger = logging.getLogger(__name__)


def _merge_messages(
    context_messages: list[Any],
    input_messages: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Prepend context messages to input messages."""
    if not context_messages:
        return list(input_messages)
    return [{"role": m.role, "content": m.content} for m in context_messages] + list(input_messages)


async def _init_session(
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
    requested_provider: str | None = None,
    requested_model: str | None = None,
    trace_id: str | None = None,
) -> tuple[DBSession, list[Any], bool]:
    """Get or create a session and publish a start event when new."""
    session, ctx, is_new = await get_or_create_session(
        db,
        session_id,
        project_id,
        provider,
        model,
        session_type="completion",
        external_id=external_id,
        client_id=client_id,
        request_source=request_source,
        agent_slug=agent_slug,
        current_branch=current_branch,
        working_dir=working_dir,
        parent_session_id=parent_session_id,
        requested_provider=requested_provider,
        requested_model=requested_model,
        trace_id=trace_id,
    )
    mark_session_execution_start(session)
    if is_new:
        await publish_session_start(session.id, model, project_id)
    await db.commit()
    return session, ctx, is_new


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
    """Setup session and prepare messages for completion."""
    session, ctx, is_new = await _init_session(
        db,
        session_id,
        project_id,
        provider,
        model,
        external_id,
        client_id,
        request_source,
        agent_slug,
        current_branch,
        working_dir,
        parent_session_id,
        requested_provider,
        requested_model,
        trace_id,
    )
    return session, session.id, is_new, _merge_messages(ctx, messages)
