"""Citation tracking utilities for completion API."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from app.services.event_storage import store_memory_cite_event
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
    cited_uuids: list[str] = []

    if not loaded_memory_uuids or not content:
        return cited_uuids

    try:
        cited_prefixes = extract_uuid_prefixes(content)
        if cited_prefixes:
            scope, scope_id = parse_memory_group_id(memory_group_id)
            group_id = "global" if scope.value == "global" else f"{scope.value}-{scope_id}"
            prefix_to_uuid = await resolve_full_uuids(cited_prefixes, group_id)
            cited_uuids = list(prefix_to_uuid.values())
            if cited_uuids:
                await track_referenced_batch(cited_uuids)
                await store_memory_cite_event(
                    db, session_id, cited_uuids,
                    agent_id=agent_id, model_used=model_used,
                )
                logger.info(f"Tracked {len(cited_uuids)} cited memory rules")
    except Exception as e:
        logger.warning(f"Citation tracking failed (continuing): {e}")

    return cited_uuids


async def track_citations_with_metrics(
    content: str,
    loaded_memory_uuids: list[str],
    memory_group_id: str | None,
    session_id: str,
    external_id: str | None,
    is_error: bool,
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

    Returns:
        List of cited UUIDs
    """
    cited_uuids: list[str] = []

    if not loaded_memory_uuids or not content:
        return cited_uuids

    try:
        cited_prefixes = extract_uuid_prefixes(content)
        if cited_prefixes:
            scope, scope_id = parse_memory_group_id(memory_group_id)
            group_id = "global" if scope.value == "global" else f"{scope.value}-{scope_id}"
            cited_uuids = list((await resolve_full_uuids(cited_prefixes, group_id)).values())
            if cited_uuids:
                await track_referenced_batch(cited_uuids)
                from app.services.memory.metrics_collector import update_citation_metrics
                await update_citation_metrics(
                    session_id=session_id,
                    external_id=external_id,
                    memories_cited=cited_uuids,
                )
                logger.info(f"Tracked {len(cited_uuids)} citations")
                if not is_error:
                    for cited_uuid in cited_uuids:
                        track_helpful(cited_uuid)
                    logger.info(f"Auto-rated {len(cited_uuids)} cited memories as helpful")
    except Exception as e:
        logger.warning(f"Citation tracking failed: {e}")

    return cited_uuids
