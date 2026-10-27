"""Private helper functions for citation_tracker.py."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from sqlalchemy import select

from app.services.memory import (
    extract_uuid_prefixes,
    parse_memory_group_id,
    resolve_full_uuids,
    track_helpful,
    track_referenced_batch,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


def _build_group_id(memory_group_id: str | None) -> str:
    """Derive the group_id string from memory_group_id."""
    scope, scope_id = parse_memory_group_id(memory_group_id)
    if scope.value == "global":
        return "global"
    return f"{scope.value}-{scope_id}"


async def _resolve_cited_uuids(content: str, memory_group_id: str | None) -> list[str]:
    """Extract and resolve cited UUID prefixes from content. Returns [] if none found."""
    cited_prefixes = extract_uuid_prefixes(content)
    if not cited_prefixes:
        return []
    group_id = _build_group_id(memory_group_id)
    return list((await resolve_full_uuids(cited_prefixes, group_id)).values())


async def _track_memory_citations(
    content: str,
    memory_group_id: str | None,
    db: AsyncSession,
    session_id: str,
    agent_id: str | None,
    model_used: str | None,
) -> list[str]:
    """Resolve cited UUIDs and store DB events. Returns cited UUIDs."""
    cited_uuids = await _resolve_cited_uuids(content, memory_group_id)
    if not cited_uuids:
        return []
    await track_referenced_batch(cited_uuids)
    for cited_uuid in cited_uuids:
        track_helpful(cited_uuid)
    await _store_cite_event(db, session_id, cited_uuids, agent_id, model_used)
    await _update_metrics(session_id, cited_uuids)
    logger.info("Tracked %d cited memory rules", len(cited_uuids))
    return cited_uuids


async def _store_cite_event(
    db: AsyncSession,
    session_id: str,
    cited_uuids: list[str],
    agent_id: str | None,
    model_used: str | None,
) -> None:
    """Store a memory cite event, deduplicating against already-cited UUIDs."""
    from app.models.session import SessionEvent, SessionEventType
    from app.services.event_storage import store_memory_cite_event

    # Dedup: query existing memory_cite events for this session
    existing_query = (
        select(SessionEvent.tool_input)
        .where(
            SessionEvent.session_id == session_id,
            SessionEvent.event_type == SessionEventType.MEMORY_CITE,
        )
    )
    rows = await db.execute(existing_query)
    already_cited: set[str] = set()
    for (tool_input,) in rows:
        if isinstance(tool_input, dict):
            already_cited.update(tool_input.get("uuids", []))

    new_uuids = [u for u in cited_uuids if u not in already_cited]
    if not new_uuids:
        return

    await store_memory_cite_event(
        db, session_id, new_uuids, agent_id=agent_id, model_used=model_used
    )


async def _update_metrics(session_id: str, cited_uuids: list[str]) -> None:
    """Update citation metrics for cited UUIDs."""
    from app.services.memory.metrics_collector import update_citation_metrics

    await update_citation_metrics(session_id=session_id, memories_cited=cited_uuids)


async def _record_citation_metrics(
    cited_uuids: list[str],
    session_id: str,
    external_id: str | None,
    is_error: bool,
) -> None:
    """Update citation and helpfulness metrics for a list of cited UUIDs."""
    from app.services.memory.metrics_collector import update_citation_metrics

    await track_referenced_batch(cited_uuids)
    await update_citation_metrics(
        session_id=session_id,
        external_id=external_id,
        memories_cited=cited_uuids,
    )
    logger.info("Tracked %d citations", len(cited_uuids))

    if is_error:
        return
    for cited_uuid in cited_uuids:
        track_helpful(cited_uuid)
    logger.info("Auto-rated %d cited memories as helpful", len(cited_uuids))
