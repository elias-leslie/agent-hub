"""Citation tracking utilities for completion API."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from sqlalchemy import select

from app.models.feedback import FeedbackItem
from app.services.event_storage import store_memory_cite_event
from app.services.memory import (
    extract_uuid_prefixes,
    parse_memory_group_id,
    resolve_full_uuids,
    track_helpful,
    track_referenced_batch,
)
from app.services.memory.citation_parser import parse_feedback_tags

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


async def track_inline_feedback(
    content: str,
    db: AsyncSession,
    session_id: str,
    agent_id: str | None = None,
    model_used: str | None = None,
    project_id: str | None = None,
) -> int:
    """Parse and store inline feedback tags from content.

    Scans for [F:type:component] tags and creates feedback items.
    Deduplicates by (session_id, component_id, feedback_type) within a session.

    Returns:
        Count of feedback items created.
    """
    from app.services.feedback_storage import create_feedback_item

    result = parse_feedback_tags(content)
    if not result.tags:
        return 0

    # Resolve project_id from session if not provided
    if not project_id:
        from app.models import Session

        row = await db.execute(
            select(Session.project_id).where(Session.id == session_id)
        )
        project_id = row.scalar_one_or_none() or "unknown"

    # Get existing feedback for this session to dedup
    existing_query = (
        select(FeedbackItem.component_id, FeedbackItem.feedback_type)
        .where(FeedbackItem.created_by_session_id == session_id)
    )
    existing_rows = await db.execute(existing_query)
    existing_keys = {(r.component_id, r.feedback_type) for r in existing_rows}

    created = 0
    for tag in result.tags:
        key = (tag.component_id, tag.feedback_type)
        if key in existing_keys:
            continue

        await create_feedback_item(
            db,
            component_id=tag.component_id,
            feedback_type=tag.feedback_type,
            title=tag.description[:120] if tag.description else f"{tag.feedback_type} on {tag.component_id}",
            description=tag.description or None,
            project_id=project_id,
            session_id=session_id,
            agent_slug=agent_id,
            model_used=model_used,
            session_type="inline_tag",
        )
        existing_keys.add(key)
        created += 1

    if created:
        await db.commit()
        logger.info("Created %d inline feedback items for session %s", created, session_id)

    return created


async def track_citations(
    content: str,
    loaded_memory_uuids: list[str],
    memory_group_id: str | None,
    db: AsyncSession,
    session_id: str,
    agent_id: str | None = None,
    model_used: str | None = None,
) -> list[str]:
    """Track memory citations in content.

    Args:
        content: Response content to scan for citations
        loaded_memory_uuids: UUIDs that were loaded for this request
        memory_group_id: Memory group identifier
        db: Database session
        session_id: Session identifier
        agent_id: Agent slug for attribution
        model_used: Model used for attribution

    Returns:
        List of cited UUIDs
    """
    if not content:
        return []

    # Track inline feedback tags (independent of memory loading)
    try:
        await track_inline_feedback(
            content, db, session_id,
            agent_id=agent_id, model_used=model_used,
        )
    except Exception as e:
        logger.warning(f"Inline feedback tracking failed (continuing): {e}")

    if not loaded_memory_uuids:
        return []

    try:
        cited_uuids = await _resolve_cited_uuids(content, memory_group_id)
        if not cited_uuids:
            return []
        await track_referenced_batch(cited_uuids)
        for cited_uuid in cited_uuids:
            track_helpful(cited_uuid)
        await store_memory_cite_event(
            db, session_id, cited_uuids,
            agent_id=agent_id, model_used=model_used,
        )
        from app.services.memory.metrics_collector import update_citation_metrics

        await update_citation_metrics(
            session_id=session_id,
            memories_cited=cited_uuids,
        )
        logger.info(f"Tracked {len(cited_uuids)} cited memory rules")
        return cited_uuids
    except Exception as e:
        logger.warning(f"Citation tracking failed (continuing): {e}")
        return []


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
    logger.info(f"Tracked {len(cited_uuids)} citations")

    if is_error:
        return
    for cited_uuid in cited_uuids:
        track_helpful(cited_uuid)
    logger.info(f"Auto-rated {len(cited_uuids)} cited memories as helpful")


async def track_citations_with_metrics(
    content: str,
    loaded_memory_uuids: list[str],
    memory_group_id: str | None,
    session_id: str,
    external_id: str | None,
    is_error: bool,
    db: AsyncSession | None = None,
    agent_id: str | None = None,
    model_used: str | None = None,
) -> list[str]:
    """Track citations and update metrics (helpfulness + citation metrics).

    Unlike track_citations, this does not store DB events but updates
    in-memory metrics. Use this in single-turn completion handlers.

    Args:
        content: Response content to scan for citations
        loaded_memory_uuids: UUIDs that were loaded for this request
        memory_group_id: Memory group identifier
        session_id: Session identifier
        external_id: External ID for metrics attribution
        is_error: Whether the response is an error (skips helpfulness rating)
        db: Optional database session for feedback tracking
        agent_id: Agent slug for attribution
        model_used: Model used for attribution

    Returns:
        List of cited UUIDs
    """
    if not content:
        return []

    # Track inline feedback tags (independent of memory loading)
    if db:
        try:
            await track_inline_feedback(
                content, db, session_id,
                agent_id=agent_id, model_used=model_used,
            )
        except Exception as e:
            logger.warning(f"Inline feedback tracking failed (continuing): {e}")

    if not loaded_memory_uuids:
        return []

    try:
        cited_uuids = await _resolve_cited_uuids(content, memory_group_id)
        if not cited_uuids:
            return []
        await _record_citation_metrics(cited_uuids, session_id, external_id, is_error)
        return cited_uuids
    except Exception as e:
        logger.warning(f"Citation tracking failed: {e}")
        return []
