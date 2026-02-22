"""Session analysis for memory citation scanning and task outcome processing.

Provides two core functions:
1. analyze_session() - Extract and credit citations from CC transcripts or API sessions
2. process_task_outcome() - Propagate task success/failure to memory scoring
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy import select

from .citation_parser import resolve_full_uuids
from .metrics_collector import update_citation_metrics
from .session_queries import (
    extract_citations_from_events,
    extract_feedback_from_events,
    find_sessions_by_task,
    get_memories_loaded,
    get_session_group_id,
    store_cite_event,
)
from .usage_tracker import track_helpful, track_referenced_batch, track_success_batch

logger = logging.getLogger(__name__)


@dataclass
class AnalysisResult:
    """Result of session citation analysis."""

    session_id: str
    citations_found: int
    citations_credited: int
    feedback_created: int = 0


@dataclass
class TaskOutcomeResult:
    """Result of task outcome processing."""

    session_id: str
    task_succeeded: bool
    metrics_updated: int
    memories_credited: int


async def analyze_session(
    session_id: str,
    citation_prefixes: list[str] | None = None,
    feedback_tags: list[str] | None = None,
) -> AnalysisResult:
    """Analyze a session for memory citations and credit them.

    Two paths:
    1. CC path: citation_prefixes provided directly (from Stop.sh transcript grep)
    2. API path: query session_events for assistant_message events, extract citations

    Feedback tags:
    - CC path: raw [F:...] strings from transcript grep
    - API path: scanned from session_events automatically

    Args:
        session_id: Session to analyze
        citation_prefixes: Pre-extracted 8-char UUID prefixes (CC path)
        feedback_tags: Raw [F:type:component] strings from CC transcript (CC path)

    Returns:
        AnalysisResult with citation and feedback counts
    """
    prefixes: list[str] = []

    if citation_prefixes is not None:
        # CC path: use provided prefixes directly
        prefixes = [p.lower()[:8] for p in citation_prefixes if len(p) >= 8]
    else:
        # API path: scan session_events for citations
        prefixes = await extract_citations_from_events(session_id)

    # --- Process feedback tags ---
    feedback_created = await _process_feedback_tags(session_id, feedback_tags)

    if not prefixes:
        return AnalysisResult(
            session_id=session_id,
            citations_found=0,
            citations_credited=0,
            feedback_created=feedback_created,
        )

    # Determine group_id from session's project
    group_id = await get_session_group_id(session_id)

    # Resolve 8-char prefixes to full UUIDs
    prefix_to_uuid = await resolve_full_uuids(prefixes, group_id=group_id)
    resolved_uuids = list(prefix_to_uuid.values())

    if resolved_uuids:
        await track_referenced_batch(resolved_uuids)
        for uuid in resolved_uuids:
            track_helpful(uuid)

        # Store audit trail via event storage
        await store_cite_event(session_id, resolved_uuids)

        # Update citation metrics on injection record
        await update_citation_metrics(
            session_id=session_id,
            memories_cited=resolved_uuids,
        )

    logger.info(
        "Session %s: found %d citation prefixes, credited %d, feedback %d",
        session_id,
        len(prefixes),
        len(resolved_uuids),
        feedback_created,
    )

    return AnalysisResult(
        session_id=session_id,
        citations_found=len(prefixes),
        citations_credited=len(resolved_uuids),
        feedback_created=feedback_created,
    )


async def _process_feedback_tags(
    session_id: str,
    feedback_tags: list[str] | None = None,
) -> int:
    """Process feedback tags from CC transcript or session events.

    Args:
        session_id: Session to process
        feedback_tags: Raw [F:...] strings from CC transcript, or None to scan events

    Returns:
        Count of feedback items created
    """
    from app.db import _get_session_factory
    from app.models import Session

    from .citation_parser import parse_feedback_tags

    tag_dicts: list[dict] = []

    if feedback_tags is not None:
        # CC path: parse raw strings from Stop.sh transcript grep
        for raw in feedback_tags:
            if not isinstance(raw, str):
                continue
            result = parse_feedback_tags(raw)
            for tag in result.tags:
                tag_dicts.append(tag.model_dump())
    else:
        # API path: scan session_events
        tag_dicts = await extract_feedback_from_events(session_id)

    if not tag_dicts:
        return 0

    from app.models.feedback import FeedbackItem
    from app.services.feedback_storage import create_feedback_item

    session_factory = _get_session_factory()

    async with session_factory() as db:
        # Get project_id and agent_slug from session
        row = await db.execute(
            select(Session.project_id, Session.agent_slug).where(Session.id == session_id)
        )
        session_info = row.one_or_none()
        if not session_info:
            logger.warning("Session %s not found for feedback processing", session_id)
            return 0
        project_id = session_info.project_id
        agent_slug = session_info.agent_slug

        # Get existing feedback for dedup
        existing_query = select(
            FeedbackItem.component_id, FeedbackItem.feedback_type
        ).where(FeedbackItem.created_by_session_id == session_id)
        existing_rows = await db.execute(existing_query)
        existing_keys = {(r.component_id, r.feedback_type) for r in existing_rows}

        created = 0
        for tag_dict in tag_dicts:
            key = (tag_dict["component_id"], tag_dict["feedback_type"])
            if key in existing_keys:
                continue

            desc = tag_dict.get("description", "")
            await create_feedback_item(
                db,
                component_id=tag_dict["component_id"],
                feedback_type=tag_dict["feedback_type"],
                title=desc[:120] if desc else f"{tag_dict['feedback_type']} on {tag_dict['component_id']}",
                description=desc or None,
                project_id=project_id,
                session_id=session_id,
                agent_slug=agent_slug,
                session_type="inline_tag",
            )
            existing_keys.add(key)
            created += 1

        if created:
            await db.commit()
            logger.info("Created %d feedback items for session %s", created, session_id)

    return created


async def process_task_outcome(
    session_id: str,
    succeeded: bool,
    task_id: str | None = None,
) -> TaskOutcomeResult:
    """Process task outcome and credit loaded memories on success.

    Updates MemoryInjectionMetric.task_succeeded and credits memories on success.
    """
    # Update task_succeeded on injection metrics
    metrics_updated = await update_citation_metrics(
        session_id=session_id,
        task_succeeded=succeeded,
    )

    memories_credited = 0

    if succeeded:
        # Query memories_loaded from injection metrics for this session
        loaded_uuids = await get_memories_loaded(session_id)

        if loaded_uuids:
            await track_success_batch(loaded_uuids)
            memories_credited = len(loaded_uuids)

    logger.info(
        "Task outcome for session %s: succeeded=%s, metrics_updated=%d, memories_credited=%d",
        session_id,
        succeeded,
        metrics_updated,
        memories_credited,
    )

    return TaskOutcomeResult(
        session_id=session_id,
        task_succeeded=succeeded,
        metrics_updated=metrics_updated,
        memories_credited=memories_credited,
    )


async def find_sessions_for_task(
    task_id: str,
    project_id: str | None = None,
    started_at: str | None = None,
) -> list[str]:
    """Find session IDs associated with a task via injection metrics."""
    return await find_sessions_by_task(task_id, project_id, started_at)
