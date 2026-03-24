"""Citation tracking utilities for completion API."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from app.services.memory.citation_parser import parse_feedback_tags, parse_summary_tags
from app.services.session_display_summary import extract_outcome_summary

from ._citation_helpers import (
    _create_new_feedback_items,
    _get_existing_feedback_keys,
    _record_citation_metrics,
    _resolve_cited_uuids,
    _resolve_project_id,
    _store_cite_event,
    _track_memory_citations,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


async def track_inline_feedback(
    content: str,
    db: AsyncSession,
    session_id: str,
    agent_id: str | None = None,
    model_used: str | None = None,
    project_id: str | None = None,
) -> int:
    """Parse [F:type:component] tags and create deduplicated feedback items.

    Returns count of feedback items created.
    """
    result = parse_feedback_tags(content)
    if not result.tags:
        return 0
    if not project_id:
        project_id = await _resolve_project_id(db, session_id)
    existing_keys = await _get_existing_feedback_keys(db, session_id)
    created, voted = await _create_new_feedback_items(
        db, result.tags, existing_keys, project_id, session_id, agent_id, model_used
    )
    if created or voted:
        await db.commit()
        logger.info(
            "Tracked inline feedback for session %s: created=%d voted=%d",
            session_id,
            created,
            voted,
        )
    return created


async def track_inline_summaries(
    content: str,
    db: AsyncSession,
    session_id: str,
    agent_id: str | None = None,
) -> bool:
    """Parse [[S:outcome:description]] tags and store the last summary on the session.

    Returns True if a summary was stored, False otherwise.
    """
    result = parse_summary_tags(content)
    if not result.tags:
        return False
    from app.services.memory.summary_generator import _enforce_oneliner, _store_summary_on_session

    tag = result.tags[-1]
    await _store_summary_on_session(
        session_id=session_id,
        summary_oneliner=_enforce_oneliner(tag.description),
        outcome=tag.outcome,
        files_touched=[],
        git_digest="",
        db=db,
    )
    logger.info("Stored inline summary for session %s: outcome=%s", session_id, tag.outcome)
    return True


def _extract_chat_summary(content: str) -> str:
    """Extract a concise outcome summary from assistant content."""
    return extract_outcome_summary(content, max_chars=120) or ""


async def _ensure_synthetic_summary(
    content: str,
    session_id: str,
    db: AsyncSession | None = None,
) -> bool:
    """Generate a synthetic summary from content when no inline tags were found.

    Uses _store_summary_on_session (independent DB session) — appropriate for both
    streaming paths (no outer DB session) and non-streaming paths (independent write).
    """
    from app.services.memory.summary_generator import _enforce_oneliner, _store_summary_on_session

    summary = _extract_chat_summary(content)
    if not summary:
        return False

    await _store_summary_on_session(
        session_id=session_id,
        summary_oneliner=_enforce_oneliner(summary),
        outcome="completed",
        files_touched=[],
        git_digest="",
        db=db,
    )
    logger.info("Stored synthetic summary for chat session %s", session_id)
    return True


async def _track_inline_tags(
    content: str,
    db: AsyncSession,
    session_id: str,
    agent_id: str | None,
    model_used: str | None,
) -> None:
    """Run inline feedback and summary tracking, suppressing non-fatal errors."""
    try:
        await track_inline_feedback(content, db, session_id, agent_id=agent_id, model_used=model_used)
    except Exception as e:
        logger.warning("Inline feedback tracking failed (continuing): %s", e)
    summary_stored = False
    try:
        summary_stored = await track_inline_summaries(content, db, session_id, agent_id=agent_id)
    except Exception as e:
        logger.warning("Inline summary tracking failed (continuing): %s", e)
    # Fallback: generate synthetic summary if no inline [[S:...]] tag was found
    if not summary_stored:
        try:
            await _ensure_synthetic_summary(content, session_id, db=db)
        except Exception as e:
            logger.warning("Synthetic summary generation failed (continuing): %s", e)


async def track_citations(
    content: str,
    loaded_memory_uuids: list[str],
    memory_group_id: str | None,
    db: AsyncSession,
    session_id: str,
    agent_id: str | None = None,
    model_used: str | None = None,
) -> list[str]:
    """Track memory citations in content. Returns list of cited UUIDs."""
    if not content:
        return []
    await _track_inline_tags(content, db, session_id, agent_id, model_used)
    if not loaded_memory_uuids:
        return []
    try:
        return await _track_memory_citations(content, memory_group_id, db, session_id, agent_id, model_used)
    except Exception as e:
        logger.warning(f"Citation tracking failed (continuing): {e}")
        return []


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
    """Track citations and update metrics for single-turn completion handlers.

    When a DB session is available, persist the `memory_cite` audit event as well.
    """
    if not content:
        return []
    if db:
        await _track_inline_tags(content, db, session_id, agent_id, model_used)
    if not loaded_memory_uuids:
        return []
    try:
        cited_uuids = await _resolve_cited_uuids(content, memory_group_id)
        if not cited_uuids:
            return []
        if db:
            await _store_cite_event(db, session_id, cited_uuids, agent_id, model_used)
            await db.commit()
        await _record_citation_metrics(cited_uuids, session_id, external_id, is_error)
        return cited_uuids
    except Exception as e:
        logger.warning(f"Citation tracking failed: {e}")
        return []
