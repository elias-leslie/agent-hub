"""Session analysis for memory citation scanning and task outcome processing.

Provides two core functions:
1. analyze_session() - Extract and credit citations from CC transcripts or API sessions
2. process_task_outcome() - Propagate task success/failure to memory scoring
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy import select

from app.db import _get_session_factory
from app.models import MemoryInjectionMetric, Session, SessionEvent

from .citation_parser import extract_uuid_prefixes, resolve_full_uuids
from .memory_utils import build_group_id
from .metrics_collector import update_citation_metrics
from .service import MemoryScope
from .usage_tracker import track_referenced_batch, track_success_batch

logger = logging.getLogger(__name__)


@dataclass
class AnalysisResult:
    """Result of session citation analysis."""

    session_id: str
    citations_found: int
    citations_credited: int


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
) -> AnalysisResult:
    """Analyze a session for memory citations and credit them.

    Two paths:
    1. CC path: citation_prefixes provided directly (from Stop.sh transcript grep)
    2. API path: query session_events for assistant_message events, extract citations

    Args:
        session_id: Session to analyze
        citation_prefixes: Pre-extracted 8-char UUID prefixes (CC path)

    Returns:
        AnalysisResult with citation counts
    """
    prefixes: list[str] = []

    if citation_prefixes is not None:
        # CC path: use provided prefixes directly
        prefixes = [p.lower()[:8] for p in citation_prefixes if len(p) >= 8]
    else:
        # API path: scan session_events for citations
        prefixes = await _extract_citations_from_events(session_id)

    if not prefixes:
        return AnalysisResult(
            session_id=session_id,
            citations_found=0,
            citations_credited=0,
        )

    # Determine group_id from session's project
    group_id = await _get_session_group_id(session_id)

    # Resolve 8-char prefixes to full UUIDs
    prefix_to_uuid = await resolve_full_uuids(prefixes, group_id=group_id)
    resolved_uuids = list(prefix_to_uuid.values())

    if resolved_uuids:
        # Credit via usage tracker (citation = referenced, not helpful)
        # helpful/harmful are reserved for explicit user feedback
        await track_referenced_batch(resolved_uuids)

        # Store audit trail via event storage
        await _store_cite_event(session_id, resolved_uuids)

        # Update citation metrics on injection record
        await update_citation_metrics(
            session_id=session_id,
            memories_cited=resolved_uuids,
        )

    logger.info(
        "Session %s: found %d citation prefixes, credited %d",
        session_id,
        len(prefixes),
        len(resolved_uuids),
    )

    return AnalysisResult(
        session_id=session_id,
        citations_found=len(prefixes),
        citations_credited=len(resolved_uuids),
    )


async def process_task_outcome(
    session_id: str,
    succeeded: bool,
    task_id: str | None = None,
) -> TaskOutcomeResult:
    """Process task outcome and credit loaded memories on success.

    Steps:
    1. Update MemoryInjectionMetric.task_succeeded via update_citation_metrics()
    2. If succeeded: query memories_loaded from injection metrics, credit via track_success_batch()

    Args:
        session_id: Session that ran the task
        succeeded: Whether the task succeeded
        task_id: Optional task ID for correlation

    Returns:
        TaskOutcomeResult with processing counts
    """
    # Update task_succeeded on injection metrics
    metrics_updated = await update_citation_metrics(
        session_id=session_id,
        task_succeeded=succeeded,
    )

    memories_credited = 0

    if succeeded:
        # Query memories_loaded from injection metrics for this session
        loaded_uuids = await _get_memories_loaded(session_id)

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
    """Find Agent Hub session IDs associated with a task via injection metrics.

    Primary lookup: MemoryInjectionMetric.external_id matching task_id.
    Fallback: When external_id not set (common for CC interactive sessions),
    find sessions by project_id + time range from injection metrics.

    Args:
        task_id: SummitFlow task ID
        project_id: Project ID for fallback lookup
        started_at: ISO timestamp of task start for time-bounded fallback

    Returns:
        List of unique session IDs
    """
    session_factory = _get_session_factory()

    async with session_factory() as db:
        # Primary: lookup by external_id
        query = (
            select(MemoryInjectionMetric.session_id)
            .where(MemoryInjectionMetric.external_id == task_id)
            .where(MemoryInjectionMetric.session_id.isnot(None))
            .distinct()
        )
        result = await db.execute(query)
        session_ids = [sid for sid in result.scalars().all() if sid is not None]

        if session_ids:
            return session_ids

        # Fallback: lookup by project_id + time range
        # Requires both project_id AND started_at to avoid over-crediting
        if project_id and started_at:
            from datetime import datetime

            try:
                start_dt = datetime.fromisoformat(started_at)
            except ValueError:
                logger.warning("Invalid started_at format: %s", started_at)
                return session_ids

            fallback_query = (
                select(MemoryInjectionMetric.session_id)
                .where(MemoryInjectionMetric.project_id == project_id)
                .where(MemoryInjectionMetric.session_id.isnot(None))
                .where(MemoryInjectionMetric.task_succeeded.is_(None))
                .where(MemoryInjectionMetric.created_at >= start_dt)
                .distinct()
            )
            result = await db.execute(fallback_query)
            session_ids = [sid for sid in result.scalars().all() if sid is not None]

            if session_ids:
                logger.info(
                    "Task %s: found %d sessions via project fallback (project=%s, since=%s)",
                    task_id,
                    len(session_ids),
                    project_id,
                    started_at,
                )

        return session_ids


async def _extract_citations_from_events(session_id: str) -> list[str]:
    """Extract citation UUID prefixes from session_events assistant messages."""
    session_factory = _get_session_factory()

    async with session_factory() as db:
        query = (
            select(SessionEvent.content)
            .where(SessionEvent.session_id == session_id)
            .where(SessionEvent.event_type == "assistant_message")
        )
        result = await db.execute(query)
        rows = result.scalars().all()

    all_prefixes: set[str] = set()
    for content in rows:
        if content:
            prefixes = extract_uuid_prefixes(content)
            all_prefixes.update(prefixes)

    return list(all_prefixes)


async def _get_session_group_id(session_id: str) -> str:
    """Get the group_id for a session based on its project_id."""
    session_factory = _get_session_factory()

    async with session_factory() as db:
        query = select(Session.project_id).where(Session.id == session_id)
        result = await db.execute(query)
        project_id = result.scalar_one_or_none()

    if project_id:
        return build_group_id(MemoryScope.PROJECT, project_id)
    return "global"


async def _get_memories_loaded(session_id: str) -> list[str]:
    """Get all memory UUIDs loaded for a session from injection metrics."""
    session_factory = _get_session_factory()

    async with session_factory() as db:
        query = (
            select(MemoryInjectionMetric.memories_loaded)
            .where(MemoryInjectionMetric.session_id == session_id)
            .where(MemoryInjectionMetric.memories_loaded.isnot(None))
        )
        result = await db.execute(query)
        rows = result.scalars().all()

    # Flatten all loaded UUIDs across multiple injection records, deduplicate
    all_uuids: set[str] = set()
    for loaded in rows:
        if loaded:
            all_uuids.update(loaded)

    return list(all_uuids)


async def _store_cite_event(session_id: str, cited_uuids: list[str]) -> None:
    """Store a memory citation event for audit trail."""
    from app.services.event_storage import store_memory_cite_event

    session_factory = _get_session_factory()

    try:
        async with session_factory() as db:
            await store_memory_cite_event(db, session_id, cited_uuids)
            await db.commit()
    except Exception as e:
        logger.warning("Failed to store cite event for session %s: %s", session_id, e)
