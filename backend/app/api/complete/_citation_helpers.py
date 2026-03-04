"""Private helper functions for citation_tracker.py."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from sqlalchemy import select

from app.models.feedback import FeedbackItem
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


async def _resolve_project_id(db: AsyncSession, session_id: str) -> str:
    """Query and return project_id for a session, defaulting to 'unknown'."""
    from app.models import Session

    row = await db.execute(select(Session.project_id).where(Session.id == session_id))
    return row.scalar_one_or_none() or "unknown"


async def _get_existing_feedback_keys(
    db: AsyncSession, session_id: str
) -> set[tuple[str, str]]:
    """Return set of (component_id, feedback_type) already stored for session."""
    existing_query = select(FeedbackItem.component_id, FeedbackItem.feedback_type).where(
        FeedbackItem.created_by_session_id == session_id
    )
    existing_rows = await db.execute(existing_query)
    return {(r.component_id, r.feedback_type) for r in existing_rows}


async def _create_new_feedback_items(
    db: AsyncSession,
    tags: list,
    existing_keys: set[tuple[str, str]],
    project_id: str,
    session_id: str,
    agent_id: str | None,
    model_used: str | None,
) -> int:
    """Create feedback items for tags not already in existing_keys.

    Cross-session dedup: if a similar open item already exists, vote on it
    instead of creating a duplicate.

    Returns count of items created (not votes).
    """
    from app.services.feedback_storage import (
        create_feedback_item,
        find_duplicate_candidates,
        vote_on_item,
    )

    created = 0
    for tag in tags:
        key = (tag.component_id, tag.feedback_type)
        if key in existing_keys:
            continue

        title = tag.description[:120] if tag.description else f"{tag.feedback_type} on {tag.component_id}"

        # Cross-session dedup: check for existing similar items
        try:
            duplicates = await find_duplicate_candidates(
                db, component_id=tag.component_id, title=title, limit=1,
            )
            if duplicates:
                await vote_on_item(
                    db,
                    item_id=str(duplicates[0].id),
                    session_id=session_id,
                    comment=tag.description,
                    agent_slug=agent_id,
                    model_used=model_used,
                )
                existing_keys.add(key)
                logger.debug(
                    "Dedup vote: %s/%s → existing %s",
                    tag.component_id, tag.feedback_type, str(duplicates[0].id)[:8],
                )
                continue
        except Exception:
            logger.debug("Dedup check failed, creating new item", exc_info=True)

        await create_feedback_item(
            db,
            component_id=tag.component_id,
            feedback_type=tag.feedback_type,
            title=title,
            description=tag.description or None,
            project_id=project_id,
            session_id=session_id,
            agent_slug=agent_id,
            model_used=model_used,
            session_type="inline_tag",
        )
        existing_keys.add(key)
        created += 1
    return created


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
    """Store a memory cite event in the database."""
    from app.services.event_storage import store_memory_cite_event

    await store_memory_cite_event(
        db, session_id, cited_uuids, agent_id=agent_id, model_used=model_used
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
