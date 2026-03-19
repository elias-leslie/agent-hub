"""Hook to extract narration tags from stored assistant_message events.

Called after events are stored, extracts [[P:type:content]] tags and persists
them to the task_narration_tags table if the session is linked to a task.
"""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Session, SessionEventType
from app.services.narration_tags import parse_narration_tags
from app.storage.narration_tags import insert_narration_tags_bulk

logger = logging.getLogger(__name__)


async def extract_narration_from_event(
    db: AsyncSession,
    *,
    session_id: str,
    event_type: str,
    content: str | None,
    session: Session | None = None,
) -> int:
    """Extract and store narration tags from an assistant message event.

    Returns number of tags extracted. Skips silently if:
    - Event is not an assistant_message
    - No content or no [[P: tags in content
    - Session has no external_id (no linked task)
    """
    if event_type != SessionEventType.ASSISTANT_MESSAGE:
        return 0
    if not content or "[[P:" not in content:
        return 0

    tags = parse_narration_tags(content)
    if not tags:
        return 0

    # Resolve task_id from session's external_id
    if session is None:
        row = await db.execute(
            select(Session.external_id).where(Session.id == session_id).limit(1)
        )
        task_id = row.scalar_one_or_none()
    else:
        task_id = session.external_id

    if not task_id:
        return 0

    await insert_narration_tags_bulk(
        db,
        task_id=task_id,
        session_id=session_id,
        tags=[(t.tag_type, t.content) for t in tags],
    )
    logger.debug("Extracted %d narration tags for task %s", len(tags), task_id)
    return len(tags)
