"""Session setup for completion API."""

from __future__ import annotations

import logging
import uuid
from typing import TYPE_CHECKING, Any

from app.adapters.base import Message
from app.services.events import publish_session_start

from .session_manager import get_or_create_session

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.models import Session as DBSession

logger = logging.getLogger(__name__)


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
    messages: list[dict[str, Any]],
) -> tuple[DBSession, str, bool, list[dict[str, Any]]]:
    """Setup session and prepare messages for completion.

    Args:
        db: Database session
        session_id: Optional existing session ID
        project_id: Project ID
        provider: Provider name
        model: Model identifier
        external_id: External ID for cost aggregation
        client_id: Client identifier
        request_source: Request source
        agent_slug: Agent slug for metrics
        messages: Input messages

    Returns:
        Tuple of (session, final_session_id, is_new_session, messages_dict)
    """
    final_session_id = session_id or str(uuid.uuid4())

    session, context_messages, is_new_session = await get_or_create_session(
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
    )
    final_session_id = session.id

    if is_new_session:
        await publish_session_start(final_session_id, model, project_id)

    # Merge context messages with input messages
    messages_dict = list(messages)
    if context_messages:
        context_as_dicts = [{"role": m.role, "content": m.content} for m in context_messages]
        messages_dict = context_as_dicts + messages_dict

    return session, final_session_id, is_new_session, messages_dict
